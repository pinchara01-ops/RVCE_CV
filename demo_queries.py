"""Standalone manual demo script - runs a curated set of realistic queries
against the seeded Qdrant collection through the real /search pipeline and
prints results in a readable format.

Usage:
    python -m query_retrieval.seed_dummy_data   # if not already seeded
    python demo_queries.py

Uses the real encoder models (X-CLIP/CLAP/BGE-M3) - first run may take a
few minutes to load; set HF_HUB_OFFLINE=1 once they're cached locally to
cut that to ~10s. No query router (see README.md) - every query encodes
and searches all 4 modalities unconditionally; RRF fusion suppresses
irrelevant ones through rank.
"""
import time

from fastapi.testclient import TestClient

from query_retrieval.api import app

QUERIES = [
    "red car",
    "person wearing glasses",
    "dog barking",
    "glass breaking",
    "someone says hello",
    "person mentions their name",
    "a celebration",
    "an outdoor scene",
    "man shouting while driving",
    "a birthday party",
    "loud crash sound",
    "quiet room",
    "🐶 loud bang!!",
    "asdkjfh qwoeiru",
    "",
]


def _print_result(query: str, body: dict, elapsed: float) -> None:
    print(f"\n{'=' * 70}")
    print(f"QUERY: {query!r}   ({elapsed * 1000:.0f}ms)")
    if not body["results"]:
        print("  (no results)")
        return
    for i, r in enumerate(body["results"][:5], 1):
        modalities = ",".join(r["matched_modalities"])
        print(
            f"  {i}. [{r['video_id']}] {r['start']:.1f}-{r['end']:.1f}s "
            f"score={r['score']:.4f} modalities=[{modalities}]"
        )
        if r["caption"]:
            print(f"     caption: {r['caption']}")
        if r["transcript"]:
            print(f"     transcript: {r['transcript']}")


def main() -> None:
    print("Starting server (encoder warmup - may take a while on first run)...")
    with TestClient(app) as client:
        print("Ready.\n")
        for query in QUERIES:
            t0 = time.time()
            resp = client.post("/search", json={"query": query, "top_k": 5})
            elapsed = time.time() - t0
            if resp.status_code != 200:
                print(f"\nQUERY: {query!r} -> ERROR {resp.status_code}: {resp.text}")
                continue
            _print_result(query, resp.json(), elapsed)
    print(f"\n{'=' * 70}\nDone: {len(QUERIES)} queries.")


if __name__ == "__main__":
    main()
