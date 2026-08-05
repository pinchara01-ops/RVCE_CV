"""Cross-field validation for eval-set manifests, on top of the structural
schema in post_training/schemas/eval_example.py.

Pydantic already enforces shape/types/ranges (e.g. end_s > start_s). This
script enforces the business rules from post-training/README.md section 5
("Canonical training data contract") that span more than one field:

- event_start_s/event_end_s should fall inside the example's window
  [window.start_s, window.end_s]. README section 10 ("Edge-case checklist")
  says events may legitimately start before or end after the window, so an
  out-of-window event is a WARNING, not an error.
- `relevant: false` examples must carry an explicit `labels.reason` (temporal
  near miss, similar object, language mismatch, silent audio, etc.) — README
  section 5, "explicit reason" bullet. ERROR if missing/blank.
- Every query must have a non-blank `language` and `script`. ERROR if either
  is blank.

Usage:
    python -m post_training.data.validate_manifest
    python -m post_training.data.validate_manifest --manifest path/to.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from post_training.schemas.eval_example import EvalExample, EvalSet

DATA_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = DATA_DIR / "eval_set.json"

Severity = Literal["error", "warning"]


@dataclass
class Issue:
    severity: Severity
    message: str


def validate_example(example: EvalExample) -> list[Issue]:
    issues: list[Issue] = []

    if (
        example.labels.event_start_s < example.window.start_s
        or example.labels.event_end_s > example.window.end_s
    ):
        issues.append(
            Issue(
                "warning",
                f"event [{example.labels.event_start_s}, {example.labels.event_end_s}] "
                f"extends outside window [{example.window.start_s}, {example.window.end_s}]",
            )
        )

    if not example.labels.relevant and not (example.labels.reason or "").strip():
        issues.append(
            Issue(
                "error",
                "relevant=false but labels.reason is missing/blank "
                "(README: negatives need an explicit reason)",
            )
        )

    for i, query in enumerate(example.queries):
        if not query.language.strip():
            issues.append(Issue("error", f"queries[{i}] ({query.text!r}) has blank language"))
        if not query.script.strip():
            issues.append(Issue("error", f"queries[{i}] ({query.text!r}) has blank script"))

    return issues


def validate_eval_set(eval_set: EvalSet) -> dict[str, list[Issue]]:
    return {example.example_id: validate_example(example) for example in eval_set.examples}


def print_report(report: dict[str, list[Issue]]) -> bool:
    """Print a per-example pass/fail report. Returns True iff every example passed
    (a WARNING alone still counts as a pass; an ERROR does not)."""
    all_passed = True
    for example_id, issues in report.items():
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        if errors:
            all_passed = False
            print(f"FAIL {example_id}")
        elif warnings:
            print(f"PASS {example_id} (with warnings)")
        else:
            print(f"PASS {example_id}")
        for issue in errors:
            print(f"       ERROR   {issue.message}")
        for issue in warnings:
            print(f"       WARNING {issue.message}")
    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    raw = json.loads(args.manifest.read_text())
    eval_set = EvalSet.model_validate(raw)

    print(f"Validating {len(eval_set.examples)} examples from {args.manifest}\n")
    report = validate_eval_set(eval_set)
    all_passed = print_report(report)

    num_errors = sum(1 for issues in report.values() for i in issues if i.severity == "error")
    num_warnings = sum(1 for issues in report.values() for i in issues if i.severity == "warning")
    print(f"\n{len(eval_set.examples)} examples, {num_errors} errors, {num_warnings} warnings")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
