"""Baseline evaluation harness for post_training/data/eval_set.json.

Runs every labeled query through the real, unmodified retrieval pipeline
(query_retrieval.api:app, the same FastAPI app served in production) via
TestClient — no network hop, no server process to manage, mirrors the
pattern already used by demo_queries.py at the repo root.

All metric computation lives in post_training/evaluate/metrics.py; this
script is just the harness that calls /search, builds one scored row per
query, and aggregates/prints/writes the report.

Usage:
    python -m post_training.evaluate.run_baseline
    python -m post_training.evaluate.run_baseline --eval-set path/to/other.json

Requires Qdrant reachable at QDRANT_URL (see query_retrieval/config.py) and
a seeded collection containing the video_ids referenced in the eval set.
Encoders load lazily on first search and are cached in-process afterward.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient

from post_training.evaluate.metrics import (
    aggregate_by_slice,
    false_positive_rate,
    first_relevant_rank,
    graded_relevance_at_ranks,
    score_query,
)
from post_training.schemas.eval_example import EvalExample, EvalQuery, EvalSet
from query_retrieval.api import app

POST_TRAINING_DIR = Path(__file__).resolve().parent.parent
DEFAULT_EVAL_SET = POST_TRAINING_DIR / "data" / "eval_set.json"
REPORTS_DIR = POST_TRAINING_DIR / "reports"
CONFIG_PATH = POST_TRAINING_DIR / "configs" / "eval_defaults.yaml"


def _load_eval_config() -> dict[str, Any]:
    raw = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    return raw.get("evaluation", {})


_CFG = _load_eval_config()
RECALL_KS: tuple[int, ...] = tuple(_CFG.get("recall_at_k", [1, 5, 10]))
MRR_K: int = int(_CFG.get("mrr_at_k", 10))
NDCG_K: int = int(_CFG.get("ndcg_at_k", 10))
IOU_HIT_THRESHOLD: float = float(_CFG.get("iou_hit_threshold", 0.0))
TOP_K = 10

METRIC_KEYS = [f"recall@{k}" for k in RECALL_KS] + [f"mrr@{MRR_K}", f"ndcg@{NDCG_K}", "temporal_iou"]
SLICE_KEYS = ["language", "domain", "day_night", "has_audio"]


def evaluate_query(client: TestClient, example: EvalExample, query: EvalQuery) -> dict[str, Any]:
    base_row = {
        "query": query.text,
        "language": query.language,
        "script": query.script,
        "origin": query.origin,
        "domain": example.metadata.domain,
        "day_night": example.metadata.day_night,
        "has_audio": example.metadata.has_audio,
        "relevant": example.labels.relevant,
    }

    resp = client.post("/search", json={"query": query.text, "top_k": TOP_K})
    if resp.status_code != 200:
        return {**base_row, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}

    results = resp.json()["results"]
    relevance = graded_relevance_at_ranks(
        results,
        video_id=example.source_video_id,
        event_start_s=example.labels.event_start_s,
        event_end_s=example.labels.event_end_s,
    )
    first_hit_rank = first_relevant_rank(relevance[:TOP_K], threshold=IOU_HIT_THRESHOLD)
    is_hit = first_hit_rank is not None

    row: dict[str, Any] = {
        **base_row,
        "first_hit_rank": first_hit_rank,
        "is_hit": is_hit,
        "num_results": len(results),
    }
    # Recall/MRR/nDCG only mean "did retrieval find the true event" — that
    # question is undefined for a labeled negative, where the retrieval
    # target is deliberately not something the system should surface. Those
    # examples still feed false_positive_rate() via is_hit above.
    row["metrics"] = (
        score_query(
            results,
            video_id=example.source_video_id,
            event_start_s=example.labels.event_start_s,
            event_end_s=example.labels.event_end_s,
            recall_ks=RECALL_KS,
            mrr_k=MRR_K,
            ndcg_k=NDCG_K,
            iou_hit_threshold=IOU_HIT_THRESHOLD,
        )
        if example.labels.relevant
        else None
    )
    return row


def evaluate_example(client: TestClient, example: EvalExample) -> dict[str, Any]:
    query_rows = [evaluate_query(client, example, q) for q in example.queries]
    return {
        "example_id": example.example_id,
        "source_video_id": example.source_video_id,
        "split_group": example.split_group,
        "queries": query_rows,
    }


def _flatten_scored_rows(example_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One flat dict per scored (non-error) query: metrics + slice metadata,
    ready for aggregate_by_slice()/false_positive_rate()."""
    flat: list[dict[str, Any]] = []
    for ex in example_reports:
        for q in ex["queries"]:
            if "error" in q:
                continue
            row = {k: q[k] for k in SLICE_KEYS}
            row["relevant"] = q["relevant"]
            row["is_hit"] = q["is_hit"]
            if q["metrics"] is not None:
                row.update(q["metrics"])
            flat.append(row)
    return flat


