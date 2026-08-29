#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微调 vs 未微调重排序对照：同一批候选，两套模型重新打分。

默认优先用 GPU（fp16）。

用法:
  python scripts/eval_reranker_ablation.py
"""
from __future__ import annotations

import gc
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.eval_retrieval_lexical import (  # noqa: E402
    is_invalid_gold,
    ngram_recall,
    split_numbered_context,
    wilson_interval,
)

BASE_PATH = ROOT / "models/BAAI/bge-reranker-v2-m3"
TUNED_PATH = ROOT / "RAG-Retrieval/rag_retrieval/train/reranker/output/bert/runs/checkpoints/checkpoint_0"
PRED_PATH = ROOT / "data/qa_pairs/test_qa_pair_pred.json"
LIST_PATH = ROOT / "data/rerank_data/test.json"
OUT_DIR = ROOT / "test/eval_results"

MAX_LEN = 512
BATCH = 16 if torch.cuda.is_available() else 8
USE_CUDA = torch.cuda.is_available()
DEVICE = torch.device("cuda" if USE_CUDA else "cpu")
USE_FP16 = USE_CUDA
if not USE_CUDA:
    torch.set_num_threads(max(1, os.cpu_count() or 8))


def require_weights(path: Path, label: str) -> Path:
    if not (path / "config.json").exists():
        raise SystemExit(f"缺少{label} config.json: {path}")
    candidates = [p for p in path.glob("*") if p.suffix in {".bin", ".safetensors"} and p.is_file()]
    candidates = [p for p in candidates if p.name != "tokenizer.json"]
    if not candidates:
        raise SystemExit(f"{label}权重未就绪: {path}")
    weight = max(candidates, key=lambda p: p.stat().st_size)
    size_gb = weight.stat().st_size / (1024**3)
    if size_gb < 1.5:
        raise SystemExit(f"{label}权重不完整 ({weight.name} {size_gb:.2f}GB): {path}")
    print(f"[{label}] weights={weight.name} size={size_gb:.2f}GB", flush=True)
    return weight


def load_ranker(path: Path):
    tok = AutoTokenizer.from_pretrained(str(path))
    model = AutoModelForSequenceClassification.from_pretrained(str(path))
    model.eval()
    model.to(DEVICE)
    if USE_FP16:
        model.half()
    return tok, model


@torch.no_grad()
def score_pairs(tok, model, pairs: list[tuple[str, str]]) -> list[float]:
    out = []
    n = len(pairs)
    t0 = time.time()
    for i in range(0, n, BATCH):
        batch = pairs[i : i + BATCH]
        inputs = tok(
            batch,
            padding=True,
            truncation=True,
            return_tensors="pt",
            max_length=MAX_LEN,
        )
        inputs = {k: v.to(DEVICE) for k, v in inputs.items()}
        logits = model(**inputs).logits.squeeze(-1)
        if logits.ndim == 0:
            out.append(float(logits.float().cpu()))
        else:
            out.extend(logits.float().detach().cpu().tolist())
        done = min(i + BATCH, n)
        if done == n or done % 128 == 0:
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta = (n - done) / rate if rate > 0 else 0
            print(f"    scored {done}/{n}  {rate:.1f} pairs/s  eta={eta/60:.1f}min", flush=True)
    return out


def graded_rel(support: float) -> float:
    """将 4-gram 覆盖率映射为分级相关度，用于 NDCG。"""
    if support >= 0.5:
        return 3.0
    if support >= 0.2:
        return 2.0
    if support >= 0.05:
        return 1.0
    return 0.0


def ndcg_at_k(rels: list[float], k: int) -> float:
    gains = rels[:k]
    dcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sorted(rels, reverse=True)[:k]
    idcg = sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def ranking_metrics(gold: str, chunks: list[str], scores: list[float]) -> dict:
    order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
    support = [ngram_recall(gold, c, n=4) for c in chunks]
    best = max(range(len(chunks)), key=lambda i: support[i])
    rank = order.index(best) + 1
    top1_rel = support[order[0]] >= 0.2 if order else False
    graded = [graded_rel(support[i]) for i in order]
    return {
        "hit1": int(rank == 1),
        "hit3": int(rank <= 3),
        "hit5": int(rank <= 5),
        "mrr": 1.0 / rank,
        "p1": int(top1_rel),
        "ndcg5": ndcg_at_k(graded, min(5, len(chunks))),
        "ndcg10": ndcg_at_k(graded, min(10, len(chunks))),
        "max_support": max(support) if support else 0.0,
    }


def load_rag_samples() -> list[dict]:
    data = json.loads(PRED_PATH.read_text(encoding="utf-8"))
    rows = []
    for item in data:
        gold = (item.get("answer") or "").strip()
        q = (item.get("question") or "").strip()
        chunks = split_numbered_context(item.get("context") or "")
        if is_invalid_gold(gold) or not q or not chunks:
            continue
        rows.append({"query": q, "gold": gold, "chunks": chunks})
    return rows


def load_listwise_samples() -> list[dict]:
    rows = []
    for line in LIST_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        info = json.loads(line)
        docs = info.get("content") or []
        if len(docs) < 2:
            continue
        rows.append({"query": info["query"], "docs": docs})
    return rows


def pct(x: float) -> float:
    return round(100.0 * x, 2)


def summarize_rag(rows: list[dict], score_lists: list[list[float]], elapsed_sec: float) -> dict:
    hit1 = hit3 = hit5 = p1 = 0
    mrr = ndcg5 = ndcg10 = 0.0
    evidence = 0
    for r, s in zip(rows, score_lists):
        m = ranking_metrics(r["gold"], r["chunks"], s)
        hit1 += m["hit1"]
        hit3 += m["hit3"]
        hit5 += m["hit5"]
        p1 += m["p1"]
        mrr += m["mrr"]
        ndcg5 += m["ndcg5"]
        ndcg10 += m["ndcg10"]
        evidence += int(m["max_support"] >= 0.5)
    n = len(rows)
    return {
        "n": n,
        "elapsed_sec": round(elapsed_sec, 1),
        "definitions": {
            "support_doc": "与金标答案 4-gram recall 最高的候选块",
            "hit@k": "支撑块排在前 k",
            "p@1": "精排第1块 4-gram recall >= 0.2",
            "mrr": "支撑块名次倒数均值",
            "ndcg@k": "按 4-gram 覆盖率分级相关度(3/2/1/0)计算",
            "evidence_recall": "候选中是否存在 4-gram recall>=0.5 的块（与重排无关，同候选集应一致）",
        },
        "hit@1": round(hit1 / n, 4),
        "hit@1_pct": pct(hit1 / n),
        "hit@1_count": hit1,
        "hit@1_ci95": [round(x, 4) for x in wilson_interval(hit1, n)],
        "hit@1_ci95_pct": [pct(x) for x in wilson_interval(hit1, n)],
        "hit@3": round(hit3 / n, 4),
        "hit@3_pct": pct(hit3 / n),
        "hit@3_count": hit3,
        "hit@3_ci95": [round(x, 4) for x in wilson_interval(hit3, n)],
        "hit@5": round(hit5 / n, 4),
        "hit@5_pct": pct(hit5 / n),
        "hit@5_count": hit5,
        "hit@5_ci95": [round(x, 4) for x in wilson_interval(hit5, n)],
        "p@1": round(p1 / n, 4),
        "p@1_pct": pct(p1 / n),
        "p@1_count": p1,
        "p@1_ci95": [round(x, 4) for x in wilson_interval(p1, n)],
        "mrr": round(mrr / n, 4),
        "ndcg@5": round(ndcg5 / n, 4),
        "ndcg@10": round(ndcg10 / n, 4),
        "evidence_recall": round(evidence / n, 4),
        "evidence_recall_pct": pct(evidence / n),
        "evidence_recall_count": evidence,
    }


def eval_rag(name: str, tok, model, rows: list[dict]) -> dict:
    t0 = time.time()
    pairs = [(r["query"], c) for r in rows for c in r["chunks"]]
    print(f"[{name}] RAG pairs={len(pairs)} queries={len(rows)}", flush=True)
    scores = score_pairs(tok, model, pairs)
    idx = 0
    score_lists = []
    for r in rows:
        n = len(r["chunks"])
        score_lists.append(scores[idx : idx + n])
        idx += n
    return summarize_rag(rows, score_lists, time.time() - t0)


def eval_rag_file_order(rows: list[dict]) -> dict:
    """当前文件里的块顺序 = 线上已保存的精排顺序。"""
    score_lists = [[float(len(r["chunks"]) - i) for i in range(len(r["chunks"]))] for r in rows]
    return summarize_rag(rows, score_lists, 0.0)


def eval_listwise(name: str, tok, model, rows: list[dict]) -> dict:
    t0 = time.time()
    pairs = [(r["query"], d) for r in rows for d in r["docs"]]
    print(f"[{name}] listwise pairs={len(pairs)} queries={len(rows)}", flush=True)
    scores = score_pairs(tok, model, pairs)
    idx = 0
    hit1 = pairwise = 0
    ndcgs = []
    for r in rows:
        n = len(r["docs"])
        s = scores[idx : idx + n]
        idx += n
        order = sorted(range(n), key=lambda i: s[i], reverse=True)
        if order[0] == 0:
            hit1 += 1
        if all(s[i] >= s[i + 1] for i in range(n - 1)):
            pairwise += 1
        # 约定 content[0] 最相关，label 递减
        rels = [n - 1 - i for i in order]
        ndcgs.append(ndcg_at_k(rels, min(3, n)))
    nq = len(rows)
    return {
        "n": nq,
        "elapsed_sec": round(time.time() - t0, 1),
        "definitions": {
            "label": "约定 content[0] 最相关，其后递减；负例多为易区分样本",
            "hit@1": "得分最高文档是否为 content[0]",
            "pairwise_acc": "得分是否严格按 content 顺序非增",
            "ndcg@3": "按约定相关度分级计算",
        },
        "hit@1": round(hit1 / nq, 4),
        "hit@1_pct": pct(hit1 / nq),
        "hit@1_count": hit1,
        "hit@1_ci95": [round(x, 4) for x in wilson_interval(hit1, nq)],
        "hit@1_ci95_pct": [pct(x) for x in wilson_interval(hit1, nq)],
        "pairwise_acc": round(pairwise / nq, 4),
        "pairwise_acc_pct": pct(pairwise / nq),
        "ndcg@3": round(sum(ndcgs) / nq, 4),
    }


def delta(a: dict, b: dict, keys: list[str]) -> dict:
    out = {}
    for k in keys:
        if isinstance(a.get(k), (int, float)) and isinstance(b.get(k), (int, float)):
            d = b[k] - a[k]
            out[k] = round(d, 4)
            if k.endswith("_pct") or k in {"hit@1", "hit@3", "hit@5", "p@1", "pairwise_acc", "ndcg@3", "ndcg@5", "ndcg@10", "mrr", "evidence_recall"}:
                # 百分点：若原值是比例，另给 pp
                if not k.endswith("_pct") and a[k] <= 1.0:
                    out[f"{k}_pp"] = round(100.0 * d, 2)
    return out


def main():
    require_weights(BASE_PATH, "base")
    require_weights(TUNED_PATH, "tuned")

    rag_rows = load_rag_samples()
    list_rows = load_listwise_samples()
    avg_chunks = sum(len(r["chunks"]) for r in rag_rows) / max(1, len(rag_rows))
    print(
        f"loaded rag={len(rag_rows)} listwise={len(list_rows)} "
        f"device={DEVICE} fp16={USE_FP16} batch={BATCH} max_len={MAX_LEN} avg_chunks={avg_chunks:.2f}",
        flush=True,
    )

    results = {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "protocol": {
            "task": "reranker ablation: official bge-reranker-v2-m3 vs fine-tuned checkpoint",
            "device": str(DEVICE),
            "precision": "fp16" if USE_FP16 else "fp32",
            "max_length": MAX_LEN,
            "batch_size": BATCH,
            "rag_set": {
                "path": str(PRED_PATH),
                "n": len(rag_rows),
                "avg_candidates": round(avg_chunks, 2),
                "candidate_source": "同一批融合召回后的候选块（来自 test_qa_pair_pred.json 的 context）",
                "labeling": "金标答案 vs 候选块的 4-gram recall 作为支撑判定",
            },
            "listwise_set": {
                "path": str(LIST_PATH),
                "n": len(list_rows),
                "labeling": "约定 content[0] 最相关；偏训练分布，负例较易",
            },
            "models": {
                "base": str(BASE_PATH),
                "tuned": str(TUNED_PATH),
            },
        },
        "file_order": {"rag": eval_rag_file_order(rag_rows)},
    }
    print(f"[file_order] rag hit@1={results['file_order']['rag']['hit@1_pct']}%", flush=True)

    for name, path in [("base", BASE_PATH), ("tuned", TUNED_PATH)]:
        print(f"\n=== load {name} {path} ===", flush=True)
        tok, model = load_ranker(path)
        results[name] = {
            "path": str(path),
            "rag": eval_rag(name, tok, model, rag_rows),
            "listwise": eval_listwise(name, tok, model, list_rows),
        }
        del model
        del tok
        gc.collect()
        if USE_CUDA:
            torch.cuda.empty_cache()

    results["delta_tuned_minus_base"] = {
        "rag": delta(
            results["base"]["rag"],
            results["tuned"]["rag"],
            ["hit@1", "hit@3", "hit@5", "p@1", "mrr", "ndcg@5", "ndcg@10", "hit@1_pct", "hit@3_pct", "hit@5_pct", "p@1_pct"],
        ),
        "listwise": delta(
            results["base"]["listwise"],
            results["tuned"]["listwise"],
            ["hit@1", "pairwise_acc", "ndcg@3", "hit@1_pct", "pairwise_acc_pct"],
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"reranker_ablation_{results['timestamp']}.json"
    latest = OUT_DIR / "reranker_ablation_latest.json"
    text = json.dumps(results, ensure_ascii=False, indent=2)
    out.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    print(text)
    print(f"[saved] {out}")


if __name__ == "__main__":
    main()
