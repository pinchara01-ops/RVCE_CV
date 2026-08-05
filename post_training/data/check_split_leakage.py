"""Split-leakage check for eval-set manifests.

post-training/README.md section 5 ("Canonical training data contract"):
"A query, positive region, and all its overlapping windows stay in exactly
one split. Split by split_group (camera/site/source video), not randomly by
row." Section 11 ("Acceptance gates") requires "source-video-disjoint split
proof" before a model-change PR is accepted.

This script verifies that property directly: no source_video_id may appear
under more than one split_group value across the manifest. If any video's
windows are scattered across splits (e.g. some examples in "dev", others in
"test"), that is leakage — a model could be evaluated on footage it has
implicitly already seen — and this script fails loudly with the offending
video IDs.

Usage:
    python -m post_training.data.check_split_leakage
    python -m post_training.data.check_split_leakage --manifest path/to.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from post_training.schemas.eval_example import EvalSet

DATA_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = DATA_DIR / "eval_set.json"


def find_leakage(eval_set: EvalSet) -> dict[str, set[str]]:
    """Return {source_video_id: {split_group, ...}} for every video_id that
    appears under more than one split_group. Empty dict means no leakage."""
    video_splits: dict[str, set[str]] = defaultdict(set)
    for example in eval_set.examples:
        video_splits[example.source_video_id].add(example.split_group)
    return {video_id: splits for video_id, splits in video_splits.items() if len(splits) > 1}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    raw = json.loads(args.manifest.read_text())
    eval_set = EvalSet.model_validate(raw)

    print(f"Checking split leakage across {len(eval_set.examples)} examples from {args.manifest}")
    offenders = find_leakage(eval_set)

    if not offenders:
        print(f"PASS: no source_video_id spans more than one split_group "
              f"({len({e.source_video_id for e in eval_set.examples})} distinct videos checked).")
        return 0

    print(f"\nFAIL: {len(offenders)} video(s) leak across splits:\n")
    for video_id, splits in sorted(offenders.items()):
        print(f"  {video_id}: appears in splits {sorted(splits)}")
    print(
        "\nFix: move every example for each offending source_video_id into a "
        "single split_group before training/evaluating."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
