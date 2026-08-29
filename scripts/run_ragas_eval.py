#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAGAS 端到端评测：基于 data/qa_pairs/test_qa_pair_pred.json

用法（conda activate tesla）:
  python scripts/run_ragas_eval.py --limit 5                 # 冒烟
  python scripts/run_ragas_eval.py --limit 100 --metrics core
  python scripts/run_ragas_eval.py                           # 全量（较慢）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def split_numbered_context(context: str) -> list[str]:
    """把 '1.xxx\\n2.yyy' 拆成 list[str]。"""
    text = (context or "").strip()
    if not text:
        return []
    parts = re.split(r"(?m)(?=^\d+\.)", text)
    chunks = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        p = re.sub(r"^\d+\.", "", p, count=1).strip()
        if p:
            chunks.append(p)
    if not chunks and text:
        chunks = [text]
    return chunks


def truncate_contexts(rows: list[dict], max_chars: int = 1200) -> list[dict]:
    out = []
    for r in rows:
        nr = dict(r)
        nr["contexts"] = [
            (c[:max_chars] + ("…" if len(c) > max_chars else "")) for c in r["contexts"]
        ]
        out.append(nr)
    return out


def load_pred_samples(path: Path, limit: int | None, seed: int) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for item in data:
        gold = (item.get("answer") or "").strip()
        pred = ((item.get("pred") or {}).get("answer") or "").strip()
        ctx = split_numbered_context(item.get("context") or "")
        q = (item.get("question") or "").strip()
        if not q or not pred or not ctx:
            continue
        rows.append(
            {
                "unique_id": item.get("unique_id"),
                "question": q,
                "answer": pred,
                "ground_truth": gold,
                "contexts": ctx,
                "keywords": item.get("keywords") or [],
                "cite_pages": (item.get("pred") or {}).get("cite_pages") or [],
            }
        )
    if limit is not None and limit > 0 and limit < len(rows):
        import random

        rng = random.Random(seed)
        rows = rng.sample(rows, limit)
    return rows


def keyword_hit_rate(rows: list[dict]) -> dict:
    per = []
    for r in rows:
        kws = [k for k in r["keywords"] if k]
        if not kws:
            continue
        blob = (r["answer"] + "\n" + "\n".join(r["contexts"])).lower()
        hits = sum(1 for k in kws if k.lower() in blob)
        per.append(hits / len(kws))
    if not per:
        return {"keyword_coverage_mean": None, "n_with_keywords": 0}
    return {
        "keyword_coverage_mean": round(sum(per) / len(per), 4),
        "n_with_keywords": len(per),
    }


