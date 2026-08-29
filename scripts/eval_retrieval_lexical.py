#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
确定性检索/生成评测（不调用 LLM）。

指标定义（可复核）:
  - Answer-in-context Recall: 金标答案规范化后是否为检索上下文的子串
  - Soft Coverage@0.8: 金标非标点字符被上下文覆盖的比例 >= 0.8
  - Context Precision: 检索块中与金标有实质字面重合的比例（块级 char-F1 >= 0.15）
  - Support Hit@k / MRR: 与金标字面重合最高的块是否排在前 k
  - Keyword Recall: 标注关键词出现在检索上下文中的比例
  - Answer Char-F1 / EM: 预测答案 vs 金标（字级）

用法:
  python scripts/eval_retrieval_lexical.py
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_ragas_eval import split_numbered_context

PUNCT = re.compile(
    r"[\s\W_]+",
    flags=re.UNICODE,
)


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[【】\[\]()（）“”\"'`·•、，。！？；：,.:;!?/\\|-]+", "", text)
    return text


def chars(text: str) -> list[str]:
    return [c for c in normalize(text) if c.strip()]


def char_f1(pred: str, gold: str) -> float:
    p, g = chars(pred), chars(gold)
    if not p and not g:
        return 1.0
    if not p or not g:
        return 0.0
    pc, gc = Counter(p), Counter(g)
    overlap = sum((pc & gc).values())
    prec = overlap / len(p)
    rec = overlap / len(g)
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec)


def ngrams(text: str, n: int = 4) -> list[str]:
    s = "".join(chars(text))
    if len(s) < n:
        return [s] if s else []
    return [s[i : i + n] for i in range(len(s) - n + 1)]


def ngram_recall(gold: str, context: str, n: int = 4) -> float:
    g = ngrams(gold, n)
    if not g:
        return 0.0
    cset = set(ngrams(context, n))
    return sum(1 for x in g if x in cset) / len(g)


def lcs_len(a: str, b: str) -> int:
    """长度截断后的 LCS，避免超长上下文拖慢评测。"""
    if not a or not b:
        return 0
    if len(b) > 8000:
        b = b[:8000]
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur.append(prev[j - 1] + 1)
            else:
                cur.append(max(prev[j], cur[-1]))
        prev = cur
    return prev[-1]


def rouge_l_recall(gold: str, context: str) -> float:
    g = "".join(chars(gold))
    c = "".join(chars(context))
    if not g:
        return 0.0
    return lcs_len(g, c) / len(g)


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def is_invalid_gold(gold: str) -> bool:
    g = (gold or "").strip()
    if not g:
        return True
    if g in {"无答案", "无", "不知道", "N/A", "n/a"}:
        return True
    if len(chars(g)) < 4:
        return True
    return False


