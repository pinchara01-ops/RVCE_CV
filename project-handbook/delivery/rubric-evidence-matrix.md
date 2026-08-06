# Rubric Evidence Matrix

## Purpose

This page is the review map for the repository. It connects each assessment
area to the implemented source, the detailed documentation, the automated
checks, and the manual evidence that a reviewer can reproduce. It is designed
to prevent a slide, diagram, or UI option from being treated as proof of a
capability that the source tree does not actually provide.

Use this alongside the [Acceptance Test Plan](acceptance-test-plan.md) and
[Acceptance Test Cases](acceptance-test-cases.md). The plan defines the
release gate; the cases define the observable pass/fail outcomes; this matrix
shows where every assessment requirement is evidenced.

## Evidence rules

- **Implemented** means the behaviour is represented in the checked-in source
  and has the listed verification coverage. It is not a claim that an external
  provider, a model download, or a particular video has been live-tested on
  every machine.
- **Automated** means a deterministic test or build gate can run without a
  human judging semantic output. It does not replace a real-video acceptance
  record where the result itself must be inspected.
- **Manual acceptance** means a reviewer follows the cited ATC and attaches
  safe evidence for the actual device, provider, test footage, and version.
- Do not attach API keys, raw credentials, private footage, server paths, or
  unredacted provider responses as review evidence.

## Assessment traceability

| Assessment area | What is implemented and documented | Source-of-truth evidence | Verification and acceptance evidence |
|---|---|---|---|
| **1. Detailed design** | End-to-end indexing and search flows; explicit boundaries for local and API-based operation; normalised named-vector schema; profile isolation; RRF recall; bounded cross-encoder reranking; optional VLM evidence/localisation; reliability, scalability, security, and trade-offs. | [System architecture](../design/system-architecture.md), [data and retrieval design](../design/data-and-retrieval-design.md), `processing_indexing/`, `query_retrieval/`. | Python contract tests; schema/profile tests; ATCs `CFG-001`, `IDX-005`, `IDX-007`, `QRY-001`–`QRY-010`; Qdrant-backed CI retrieval suite. |
| **2. Detailed user interface** | Four operator surfaces—Architecture, Index, Library/Evidence, Search—plus a live job view, error/recovery states, responsive/accessibility expectations, and an inspectable visual timeline. | [Interaction design](../design/interaction-design.md), `processing_debug_frontend/src/app/`, `processing_debug_frontend/src/components/`. | `npm test`, `npm run lint`, `npm run typecheck`, `npm run build`; ATCs `ENV-001`–`ENV-003`, `OBS-001`, `OBS-002`, `LIB-001`, `LIB-002`. |
| **3. Third-party libraries and tools** | Direct Python, browser, model, media, container, vector-store, and hosted-provider dependencies; purpose, operational impact, cost posture, licensing/supply-chain considerations, and non-dependencies are recorded. | [Dependency and provider register](../reference/dependency-register.md), `requirements*.txt`, `processing_debug_frontend/package.json`, `docker-compose.yml`, `.github/workflows/quality.yml`. | Dependency manifests are installed from scratch in CI. Before distribution, follow the register's licence and resolved-inventory checklist; do not infer a licence conclusion from a package name. |
| **5. Acceptance Test Plan** | Entry/exit criteria, environments, lawful test data, quality-metric semantics, failure severity, evidence requirements, local/cloud boundaries, and documented limitations. | [Acceptance Test Plan](acceptance-test-plan.md). | CI executes fast contracts, isolated Qdrant retrieval tests, and browser quality checks. A profile claim is accepted only when its relevant manual ATCs and a redacted evidence record are complete. |
| **6. Documentation** | Installation, architecture, interaction, operational configuration, dependencies, engineering process, ATP, ATCs, and this traceability map are separated by purpose and linked from a single handbook entry point. | [Project Handbook](../README.md), root [README](../../README.md), `PROCESSING_HANDOFF.md`, `PROCESSING_INDEXING_SPEC.md`. | Documentation review: follow the root quick start, choose a profile, run the cited quality gate, and execute the applicable ATCs. Update the relevant page whenever a public contract changes. |
| **7. Other quality evidence** | Credential/session redaction, cloud-consent gating, deterministic IDs, schema checks, cancellation, bounded retries, structured diagnostics, model/readiness status, result provenance, and metric honesty are treated as observable product requirements. | Runtime/session, Qdrant-store, diagnostic, reranking, and verification modules named in the [handbook source map](../README.md#source-of-truth-map). | ATCs `CFG-002`–`CFG-005`, `IDX-008`–`IDX-010`, `OBS-001`–`OBS-002`, `QRY-006`–`QRY-010`; secret-redaction and unavailable-service tests. |

## ATP, ATC, and test automation

| Layer | Reproducible command or record | What a pass means |
|---|---|---|
| Offline indexing contracts | `python -m pytest processing_indexing/tests -m "not integration" -q` | Deterministic indexing, profile, session, provider-adapter, diagnostics, and validation contracts passed without asserting live provider quality. |
| Offline retrieval contracts | `python -m pytest query_retrieval/tests -m "not qdrant" -q` | Fusion, decomposition, reranking, verification, metric, resilience, and preflight contracts passed without a local database. |
| Qdrant integration | `docker compose up -d qdrant` then `python -m pytest query_retrieval/tests -m qdrant -q --require-qdrant` | The intentionally destructive, isolated `video_windows_query_test` collection passed against a healthy Qdrant endpoint. The command fails immediately when Qdrant is unavailable. |
| Browser quality | From `processing_debug_frontend`: `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` | Client-side tests, linting, types, and production compilation passed. It is not an accessibility certification or full browser end-to-end semantic test. |
| Pull-request automation | [Quality workflow](../../.github/workflows/quality.yml) | A clean runner installs declared dependencies, starts the pinned Qdrant image, executes both Python gates, and builds the browser application. |
| Human acceptance | Complete the relevant [ATCs](acceptance-test-cases.md#manual-evidence-record) and attach the supplied evidence record to the review. | The actual profile, footage, hardware, provider state, visual UI, result evidence, and limitations were reviewed honestly. |

## Reviewer checklist

1. Confirm the selected profile and collection match the stated test run.
2. Confirm the relevant automated command/CI run is green; for local Qdrant
   integration, require the `--require-qdrant` result rather than accepting a
   skipped environment.
3. Run the P0/P1 ATCs for the profile being demonstrated, including one
   negative path (bad media, unavailable Qdrant, or provider quota failure).
4. Inspect Library and Search evidence for the claimed video: profile,
   timestamps, modality contributions, reranker/verification status, and
   refined playback interval.
5. For labelled retrieval claims, record Recall@K, MRR, nDCG@K, K, and stage
   timings. For ordinary live searches, confirm the metrics say *unevaluated*.
6. Record skipped cases, external rate limits, cold model downloads, and
   hardware constraints as limitations—not as passes.

## Current claim boundary

The repository supports a local single-operator workflow and an API-based
workflow with explicit external-provider consent. It does **not** claim
production multi-tenancy, universal video-recognition accuracy, provider
uptime, free-tier throughput, browser accessibility certification, or a
committed real-media golden benchmark. These limits are intentional and are
kept visible in the design and ATP so reviewers can distinguish working
software from future scale-up work.