def aggregate(example_reports: list[dict[str, Any]]) -> dict[str, Any]:
    num_queries = sum(len(ex["queries"]) for ex in example_reports)
    num_errors = sum(1 for ex in example_reports for q in ex["queries"] if "error" in q)
    flat_rows = _flatten_scored_rows(example_reports)
    positive_rows = [r for r in flat_rows if r["relevant"]]

    slices = aggregate_by_slice(positive_rows, slice_keys=SLICE_KEYS, metric_keys=METRIC_KEYS)
    fpr = false_positive_rate(flat_rows)

    return {
        "num_examples": len(example_reports),
        "num_queries": num_queries,
        "num_errors": num_errors,
        "num_scored": num_queries - num_errors,
        "num_positive_scored": len(positive_rows),
        "num_negative_scored": len(flat_rows) - len(positive_rows),
        "false_positive_rate": fpr,
        **slices["overall"],
        "by_slice": {k: v for k, v in slices.items() if k != "overall"},
    }


def print_report(example_reports: list[dict[str, Any]], agg: dict[str, Any]) -> None:
    print(f"\n{'=' * 70}\nPER-EXAMPLE RESULTS\n{'=' * 70}")
    for ex in example_reports:
        print(f"\n[{ex['example_id']}] video={ex['source_video_id']} split={ex['split_group']}")
        for q in ex["queries"]:
            if "error" in q:
                print(f"  ✗ {q['query']!r}: ERROR — {q['error']}")
                continue
            rank = q["first_hit_rank"] if q["first_hit_rank"] is not None else "-"
            if q["metrics"] is not None:
                m = q["metrics"]
                print(
                    f"  · {q['query']!r} [relevant]: hit_rank={rank} "
                    f"R@1={m['recall@1']:.0f} R@5={m['recall@5']:.0f} R@10={m['recall@10']:.0f} "
                    f"MRR@{MRR_K}={m[f'mrr@{MRR_K}']:.3f} nDCG@{NDCG_K}={m[f'ndcg@{NDCG_K}']:.3f} "
                    f"IoU={m['temporal_iou']:.3f}"
                )
            else:
                print(
                    f"  · {q['query']!r} [labeled NEGATIVE]: "
                    f"{'FALSE POSITIVE (hit at rank ' + str(rank) + ')' if q['is_hit'] else 'correctly not retrieved'}"
                )

    errors_suffix = f", {agg['num_errors']} errors" if agg["num_errors"] else ""
    print(
        f"\n{'=' * 70}\nAGGREGATE ({agg['num_scored']}/{agg['num_queries']} queries scored"
        f"{errors_suffix}; {agg['num_positive_scored']} positive, "
        f"{agg['num_negative_scored']} negative)\n{'=' * 70}"
    )
    for k in RECALL_KS:
        val = agg.get(f"recall@{k}")
        print(f"  Recall@{k}:      {val:.3f}" if val is not None else f"  Recall@{k}:      n/a")
    mrr = agg.get(f"mrr@{MRR_K}")
    print(f"  MRR@{MRR_K}:       {mrr:.3f}" if mrr is not None else f"  MRR@{MRR_K}:       n/a")
    ndcg = agg.get(f"ndcg@{NDCG_K}")
    print(f"  nDCG@{NDCG_K}:      {ndcg:.3f}" if ndcg is not None else f"  nDCG@{NDCG_K}:      n/a")
    iou = agg.get("temporal_iou")
    print(f"  Temporal IoU:  {iou:.3f}" if iou is not None else "  Temporal IoU:  n/a")
    fpr = agg.get("false_positive_rate")
    print(f"  False-positive rate: {fpr:.3f}" if fpr is not None else "  False-positive rate: n/a (no labeled negatives)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    args = parser.parse_args()

    raw = json.loads(args.eval_set.read_text())
    eval_set = EvalSet.model_validate(raw)
    if not eval_set.examples:
        print(f"No examples in {args.eval_set}; nothing to evaluate.")
        return 0

    print(f"Loaded {len(eval_set.examples)} examples from {args.eval_set}")
    print("Starting retrieval pipeline (encoder warmup on first query)...")

    started = time.perf_counter()
    with TestClient(app) as client:
        example_reports = [evaluate_example(client, ex) for ex in eval_set.examples]
    elapsed = time.perf_counter() - started

    agg = aggregate(example_reports)
    print_report(example_reports, agg)
    print(f"\nTotal time: {elapsed:.1f}s")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORTS_DIR / f"baseline_{timestamp}.json"
    report_path.write_text(
        json.dumps(
            {
                "eval_set": str(args.eval_set),
                "generated_at": timestamp,
                "elapsed_seconds": round(elapsed, 3),
                "aggregate": agg,
                "examples": example_reports,
            },
            indent=2,
        )
    )
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