def fullset_aux_stats(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    n = len(data)
    n_cite = 0
    n_empty_pred = 0
    kw_rates = []
    ctx_counts = []
    for item in data:
        pred = (item.get("pred") or {}).get("answer") or ""
        if not str(pred).strip():
            n_empty_pred += 1
        pages = (item.get("pred") or {}).get("cite_pages") or []
        if pages:
            n_cite += 1
        ctx = split_numbered_context(item.get("context") or "")
        ctx_counts.append(len(ctx))
        kws = item.get("keywords") or []
        if kws:
            blob = (pred + "\n" + "\n".join(ctx)).lower()
            hits = sum(1 for k in kws if k and k.lower() in blob)
            kw_rates.append(hits / len(kws))
    return {
        "n_total": n,
        "cite_page_rate": round(n_cite / n, 4) if n else None,
        "empty_pred_rate": round(n_empty_pred / n, 4) if n else None,
        "avg_context_chunks": round(sum(ctx_counts) / len(ctx_counts), 3) if ctx_counts else None,
        "keyword_coverage_mean": round(sum(kw_rates) / len(kw_rates), 4) if kw_rates else None,
        "n_with_keywords": len(kw_rates),
    }


def build_ragas_dataset(rows: list[dict]):
    from datasets import Dataset

    return Dataset.from_dict(
        {
            "question": [r["question"] for r in rows],
            "answer": [r["answer"] for r in rows],
            "contexts": [r["contexts"] for r in rows],
            "ground_truth": [r["ground_truth"] for r in rows],
        }
    )


def run_ragas(dataset, batch_size: int | None, metrics_mode: str = "core"):
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import evaluate
    from ragas.metrics import (
        answer_correctness,
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )
    from ragas.run_config import RunConfig

    api_key = os.environ["BAILIAN_API_KEY"]
    base_url = os.environ.get(
        "BAILIAN_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    model = os.environ.get("BAILIAN_MODEL_NAME", "qwen-plus")

    # 百炼并发过高易 Timeout；answer_relevancy 还可能要 n>1，thinking 必须关
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        timeout=180,
        max_retries=3,
        extra_body={"enable_thinking": False},
    )
    embeddings = OpenAIEmbeddings(
        model="text-embedding-v3",
        api_key=api_key,
        base_url=base_url,
        check_embedding_ctx_length=False,
    )

    if metrics_mode == "full":
        metrics = [
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
            answer_correctness,
        ]
    else:
        metrics = [
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
        ]

    return evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        show_progress=True,
        batch_size=batch_size,
        raise_exceptions=False,
        run_config=RunConfig(max_workers=2, timeout=180),
        column_map={
            "question": "question",
            "answer": "answer",
            "contexts": "contexts",
            "ground_truth": "ground_truth",
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data/qa_pairs/test_qa_pair_pred.json",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "test/ragas_results",
    )
    parser.add_argument("--limit", type=int, default=None, help="抽样条数，默认全量")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument(
        "--metrics",
        choices=["core", "full"],
        default="core",
        help="core=四项核心；full=加 answer_correctness",
    )
    parser.add_argument(
        "--max-ctx-chars",
        type=int,
        default=1200,
        help="每段 retrieved context 最大字符，降时延",
    )
    args = parser.parse_args()

    if not os.environ.get("BAILIAN_API_KEY"):
        raise SystemExit("缺少 BAILIAN_API_KEY，请检查 .env")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    rows = load_pred_samples(args.input, args.limit, args.seed)
    rows = truncate_contexts(rows, args.max_ctx_chars)
    print(f"[RAGAS] loaded {len(rows)} samples from {args.input}")
    print(
        f"[RAGAS] judge={os.environ.get('BAILIAN_MODEL_NAME')} "
        f"embed=text-embedding-v3 metrics={args.metrics}"
    )

    sample_aux = keyword_hit_rate(rows)
    full_aux = fullset_aux_stats(args.input)
    dataset = build_ragas_dataset(rows)

    t0 = time.time()
    result = run_ragas(dataset, args.batch_size, args.metrics)
    elapsed = time.time() - t0

    try:
        df = result.to_pandas()
    except Exception:
        df = None

    summary = {
        "timestamp": stamp,
        "n_samples": len(rows),
        "limit": args.limit,
        "seed": args.seed,
        "metrics_mode": args.metrics,
        "max_ctx_chars": args.max_ctx_chars,
        "judge_model": os.environ.get("BAILIAN_MODEL_NAME"),
        "embedding_model": "text-embedding-v3",
        "elapsed_sec": round(elapsed, 1),
        "metrics": {},
        "sample_aux": sample_aux,
        "fullset_aux": full_aux,
        "input": str(args.input),
    }

    metric_names = [
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
        "answer_correctness",
    ]
    for name in metric_names:
        val = None
        try:
            val = float(result[name])
        except Exception:
            if df is not None and name in df.columns:
                val = float(df[name].mean(skipna=True))
        if val is None or val != val:
            if args.metrics == "core" and name == "answer_correctness":
                continue
            summary["metrics"][name] = None
        else:
            summary["metrics"][name] = round(val, 4)

    scores_path = args.out_dir / f"ragas_scores_{stamp}.json"
    detail_path = args.out_dir / f"ragas_detail_{stamp}.csv"
    summary_path = args.out_dir / f"ragas_summary_{stamp}.json"
    latest_summary = args.out_dir / "ragas_summary_latest.json"

    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if df is not None:
        df.insert(0, "unique_id", [r["unique_id"] for r in rows])
        df.insert(1, "question", [r["question"] for r in rows])
        df.to_csv(detail_path, index=False)
        scores_path.write_text(
            df.to_json(orient="records", force_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[RAGAS] summary -> {summary_path}")
    if df is not None:
        print(f"[RAGAS] detail  -> {detail_path}")


if __name__ == "__main__":
    main()