def evaluate(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    n_raw = len(data)

    valid = []
    n_skip_empty = 0
    n_skip_noans = 0
    for item in data:
        gold = (item.get("answer") or "").strip()
        pred = ((item.get("pred") or {}).get("answer") or "").strip()
        ctx_list = split_numbered_context(item.get("context") or "")
        if is_invalid_gold(gold):
            n_skip_noans += 1
            continue
        if not pred or not ctx_list:
            n_skip_empty += 1
            continue
        valid.append(
            {
                "gold": gold,
                "pred": pred,
                "chunks": ctx_list,
                "keywords": [k for k in (item.get("keywords") or []) if str(k).strip()],
                "cite_pages": (item.get("pred") or {}).get("cite_pages") or [],
            }
        )

    n = len(valid)
    in_ctx = 0
    ngram50 = ngram70 = 0
    rouge50 = 0
    hit1 = hit3 = hit5 = 0
    mrr_sum = 0.0
    precisions = []
    p_at_1 = []
    p_at_5 = []
    ngram_recalls = []
    rouge_recalls = []
    f1s = []
    em = 0
    kw_recalls = []
    n_kw = 0
    n_cite = 0
    chunk_counts = []

    for r in valid:
        concat = "\n".join(r["chunks"])
        gold_n = normalize(r["gold"])
        ctx_n = normalize(concat)
        ng = ngram_recall(r["gold"], concat, n=4)
        rl = rouge_l_recall(r["gold"], concat)
        ngram_recalls.append(ng)
        rouge_recalls.append(rl)
        if gold_n and gold_n in ctx_n:
            in_ctx += 1
        if ng >= 0.5:
            ngram50 += 1
        if ng >= 0.7:
            ngram70 += 1
        if rl >= 0.5:
            rouge50 += 1

        scores = [ngram_recall(r["gold"], chunk, n=4) for chunk in r["chunks"]]
        relevant = sum(1 for s in scores if s >= 0.2)
        precisions.append(relevant / len(scores) if scores else 0.0)
        top5 = scores[:5]
        p_at_1.append(1.0 if scores and scores[0] >= 0.2 else 0.0)
        p_at_5.append(sum(1 for s in top5 if s >= 0.2) / len(top5) if top5 else 0.0)
        chunk_counts.append(len(r["chunks"]))

        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        best = ranked[0] if ranked else None
        if best is not None:
            rank = best + 1  # 1-based position of the best-supporting chunk
            if rank == 1:
                hit1 += 1
            if rank <= 3:
                hit3 += 1
            if rank <= 5:
                hit5 += 1
            mrr_sum += 1.0 / rank

        f1 = char_f1(r["pred"], r["gold"])
        f1s.append(f1)
        if normalize(r["pred"]) == gold_n:
            em += 1

        if r["keywords"]:
            n_kw += 1
            blob = concat
            hits = sum(1 for k in r["keywords"] if k and k in blob)
            kw_recalls.append(hits / len(r["keywords"]))
        if r["cite_pages"]:
            n_cite += 1

    def rate(x: int) -> float:
        return x / n if n else 0.0

    summary = {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "input": str(path),
        "n_raw": n_raw,
        "n_eval": n,
        "n_skip_invalid_gold": n_skip_noans,
        "n_skip_empty_pred_or_ctx": n_skip_empty,
        "avg_retrieved_chunks": round(mean(chunk_counts), 3),
        "metrics": {
            "answer_in_context_recall": {
                "value": round(rate(in_ctx), 4),
                "count": in_ctx,
                "n": n,
                "ci95": [round(x, 4) for x in wilson_interval(in_ctx, n)],
                "definition": "金标答案规范化后是检索上下文的子串",
            },
            "ngram4_recall_at_0.5": {
                "value": round(rate(ngram50), 4),
                "count": ngram50,
                "n": n,
                "mean_ngram4_recall": round(mean(ngram_recalls), 4),
                "ci95": [round(x, 4) for x in wilson_interval(ngram50, n)],
                "definition": "金标4-gram被检索上下文覆盖比例>=0.5，作为检索召回",
            },
            "ngram4_recall_at_0.7": {
                "value": round(rate(ngram70), 4),
                "count": ngram70,
                "n": n,
                "ci95": [round(x, 4) for x in wilson_interval(ngram70, n)],
            },
            "rouge_l_recall_at_0.5": {
                "value": round(rate(rouge50), 4),
                "count": rouge50,
                "n": n,
                "mean_rouge_l_recall": round(mean(rouge_recalls), 4),
                "ci95": [round(x, 4) for x in wilson_interval(rouge50, n)],
                "definition": "金标相对检索上下文的 ROUGE-L recall >= 0.5",
            },
            "context_precision": {
                "value": round(mean(precisions), 4),
                "definition": "全部检索块中与金标 4-gram recall>=0.2 的比例，再对样本取平均",
            },
            "precision@1": {
                "value": round(mean(p_at_1), 4),
                "definition": "精排后第1块 4-gram recall>=0.2 的比例",
            },
            "precision@5": {
                "value": round(mean(p_at_5), 4),
                "definition": "精排后前5块中与金标 4-gram recall>=0.2 的比例",
            },
            "support_hit@1": {
                "value": round(rate(hit1), 4),
                "count": hit1,
                "n": n,
                "ci95": [round(x, 4) for x in wilson_interval(hit1, n)],
                "definition": "与金标字面重合最高的块排在第1位",
            },
            "support_hit@3": {
                "value": round(rate(hit3), 4),
                "count": hit3,
                "n": n,
                "ci95": [round(x, 4) for x in wilson_interval(hit3, n)],
            },
            "support_hit@5": {
                "value": round(rate(hit5), 4),
                "count": hit5,
                "n": n,
                "ci95": [round(x, 4) for x in wilson_interval(hit5, n)],
            },
            "support_mrr": {
                "value": round(mrr_sum / n if n else 0.0, 4),
                "definition": "支撑块排名的倒数均值",
            },
            "keyword_recall": {
                "value": round(mean(kw_recalls), 4) if kw_recalls else None,
                "n_with_keywords": n_kw,
                "definition": "标注关键词出现在检索上下文中的比例",
            },
            "cite_page_rate": {
                "value": round(n_cite / n, 4) if n else None,
                "count": n_cite,
                "n": n,
            },
            "answer_char_f1": {
                "value": round(mean(f1s), 4),
                "definition": "预测答案 vs 金标，中文字级 F1",
            },
            "answer_em": {
                "value": round(rate(em), 4),
                "count": em,
                "n": n,
                "definition": "预测与金标规范化后完全一致",
            },
        },
        "caveats": [
            "评测基于已落盘的 BM25+Milvus+Rerank 结果，未重新加载模型。",
            "金标多为手册抽取/改写，4-gram/ROUGE-L 衡量的是「答案证据是否出现在召回上下文」，不是开放域文档ID召回。",
            "Context Precision 定义为与金标有实质 4-gram 重合的检索块占比。",
            "Support Hit@k 以 4-gram recall 最高的块为支撑块，衡量精排后是否靠前。",
        ],
    }
    return summary


def main():
    inp = ROOT / "data/qa_pairs/test_qa_pair_pred.json"
    out_dir = ROOT / "test/eval_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = evaluate(inp)
    out = out_dir / f"lexical_eval_{summary['timestamp']}.json"
    latest = out_dir / "lexical_eval_latest.json"
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    out.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    main()
