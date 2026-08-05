# post_training/ — implementation checklist

Tracks what of `post-training/README.md`'s plan (the playbook, one directory
up) is actually built here. Read that doc for the "why"; this is just the
status board, checked against its own section numbers. No real labeled data
exists yet — `data/eval_set.json` is synthetic/placeholder throughout.

## Done

- [x] **Eval-example schema** (playbook §5) — `schemas/eval_example.py`:
  `example_id`, `source_video_id`, `split_group`, `window`,
  `queries[text, language, script, origin]`,
  `labels[relevant, event_start_s, event_end_s, observed_actions, confidence, reason]`.
- [x] **Manifest cross-field validation** (playbook §5 rules) —
  `data/validate_manifest.py`: `relevant=false` requires `reason` (error),
  every query needs non-blank `language`/`script` (error), event window
  outside the labeled window is a warning (playbook §10 edge case), not an
  error.
- [x] **Split-leakage check** (playbook §5, §11 "source-video-disjoint split
  proof") — `data/check_split_leakage.py`: fails loudly if one
  `source_video_id` spans more than one `split_group`.
- [x] **Model registry manifest** (playbook §9 item 1) —
  `schemas/model_manifest.py`: `base_model`, `revision`, `adapter_path`,
  `sha256` (validated hex), `vector_dim`, `tokenizer_revision`,
  `training_data_manifest_ref`, `eval_report_ref`, `licence`, `created_at`.
- [x] **Reranker safety boundary** (playbook §9 item 5) —
  `serve/reranker_guard.py`: bounds candidate count, frame count, byte size,
  timeout, and concurrency; fails open to the untouched input ranking on
  timeout/exception/unavailability; logs which path was taken. **Standalone**
  — not yet wired into `query_retrieval/api.py`.
- [x] **Baseline retrieval evaluation harness** (playbook §3 step 1, §6) —
  `evaluate/run_baseline.py` + `evaluate/metrics.py`: Recall@1/5/10,
  MRR@10, nDCG@10, temporal IoU, false-positive rate on labeled negatives,
  and per-slice reporting (language, domain, day/night, audio availability).
- [x] **Versioned eval/serving config** (playbook §7.1 "keep values versioned
  in configuration") — `configs/eval_defaults.yaml`: documents the actual
  `RRF_K`/`DEFAULT_TOP_K`/modality-weight behavior found in `query_retrieval/`
  (flagging which values are real vs newly introduced), plus reranker-guard
  bounds.
- [x] **Regression tests** (playbook §9 item 8, partial) — `tests/` (46
  tests, all against clearly-marked fake data): schema validation, split
  leakage, model-manifest `sha256`, reranker fallback paths.
- [x] **Dummy data for dev iteration** — `data/eval_set.json`, 4 synthetic
  examples (3 positive, 1 labeled negative) with placeholder video IDs.

## Pending (infra exists, needs real inputs or more code)

- [ ] **Real labeled eval set** — everything above runs on 4 fake examples;
  no metric is trustworthy until real hand-labeled footage replaces them
  (playbook §4, §5).
- [ ] **Frozen baseline report** (playbook §6) — `run_baseline.py` writes
  `reports/baseline_<timestamp>.json`, but it has never run against real
  data or a live Qdrant; nothing is "frozen" yet.
- [ ] **Held-out, source-video-disjoint test set** across language/domain
  /camera/event (playbook §6) — schema + leakage checker support it; no real
  split has been built.
- [ ] **Full canonical training-data contract** (playbook §5) —
  `eval_example.py` covers the query-retrieval-eval subset only; the
  playbook's `media{video_uri, audio_uri, sha256, licence_id,
  country_context, domain}`, `negatives[]`, and `annotation{schema_version,
  reviewers, adjudicated}` blocks don't exist here yet.
- [ ] **Per-modality Recall@K before RRF fusion** (playbook §6 table) —
  `metrics.py` scores only the fused/merged result, not visual/audio/speech
  /caption candidate pools individually.
- [ ] **Absolute start/end temporal error**, not just IoU (playbook §6
  table).
- [ ] **ASR WER/CER by language/noise condition** (playbook §6 table) — no
  ASR eval exists.
- [ ] **Audio-only mAP/Recall@K**, evaluated separately from speech queries
  (playbook §6 table).
- [ ] **Latency / GPU-memory / failure-rate operational metrics** (playbook
  §6 table) — `run_baseline.py` reports only total wall-clock time.
- [ ] **Slicing by script, Indian-vs-non-Indian source, resolution, event
  class/negative class** (playbook §6) — only language/domain/day_night/
  has_audio slices are implemented today.
- [ ] **Wiring `reranker_guard.py` into `query_retrieval/api.py`** — ready,
  not adopted by the live pipeline (`post-training` root README explicitly
  said do not modify existing pipeline files yet).
- [ ] **Versioned Qdrant collections + atomic cutover tooling** (playbook §9
  items 2–3).
- [ ] **Learned-fusion feature-schema versioning** (playbook §9 item 4) — no
  learned fusion ranker exists yet to version.
- [ ] **Data lineage / consent / licence / deletion ledger** (playbook §9
  item 6, §5 bullet 5) — no fields or tooling for this yet.
- [ ] **Structured observability** — model version, candidate counts, stage
  timings, per-language metrics (playbook §9 item 7) — beyond
  `reranker_guard`'s path logging and `run_baseline`'s per-query diagnostics.
- [ ] **`mining/`, `train/`, `export/` subpackages** (playbook §9's proposed
  tree) — don't exist yet; required before any step in §7 can start.

## Out of scope (for now)

- **Every training job in playbook §7** — learned fusion ranker, text-
  embedding fine-tune, visual/audio adapters, ASR fine-tune, multimodal
  reranker, VLM fine-tune. Playbook §3 explicitly orders all of these after
  a frozen baseline report exists; none has run.
- **Colab notebooks and `requirements-colab.txt`** (playbook §8) — the
  playbook itself calls these "future engineering work."
- **Dataset sourcing/licensing** (playbook §4) — a legal/process task, not
  code; deferred while there is no real labeled data.
- **PR acceptance-gate checklist** (playbook §11) — inapplicable until a
  trained model exists to gate.
- **Remaining edge cases from playbook §10** beyond the two enforced in
  `validate_manifest.py` (event-outside-window warning, `relevant=false`
  reason) — e.g. multi-event windows, an explicit silent-audio state,
  duplicate/perceptual-hash dedup, caption-hallucination provenance, a
  dataset-withdrawal ledger.
