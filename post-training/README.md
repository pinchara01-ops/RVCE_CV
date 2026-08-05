# Post-training playbook

This is the implementation hand-off for adapting the video-search workbench to
surveillance footage, with an India-first language and visual-domain strategy.
It is a plan, not a claim that the current repository has trained models or
training scripts. Build and validate one stage at a time.

## 1. Decisions and scope

### Goal

Improve retrieval of time-bounded events in video from natural-language
queries, including Indian English, Hindi, and other regional Indian languages.
The system should return the correct source video and the smallest supported
time range, with observable evidence.

### Non-goals

- Do not train a system to infer criminal intent, guilt, identity, caste,
  religion, or protected attributes.
- Do not use unconsented CCTV footage, bypass source restrictions, or upload
  sensitive footage to a public notebook service.
- Do not replace the whole pipeline with one large model before a measured
  baseline shows that it is necessary.
- Do not mix vectors created by different versions of an embedding model in
  the same retrieval field/collection.

### Current pipeline inventory

| Component | Current model family / job | Post-training priority | Why |
|---|---|---:|---|
| Visual retrieval | Video-text dual encoder | Medium | Improves visual surveillance/domain recall. |
| Audio retrieval | Audio-text dual encoder | Medium | Useful for sirens, crashes, shouting, alarms, glass breakage. |
| Speech/caption retrieval | Multilingual text embedding model | High | Lowest-cost route to better query language and terminology support. |
| Speech-to-text | Whisper-family ASR runtime | Medium | Essential when spoken Indian languages are part of search. |
| Captioning / visual verification | Vision-language model (VLM) | Low initially | Expensive labels and compute; useful after retrieval is measured. |
| RRF fusion | Deterministic rank fusion | No model training | It has no weights to fine-tune. |
| Learned fusion | Small learning-to-rank model over retrieval features | High | Cheap, fast, and a strong first improvement. |
| Multimodal reranker | Qwen3-VL-Reranker-compatible cross encoder | High after baseline | Reorders a small candidate set using query + real candidate content. |

The existing index uses overlapping 10-second windows with a 5-second stride.
This matters for training: annotations must be temporal, and train/validation/
test splits must be made by **source video/camera**, never by individual
overlapping windows.

## 2. Target architecture after post-training

```text
video -> overlapping windows -> visual/audio/transcript/caption embeddings -> vector store

text query -> one query vector per retrieval space -> top-L retrieval per space
           -> RRF rank fusion -> merge neighbouring same-video windows
           -> top-K multimodal cross-encoder reranker
           -> optional VLM evidence + timestamp refinement for final M
```

Definitions:

- **L**: per-retrieval-space candidate depth. This is a recall setting.
- **K**: fused, merged candidate regions sent to the cross-encoder. This is a
  precision/latency setting.
- **M**: final candidates sent to a VLM verifier. This is an evidence/cost
  setting.

RRF selects candidates; it does not give a cross-encoder a semantic score to
copy. A cross-encoder should score `query + sampled candidate frames +
transcript/caption` independently. The RRF score may be kept for diagnostics
and only used as a stable tie-breaker, unless a later evaluation proves that a
calibrated score combination helps.

## 3. What to train, in the right order

Do **not** train every model simultaneously. Use this order:

1. Build the evaluation set and baseline report.
2. Train a small learned fusion ranker on existing retrieval outputs.
3. Fine-tune the text embedding model for surveillance terminology and Indian
   languages.
4. Train the multimodal cross-encoder reranker with hard negatives mined from
   the real retriever.
5. Address the weakest measured modality: visual retrieval, ASR, or audio.
6. Fine-tune a VLM only if retrieval plus reranking still cannot answer the
   required queries accurately enough.

This order is deliberate: steps 2--4 offer the highest expected quality gain
per labelled example and do not require re-training every foundation model.

## 4. Dataset strategy

### 4.1 India-first mix

Use the following starting policy, then change it only with measured
per-language and per-domain results:

- Aim for about **70% India-context source video**: consented/contracted
  footage, safely staged reenactments, Indian road/traffic data, and footage
  whose licence explicitly permits the intended research use.
- Use at most about **30% external public surveillance/event data** to cover
  rare events and camera conditions that cannot be safely collected locally.
- Apply the percentage at the **source-video/camera level**, not after window
  extraction. Otherwise one long foreign video can leak thousands of windows
  into a supposedly India-first training split.

Indian-context footage should span the intended deployment domains, for
example road/dashcam, retail interiors, entrances, corridors, and public
outdoor cameras. Indian road data is valuable for vehicle, road, lighting,
traffic, and camera-angle adaptation; it is not a substitute for labelled
shoplifting or assault data.

### 4.2 Recommended source categories

| Need | Candidate sources | Correct use | Caution |
|---|---|---|---|
| Surveillance video-language retrieval | [UCA / UCF-Crime Annotation](https://xuange923.github.io/Surveillance-Video-Understanding), [UCF-Crime](https://www.crcv.ucf.edu/research/real-world-anomaly-detection-in-surveillance-videos/), [VIRAT](https://viratdata.org/index.html) | Retrieval/reranking evaluation and event/window supervision | Check each source's access agreement before download or redistribution. |
| Traffic / road-domain adaptation | [India Driving Dataset (IDD)](https://idd.insaan.iiit.ac.in/), [IITH Accident Dataset](https://sites.google.com/site/dineshsinghindian/iith_accident-dataset), [DoTA](https://github.com/MoonBlvd/Detection-of-Traffic-Anomaly) | Indian traffic appearance, crashes, road anomalies | IDD is not a crime-retrieval corpus. Confirm video/annotation access terms. |
| Sound-event retrieval | [FSD50K](https://zenodo.org/records/4060432), [AudioSet](https://research.google.com/audioset/) plus consented CCTV/dashcam audio | Sirens, horns, crash-like sounds, alarms, shouting, ambient negatives | AudioSet points to YouTube content; follow its terms and do not assume redistribution rights. |
| Indian-language ASR | [IndicVoices](https://huggingface.co/datasets/ai4bharat/IndicVoices), [Vistaar](https://github.com/AI4Bharat/vistaar), Common Voice/FLEURS where licensed | Speech recognition and language coverage | Speech corpora are not sound-event corpora and do not by themselves teach crash/siren semantics. |
| Multilingual text retrieval | Human-written surveillance queries and annotations; [IndicMSMARCO / AI4Bharat datasets](https://huggingface.co/ai4bharat/datasets) as supplemental general retrieval language data | Query wording, scripts, transliteration, code switching | General text retrieval data does not replace temporal video relevance labels. |
| India-specific sensitive events | Consented data partnerships or staged reenactments with signed releases | Actual target-domain labels for the demo | Prefer observable-action labels; do not scrape private/public CCTV clips. |

There is no reliable, openly licensed, ready-made Indian CCTV crime corpus that
should be treated as the sole answer for shoplifting, theft, or violence. If a
candidate dataset is found, record its licence, access conditions, source,
allowed use, retention period, and whether it is permitted to leave the
institution before using it.

### 4.3 Language policy

For each underlying event window, create multiple independently reviewed query
forms where relevant:

- English and Indian English.
- Hindi in Devanagari and Romanized Hindi/Hinglish.
- Priority regional languages chosen from the actual demo audience, e.g.
  Kannada, Tamil, Telugu, Malayalam, Marathi, Bengali, Gujarati, Punjabi,
  Urdu, or Assamese.
- Natural code-switched wording, such as English object names within an Indic
  sentence.
- Synonyms and negative/absence queries: `no helmet`, `not carrying a bag`,
  `no vehicle collision`.

Do not generate the whole language set with machine translation and call it
native data. Human review is mandatory for a held-out evaluation set, slang,
local object names, transliteration, and code-switching. Synthetic translation
is acceptable as **training augmentation**, marked as synthetic in metadata.

### 4.4 Event taxonomy

Label observable actions, not legal conclusions. Examples:

```text
observable: person picks up item; person puts item into bag; person exits area
observable: two vehicles collide; vehicle stops abruptly; smoke becomes visible
observable: alarm/siren is audible; person shouts; glass-like impact is audible
avoid:       person commits theft; suspicious person; criminal intent
```

Keep `unknown`, `not visible`, `not audible`, and `ambiguous` as valid labels.
They are essential hard negatives for a system that must not invent evidence.

## 5. Canonical training data contract

Create one source-of-truth manifest before any training. Store media outside
Git; commit only manifests, checksums where allowed, schemas, and scripts.

```json
{
  "example_id": "cam17_000421_q_hi_03",
  "source_video_id": "cam17_000421",
  "split_group": "site-a-camera-17",
  "window": {"start_s": 105.0, "end_s": 120.0},
  "media": {
    "video_uri": "secure://...",
    "audio_uri": "secure://...",
    "sha256": "...",
    "licence_id": "consent-v3",
    "country_context": "IN",
    "domain": "retail"
  },
  "evidence": {
    "transcript": "...",
    "caption": "...",
    "has_audio": true,
    "frame_timestamps_s": [106.0, 109.0, 112.0, 115.0]
  },
  "queries": [
    {
      "text": "एक व्यक्ति बैग में सामान रखता है",
      "language": "hi",
      "script": "Devanagari",
      "origin": "human",
      "intent": "observable_action"
    }
  ],
  "labels": {
    "relevant": true,
    "event_start_s": 110.5,
    "event_end_s": 116.0,
    "observed_actions": ["item placed into bag"],
    "confidence": "reviewed"
  },
  "negatives": ["cam17_000421_080_090", "cam11_000083_015_025"],
  "annotation": {"schema_version": "1", "reviewers": 2, "adjudicated": true}
}
```

Required validation rules:

- A query, positive region, and all its overlapping windows stay in exactly
  one split.
- Split by `split_group` (camera/site/source video), not randomly by row.
- `event_start_s` and `event_end_s` stay inside the referenced source video.
- `relevant=false` negatives must have an explicit reason: temporal near miss,
  similar object, similar activity, language mismatch, silent audio, etc.
- Preserve language/script/origin; never overwrite a human query with a
  translated one.
- Record licence/consent before processing and keep a deletion path for any
  source that must be withdrawn.

## 6. Evaluation before training

Freeze a baseline report before changing a model. The held-out test set must
contain source-video-disjoint examples across language, domain, camera, and
event type.

| Stage | Metrics | Pass condition |
|---|---|---|
| Candidate retrieval | Recall@K per modality and after RRF | The true event region appears in the candidate pool. |
| Ranking | MRR@10, nDCG@10, Recall@1/5/10 | Reranking improves or preserves the baseline on the frozen set. |
| Localisation | Temporal IoU, start/end absolute error | Returned interval overlaps the annotated event. |
| ASR | WER/CER by language and noisy-CCTV slice | Improvement does not hide regressions in a regional language. |
| Audio | mAP / Recall@K for sound labels | Evaluate sound queries separately from speech queries. |
| Safety | False-positive rate for negative/ambiguous queries | No model is released merely because positive recall rises. |
| Operations | Median/p95 latency, GPU memory, failure rate | The stage fits the chosen demo/runtime profile. |

Report every metric by:

- language and script;
- Indian vs non-Indian source context;
- domain (road, retail, corridor, outdoor);
- daylight/night, resolution, and audio availability;
- event class and negative class.

Do not select a checkpoint only on aggregate accuracy. A model can look better
overall while becoming worse for Kannada, low-light cameras, or silent video.

## 7. Training guide by component

### 7.1 RRF: do not train it

RRF is a deterministic formula over ranks. Tune its modality weights only
after baseline analysis, and keep the values versioned in configuration.

If the product needs a learned combination of retrieval evidence, add a
separate **learned fusion ranker**. It is not a replacement for RRF until it
wins on held-out data.

#### Learned fusion ranker

**Input features**

- rank and normalized similarity from every retrieval channel;
- whether the candidate had audio, transcript, caption, OCR, or object data;
- query language, detected query intent, and source-domain metadata;
- temporal region length and count of merged windows;
- missing-data indicators. Missing audio is not a zero-confidence label.

**Labels**: one row per `(query, candidate region)` with relevance 0/1 or a
graded relevance label.

**Model**: begin with logistic regression, then compare LambdaMART/XGBoost.
Keep it small, explainable, and CPU-deployable.

**Steps**

1. Run the frozen retriever over training queries and save the top-L list.
2. Join those candidates with human temporal relevance labels.
3. Split by source video/camera; fit only on training groups.
4. Train a baseline logistic-regression model.
5. Compare it with RRF using MRR/nDCG and calibration plots.
6. Promote only if it improves the held-out test set, not just training data.

**Engineering impact**: no re-index is required. Add a versioned model
artifact, a feature-schema version, inference fallback to RRF, and per-result
diagnostics showing the ranker version and feature availability.

### 7.2 Text embedding retriever

**Purpose**: match the query to transcript and caption text in a shared text
embedding space. This is the best first foundation-model fine-tuning target
for multilingual terminology and code-switching.

**Training records**

```text
(query in language L, positive transcript/caption/window description,
 hard negatives from the current retriever)
```

Use multiple query languages for the same positive region. Include native
script, Romanized script, English, code-switched queries, explicit negation,
and query ambiguity where users are likely to phrase them.

**Objective**: contrastive dense retrieval loss (in-batch negatives plus
mined hard negatives). A pairwise margin or triplet loss is also acceptable,
but do not train from random negatives only; they are too easy.

**Recommended steps**

1. Export transcript/caption windows and human query labels to JSONL.
2. Mine top false positives from the current text/vector retriever.
3. Fine-tune the existing multilingual embedding checkpoint using a small
   adapter/LoRA or the project's supported embedding fine-tune tooling.
4. Evaluate dense retrieval first. Optionally evaluate sparse/late-interaction
   modes separately; do not silently mix them with the current dense field.
5. Replace both the **index encoder** and **query encoder** together.
6. Build a new versioned Qdrant collection and re-embed every affected text
   field before cutover.

The current BGE family exposes dense, lexical, and multi-vector retrieval
modes and documents fine-tuning support in
[FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding). The present
application uses the dense mode only; enabling other modes is future
engineering, not a free accuracy upgrade.

**Colab feasibility**: good. Use a GPU runtime, mixed precision, gradient
accumulation, and small sequence batches. This is usually the first model to
fine-tune in Colab.

### 7.3 Visual video-text embedding retriever

**Purpose**: retrieve visually relevant video windows from text, even when the
event is not spoken or captioned.

**Training records**

```text
(text query or human window description, 4--8 uniformly sampled frames,
 positive time window, hard-negative windows)
```

Use hard negatives that are visually similar but semantically wrong:

- same camera, nearby time, no event;
- same object but different action;
- same action but different object/person count;
- day/night or viewpoint shift;
- post-event and pre-event windows.

**Objective**: contrastive video-text retrieval loss. Freeze most of the
backbone first and train projections/temporal layers or LoRA adapters. Full
fine-tuning is not the first experiment for a small surveillance dataset.

**Steps**

1. Create source-video-disjoint window/query/negative records.
2. Decode the same number of ordered frames per window as production uses.
3. Train adapters with mixed precision, small batch size, gradient
   accumulation, and early stopping on Recall@K.
4. Check qualitative failure cases in low light, occlusion, compression, and
   crowded scenes.
5. Export the updated visual encoder with a model/version manifest.
6. Re-embed every visual vector into a new collection; query and index must
   use the identical checkpoint/revision.

**Colab feasibility**: feasible as adapter training with conservative batches
on a 16 GB+ GPU. Use 24 GB+ where possible. Full retraining is not a Colab
task; use a managed multi-GPU environment only if the data volume justifies it.

### 7.4 Audio-text embedding retriever

**Purpose**: retrieve non-speech audible events and speech-related cues. It is
not an ASR model.

**Training records**

```text
(audio clip, sound description/query, event time range, source context)
```

Examples: `car horn`, `siren`, `glass breaking`, `loud impact`, `people
shouting`, and deliberately hard negatives such as traffic noise without a
collision.

**Datasets**: FSD50K and AudioSet can broaden generic sound coverage; consented
dashcam/CCTV audio supplies target acoustics. Indian-language speech datasets
should be used for ASR, not treated as labels for crash/siren retrieval.

**Objective**: contrastive audio-text retrieval. Start with a frozen text
encoder and adapter/partial tuning of the audio branch; unfreeze more only
after the baseline shows a measurable benefit.

**Steps**

1. Standardize audio rate, mono/stereo policy, duration, loudness, and silence
   representation.
2. Make human-reviewed text prompts for each sound clip in target languages.
3. Include silent/missing-audio windows as explicit non-applicable examples;
   never pretend a zero vector is audio evidence.
4. Fine-tune on contrastive pairs with balanced sound classes and realistic
   background/noise augmentation.
5. Evaluate sound-only queries separately from spoken-word queries.
6. Re-embed audio windows into a new versioned collection.

The [LAION CLAP project](https://github.com/LAION-AI/CLAP) provides training,
fine-tuning, and evaluation references. Its full pretraining setup is far
larger than this project; use it for targeted downstream adaptation only.

**Colab feasibility**: adapter/partial fine-tuning is reasonable. Full
pretraining is out of scope.

### 7.5 Speech recognition / transcription

**Purpose**: turn spoken content into high-quality searchable text. Improving
ASR can improve text retrieval without changing the text retriever.

**Important implementation detail**: the current runtime uses a fast
inference-oriented Whisper implementation. Fine-tune the underlying
Whisper-compatible model in a training framework, then export/convert it for
the production runtime. Do not try to train the inference wrapper directly.

**Data**: IndicVoices and Vistaar are strong starting points for Indian
language coverage. Add a small, consented, accurately transcribed noisy-CCTV
evaluation/training slice; clean read-speech data alone will not reflect a
camera microphone.

**Steps**

1. Choose target languages based on the demo and label language ID per clip.
2. Normalize punctuation, numbers, named entities, and code switching without
destroying the original transcript.
3. Fine-tune with sequence-to-sequence ASR loss, per-language sampling, and
   a language-ID/forced-decoder policy that is tested explicitly.
4. Measure WER/CER by language and by noise condition.
5. Export the accepted checkpoint to the production ASR format.
6. Re-transcribe the library, regenerate transcript embeddings, and reindex
   text fields. Store `asr_model_id` with every window.

The [Vistaar repository](https://github.com/AI4Bharat/vistaar) includes
training/evaluation data and manifests for 12 Indian languages and provides a
concrete IndicWhisper reference. IndicVoices covers broader spontaneous Indian
speech, but its gated access/terms must be accepted before use.

**Colab feasibility**: small/medium adapter fine-tuning is reasonable on a
GPU runtime. Use cloud GPUs for longer runs; checkpoint frequently.

### 7.6 Multimodal cross-encoder reranker

**Purpose**: improve precision after RRF. It is a second-stage model and must
never process the whole video library.

**Training records**

```text
(query, candidate region frames, candidate transcript/caption,
 relevance label, optional temporal-support label)
```

For each positive, mine challenging candidate regions from the actual RRF
output. The most useful negatives are the top retrieved false positives, not
random windows. Include same-video temporal near misses and visually similar
wrong events.

**Objective**

- Start with pointwise binary relevance (`yes` / `no`) loss.
- Add pairwise/listwise ranking once there are several labelled candidates per
  query.
- Keep a held-out calibration set; a probability-like output is not
  automatically calibrated.

**Steps**

1. Freeze the baseline retriever and mine top-L candidates for each training
   query.
2. Label candidate relevance and, where possible, the support interval.
3. Cap the frames and transcript length to the same runtime contract used by
   the application.
4. Fine-tune the 2B-class reranker with QLoRA/LoRA, gradient checkpointing,
   batch size 1--2, and accumulation.
5. Evaluate reranking only on candidates where the correct result is already
   in the pool; separately track retrieval Recall@K.
6. Export a model/adapter manifest and run the full API regression suite with
   a safe fail-open fallback to fused order.

The [Qwen3-VL embedding/reranker project](https://github.com/QwenLM/Qwen3-VL-Embedding)
documents a dual-tower embedding model for recall and a single-tower,
cross-attention reranker for `(query, document)` relevance scoring, including
LoRA configuration examples. The reranker should receive raw candidate
evidence, not stored Qdrant vectors or the RRF score.

**Colab feasibility**: use a 24 GB+ GPU if available; 16 GB may work only with
strict frame limits and 4-bit adapter training. Do not promise a free Colab
runtime will supply this hardware. Full fine-tuning of a 2B+ multimodal model
is not recommended for this project.

### 7.7 Captioning, VLM verification, and temporal localisation

**Purpose**: create richer text evidence and check whether a final candidate
actually supports the query. This is not the first recall stage.

**Recommended policy**: do not fine-tune a VLM until steps 1--4 above are
evaluated. First improve prompts, frame selection, taxonomy, and the quality of
human evidence labels.

If tuning becomes necessary, build examples of:

```text
(query, ordered frames, transcript, candidate region) ->
{match, observed evidence, missing conditions, contradictions, event start/end}
```

Use human-reviewed structured labels. Do not train solely on captions generated
by the same VLM that will be evaluated; that creates self-confirming labels.

For open-weight VLMs, use adapter/LoRA training. Hosted API VLMs cannot be
post-trained by this repository unless their provider explicitly offers a
supported training product and the data policy permits it. Treat a hosted VLM
as an inference-only verifier unless that is confirmed.

**Colab feasibility**: experimentation only. VLM fine-tuning is label-heavy,
memory-heavy, and easy to overfit; use a larger managed GPU environment for a
serious run.

## 8. Google Colab runbook

Use Colab for reproducible experiments, not as a permanent data warehouse.
Runtime GPU type, duration, and availability are account-dependent.

### Notebook layout to implement

```text
01_validate_manifest.ipynb
02_build_windows_and_labels.ipynb
03_baseline_retrieval_eval.ipynb
04_train_text_retriever.ipynb
05_train_learned_fusion.ipynb
06_mine_hard_negatives.ipynb
07_train_multimodal_reranker.ipynb
08_train_visual_or_audio_adapter.ipynb
09_asr_finetune_and_eval.ipynb
10_export_and_integration_smoke_test.ipynb
```

### Every notebook must do this

1. Record the Git commit, base model revision, dataset manifest checksum, and
   random seed at the top of the run.
2. Check the assigned GPU with `nvidia-smi`; abort early if memory is below
   the plan for that experiment.
3. Mount only a secure, access-controlled Drive/bucket. Do not put raw
   sensitive CCTV footage in a public notebook or public Drive link.
4. Install pinned dependencies from a future, reviewed
   `post-training/requirements-colab.txt`; do not rely on an unpinned global
   Colab environment.
5. Write checkpoints and metrics to persistent storage at least every epoch.
6. Resume from the last checkpoint after a runtime disconnect.
7. Run held-out evaluation and save a machine-readable report before exporting
   an adapter.

### Minimal Colab bootstrap (template, not yet a repository command)

```python
# Verify the runtime first.
!nvidia-smi

# Install only the dependencies required by the selected notebook.
!pip install -q -U datasets accelerate peft bitsandbytes evaluate jiwer

# Clone the future training branch and identify the exact revision in the run log.
!git clone https://github.com/gdpranavl/RVCE_CVHackathon.git
%cd RVCE_CVHackathon
!git rev-parse HEAD
```

The training scripts referred to below are **future engineering work**. Create
them before treating these example contracts as runnable commands:

```text
python -m post_training.train_text --config configs/text_indic_v1.yaml
python -m post_training.train_fusion --config configs/fusion_v1.yaml
python -m post_training.mine_negatives --config configs/reranker_v1.yaml
python -m post_training.train_reranker --config configs/reranker_v1.yaml
python -m post_training.evaluate --config configs/eval_indic_v1.yaml
```

### Hardware decision table

| Workload | Known 8 GB laptop GPU | Colab / cloud recommendation |
|---|---|---|
| Data validation, feature extraction, learned fusion | Good | Optional GPU |
| Text embedding adapters | Possible with careful batches | 12--16 GB+ GPU preferred |
| ASR small/medium adapters | Possible but slow/risky | 16 GB+ GPU preferred |
| Visual/audio adapters | Possible only with aggressive limits | 16--24 GB+ GPU preferred |
| 2B multimodal reranker QLoRA | Not a dependable training target | 24 GB+ GPU preferred |
| Full VLM fine-tuning / full pretraining | No | Managed multi-GPU, only if justified |

For the current RTX 4070 Laptop GPU with roughly 8 GB VRAM, use the laptop for
indexing, inference, data preparation, and evaluation. Treat long training of
multimodal models as a cloud task.

## 9. Future engineering required in this repository

The training work needs a small, explicit subsystem rather than ad hoc
notebooks that silently change production behavior.

```text
post_training/
  README.md                    # this document
  schemas/                     # JSON Schema / Pydantic data contracts
  configs/                     # versioned YAML experiment configs
  data/                        # manifest validators and split builders
  mining/                      # baseline retrieval + hard-negative mining
  train/                       # text, fusion, ASR, audio, visual, reranker entry points
  evaluate/                    # retrieval, rank, temporal, language metrics
  export/                      # adapter/model manifest, conversion, smoke tests
  notebooks/                   # thin Colab notebooks calling the entry points
```

Required production changes, after a model has passed evaluation:

1. **Model registry**: a manifest per artifact containing base model, revision,
   adapter, SHA-256, vector dimension, tokenizer/processor revision, training
   data manifest, evaluation report, licence, and creation date.
2. **Versioned collections**: embedding changes require a new Qdrant
   collection/field version and a full reindex. Do not mix old and new vectors.
3. **Atomic cutover**: switch query encoder and index collection together;
   retain the previous collection until smoke tests and rollback window pass.
4. **Feature compatibility**: learned fusion models need a versioned feature
   schema and default values for missing modalities.
5. **Reranker boundary**: bound `rerank_depth`, frame count, byte size,
   timeout, and concurrency. Preserve fail-open fused retrieval if the model
   is unavailable or candidate media cannot be read.
6. **Data lineage**: save source/consent/licence and label provenance in every
   experiment report; never put raw private video in Git or debug logs.
7. **Observability**: log model version, candidate counts, stage timings,
   reranker failures, and per-language metrics without logging API keys or
   raw sensitive frames.
8. **Regression tests**: test schema validation, vector dimensions, model
   manifest loading, reranker fallback, language routing, and temporal bounds.

## 10. Edge-case checklist

- Event starts before or ends after a window: preserve original temporal
  labels and evaluate region overlap, not exact window identity only.
- Multiple events in one region: support multiple labelled intervals or split
  the example; never force one caption to describe both ambiguously.
- No audio / silent audio / corrupt audio: explicit modality-missing state.
- OCR or transcript language differs from spoken language: preserve both
  language IDs and scripts.
- Romanized Hindi/Kannada/Tamil: do not normalize it into English and lose the
  original query.
- Night, rain, blur, compression, occlusion, and unusual camera angles: make
  each a tagged evaluation slice.
- Duplicate YouTube/re-uploaded footage: hash/perceptual-hash and keep all
  variants in one source-group split.
- Caption hallucination: retain the raw model caption separately from human
  labels and never use it as ground truth without review.
- Ambiguous activity: label uncertainty; do not teach the model to infer crime
  from appearance or context alone.
- Dataset withdrawal: retain a deletion ledger and retrain/reindex affected
  artifacts if an impactful source is removed.

## 11. Acceptance gates for a PR that introduces a trained model

A model-change PR should include:

- model manifest and licence;
- immutable training-data manifest or approved secure reference;
- source-video-disjoint split proof;
- baseline vs candidate report with per-language/per-domain metrics;
- latency, GPU-memory, and failure-rate report;
- reindex/migration and rollback instructions, where embeddings changed;
- tests proving the application can run without the new model;
- a short qualitative error analysis, including false positives.

Reject the model change if it only improves aggregate metrics, leaks frames
across splits, cannot be reproduced from its manifest, or raises unacceptable
false positives for ambiguous surveillance queries.

## 12. Recommended first two-week hand-off

1. Define the manifest/schema and annotate a small, source-video-disjoint
   India-first evaluation set.
2. Run the current pipeline and publish baseline Recall@K, MRR/nDCG, temporal
   localisation, and per-language error slices.
3. Build hard-negative mining from actual RRF results.
4. Train/evaluate the learned fusion ranker.
5. Fine-tune/evaluate the text embedding model with Indian-language queries.
6. Fine-tune/evaluate the cross-encoder reranker only if candidate Recall@K is
   already high enough to make reranking meaningful.
7. Choose visual, audio, or ASR adaptation based on the largest remaining
   measured failure mode.

This produces a defensible demo faster than trying to post-train every model at
once, and it leaves clear evidence for each added layer of complexity.

