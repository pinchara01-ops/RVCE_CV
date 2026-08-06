# Third-Party Dependency & Provider Register

> **Scope:** direct dependencies, model artifacts, tools, and hosted services used by this repository.
> **Last reviewed:** 2026-08-06.
> **Sources inspected:** `requirements-processing.txt`, `requirements.txt`, `processing_debug_frontend/package.json`, `processing_debug_frontend/package-lock.json`, `docker-compose.yml`, and the runtime-profile and provider code.

This register is an engineering inventory, not legal advice or a complete software bill of materials (SBOM). It records what the application declares or invokes directly, why it is present, and the operational decisions a maintainer should understand before enabling it. Transitive packages, downloaded model artifacts, and deployed service terms must be reviewed at the exact version and account tier used for a release.

## At a glance

| Boundary | Default self-hosted path | API-based path | Main trade-off |
|---|---|---|---|
| Video processing | Python, FFmpeg/FFprobe, CPU or local GPU models | Python and FFmpeg/FFprobe prepare bounded media inputs | Local processing keeps media on the machine; API processing can reduce model-download and inference burden. |
| Embedding and transcription | Faster-Whisper, X-CLIP, CLAP, BGE-M3 | Gemini Embedding 2 and Gemini Flash-Lite | The two paths intentionally use different vector contracts and must never share a collection. |
| Vector database | Qdrant 1.11.5 in Docker | Qdrant Cloud over HTTPS | Local storage requires Docker; Cloud storage requires credentials, network access, and a data-handling decision. |
| Precision stage | Optional local Qwen3-VL-Reranker-2B | The same optional local reranker; hosted VLM choices are available for captioning/verification | Reranking is bounded to fused candidates, so it is not a full-library model pass. |
| Browser and API | Next.js/React frontend plus FastAPI/Uvicorn backend | Same | The application server remains local in both profiles today. |

## Dependency resolution and provenance

The Python manifests use compatible version ranges rather than a lockfile with hashes. The frontend has a committed npm lockfile, which gives it a more reproducible resolution boundary. For a release or evaluation environment, capture the resolved Python environment (`pip freeze` or a generated lockfile), record model revisions, and retain a machine-readable SBOM alongside the build artifact.

The following are the source-of-truth files for direct dependencies:

- `requirements-processing.txt` — the current processing, retrieval, API, and quality-tool set.
- `requirements.txt` — a smaller, overlapping legacy requirement list; it is not sufficient on its own for the full processing UI.
- `processing_debug_frontend/package.json` and `package-lock.json` — the browser application and its resolved npm tree.
- `docker-compose.yml` — the pinned local Qdrant image.

No repository-wide `LICENSE`, `NOTICE`, or generated third-party attribution inventory is currently tracked. That is a governance gap to resolve before distributing a packaged build.

## Automation and evidence

The repository's [quality workflow](../../.github/workflows/quality.yml) is a
repeatable integration check for the declared Python/browser manifests and the
pinned Qdrant image. It installs the manifests from scratch, starts Qdrant in
an isolated runner, runs the Python quality gates, and builds the browser
application. It is a dependency-consumption check—not a substitute for a
resolved licence/SBOM review, model-card review, or provider terms audit.

The [rubric evidence matrix](../delivery/rubric-evidence-matrix.md) maps this
register to the acceptance plan and the concrete test evidence expected in a
review.

## Direct application libraries

### Backend, API, and operational libraries

| Dependency | Declared source/version policy | Role in this system | Runtime boundary and impact | Maintainer notes |
|---|---|---|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) | `fastapi>=0.115,<1` | HTTP API for indexing jobs, runtime sessions, library views, and search. | Local Python service. Parses browser requests and owns public-response redaction. | Keep request-size limits, CORS policy, authentication strategy, and error redaction under review when exposing beyond localhost. |
| [Uvicorn](https://www.uvicorn.org/) | `uvicorn[standard]>=0.30,<1` | ASGI server for the FastAPI application. | Local process launched by the project scripts. | Development launcher settings are not a production deployment configuration. |
| [Pydantic](https://docs.pydantic.dev/) | `pydantic>=2.7,<3` | Request, payload, vector, and profile validation. | In-process validation boundary. | Validation is relied upon to reject malformed vectors and profile settings; retain tests when schema changes. |
| [python-multipart](https://andrew-d.github.io/python-multipart/) | `python-multipart>=0.0.9,<1` | Multipart video upload parsing. | Receives untrusted browser-uploaded files. | Pair with upload-size, media-type, storage, and antivirus policies if the service becomes multi-user. |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | `python-dotenv>=1.0,<2` | Loads optional local environment configuration. | Local configuration convenience. | `.env` files can contain secrets; keep them ignored and never export them with job diagnostics. |
| [HTTPX](https://www.python-httpx.org/) | `httpx>=0.27,<1` | HTTP client and provider integrations. | Outbound network path for selected hosted providers. | Set explicit timeouts, retry rules, and sanitized errors for every provider integration. |
| [Qdrant Python Client](https://qdrant.tech/documentation/interfaces/) | `qdrant-client>=1.11,<1.12` | Creates profile-specific named-vector schemas, upserts windows, and performs retrieval. | Connects to local Qdrant or Qdrant Cloud. | The client minor series is constrained; update it together with collection-schema smoke tests. |
| [OpenAI Python](https://developers.openai.com/api/docs/libraries/python) | `openai>=1.68,<3` | Optional OpenAI vision/caption and verification provider integration. | Outbound only when an OpenAI stage is selected and a key is supplied. | The app labels this option as paid/API-credit required. Treat requests, model names, and pricing as account-dependent. |
| [Google Gen AI SDK](https://ai.google.dev/gemini-api/docs/libraries) | `google-genai>=1.0,<2` | Gemini Embedding 2 and Gemini Flash-Lite integration for API-based processing and query flow. | Outbound only in the API-based profile, after cloud-video consent and key configuration. | Preserve independent field embeddings and profile isolation; free-tier availability and quotas are not a performance guarantee. |

### Local machine-learning and media libraries

| Dependency | Declared source/version policy | Role in this system | Runtime boundary and impact | Maintainer notes |
|---|---|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | `faster-whisper>=1.0,<2` | Local transcription using the configured Whisper checkpoint (`small` by default). | Lazy local model download; CPU or CUDA-capable inference. | First run can be materially slower because weights are fetched and cached. Model-card terms are separate from package terms. |
| [HF Xet](https://huggingface.co/docs/hub/xet/index) | `hf-xet>=1.0,<2` | Hugging Face transfer support for model artifacts. | Download-time infrastructure, not an application feature. | Review cache location, revision pinning, and network policy on managed machines. |
| [Transformers](https://huggingface.co/docs/transformers/) | `transformers>=4.57,<5` | Loads X-CLIP, CLAP, local Qwen2.5-VL, and supporting processors. | Lazy local model inference and model artifact downloads. | Pin tested versions for reproducibility; checkpoint behavior and licenses come from their model repositories. |
| [Sentence Transformers](https://www.sbert.net/) | `sentence-transformers>=3.0,<4` | Loads the optional Qwen3-VL reranker through the cross-encoder interface. | Bounded local precision stage after fusion. | It is deliberately not run over the whole library. |
| [Qwen VL Utils](https://github.com/QwenLM/Qwen2.5-VL) | `qwen-vl-utils>=0.0.14,<1` | Utilities required by the local Qwen multimodal runtime. | Optional local captioning/reranking support. | Upgrade in lockstep with the supported Qwen model implementation. |
| [PyTorch](https://pytorch.org/) | `torch>=2.6,<3` | Tensor runtime for local encoders and optional CUDA acceleration. | CPU by default; may use a compatible NVIDIA GPU. | Select the wheel that matches the Python/CUDA driver environment; GPU support is not guaranteed merely by installing the package. |
| [OpenCV](https://opencv.org/) | `opencv-python-headless>=4.9,<5` | Frame decoding, sampling, and image preparation. | Processes untrusted video bytes locally. | Prefer the headless build for a service environment; keep media parser updates current. |
| [Pillow](https://python-pillow.github.io/) | `pillow>=10,<12` | Image decoding and contact-sheet construction for reranking. | Local sampled-frame processing. | Image decoders are security-sensitive; retain supported versions and exercise malformed-media tests. |
| [librosa](https://librosa.org/) | `librosa>=0.10,<1` | Audio loading and feature preparation for local audio embedding. | Local audio processing. | Its transitive numeric stack should be locked for reproducible audio behavior. |
| [NumPy](https://numpy.org/) | `numpy>=1.26,<3` | Numeric vectors, normalization, and media/model data interchange. | Core local numerical dependency. | Keep ABI compatibility aligned with PyTorch, OpenCV, and the selected Python version. |

### Frontend and developer-quality libraries

| Dependency | Declared source/version policy | Role in this system | Runtime boundary and impact | Maintainer notes |
|---|---|---|---|---|
| [Next.js](https://nextjs.org/docs) | `16.2.12` (lockfile-resolved direct dependency) | Browser application, routes, build, and development server. | Local browser/UI service. | Keep Next.js and its ESLint config aligned during upgrades. |
| [React](https://react.dev/) and [React DOM](https://react.dev/) | `19.2.4` | Component rendering, job diagnostics, architecture controls, library, and search UI. | Browser runtime. | Maintain stable list keys and component tests; browser-only session storage holds an opaque session ID, not provider keys. |
| [Recharts](https://recharts.org/) | `^3.10.1` | Processing and retrieval diagnostic visualizations. | Browser runtime. | Treat visual metrics as diagnostic information, not a substitute for backend evidence. |
| [TypeScript](https://www.typescriptlang.org/) | `^5` | Static checking for frontend source. | Build-time quality control. | `npm run typecheck` is the intended verification command. |
| [ESLint](https://eslint.org/) and `eslint-config-next` | `^9` / `16.2.12` | Frontend linting. | Build-time quality control. | Run lint after React/Next upgrades. |
| [Vitest](https://vitest.dev/) | `^4.1.10` | Frontend unit tests. | Build-time quality control. | Keep test coverage focused on user-visible filtering, state, and protocol behavior. |
| [pytest](https://docs.pytest.org/) | `pytest>=8,<9` | Python test runner. | Build-time and integration-test quality control. | Tests marked `integration` require actual FFmpeg, model availability, test media, and Qdrant. |
| [Ruff](https://docs.astral.sh/ruff/) | `ruff>=0.6,<1` | Python linting and formatting checks. | Build-time quality control. | Add a pinned configuration and CI command before treating lint cleanliness as a release gate. |
| [GitHub Actions](https://docs.github.com/actions) (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`) | Pinned action major versions in `.github/workflows/quality.yml` | Pull-request automation for dependency installation, isolated Qdrant tests, and browser quality gates. | Hosted CI only; it is not part of the product runtime. | Review action revisions, runner access, logs, and organisation billing/security policy before enabling it on a public or sensitive repository. |

## Model and service inventory

Packages make the code capable of loading models; they do not grant rights to use every model or service. Confirm each model-card, provider, data-residency, and acceptable-use term before an external deployment.

| Stage | Current selectable implementation | Where it runs | Access and cost posture | Compatibility / operational notes |
|---|---|---|---|---|
| Visual embeddings, self-hosted | `microsoft/xclip-base-patch32` | Local CPU/GPU through Transformers. | Downloaded checkpoint; no per-request API charge. | Produces the self-hosted visual vector contract. It cannot be mixed with the API profile. |
| Audio embeddings, self-hosted | `laion/clap-htsat-unfused` | Local CPU/GPU through Transformers. | Downloaded checkpoint; no per-request API charge. | Produces the self-hosted audio vector contract. Silent/missing audio is explicitly represented by the local pipeline. |
| Transcript and caption-text embeddings, self-hosted | `BAAI/bge-m3` | Local CPU/GPU through Sentence Transformers. | Downloaded checkpoint; no per-request API charge. | Produces the self-hosted `speech` and `caption` vector contract. |
| Transcription, self-hosted | Faster-Whisper `small` | Local CPU/GPU. | Downloaded checkpoint; no per-request API charge. | The first run obtains local artifacts. Resource use depends on the source duration, hardware, and device setting. |
| Captioning, self-hosted | `Qwen/Qwen2.5-VL-3B-Instruct` (optional) | Local CPU/GPU, loaded only if selected. | Downloaded checkpoint; no per-request API charge. | The standard self-hosted profile also supports selection-only operation with no caption VLM. |
| Reranking, both profiles | `Qwen/Qwen3-VL-Reranker-2B` (optional) | Local CPU/GPU, loaded only after candidate fusion. | Downloaded checkpoint; no hosted reranker bill in this implementation. | Receives raw query plus bounded candidate frames/transcript/caption; not RRF scores or raw vector scores. |
| API embeddings | Gemini Embedding 2 | Gemini API. | The profile labels this as a free-tier default, subject to the account's current quota and policy. | Four separate compatible vectors are created; API profile uses its own 1536-D collection contract. |
| API transcription, captions, query decomposition, verification, localisation | Gemini 3.5 Flash-Lite | Gemini API. | The profile labels this as a free-tier default, subject to quota and policy. | Video sent to this route requires explicit cloud-video consent in the UI. |
| Hosted captioning/verification alternative | OpenAI `gpt-4.1-mini` | OpenAI API. | Explicitly labelled paid/API-credit required in the runtime profile. | Selectable for API-profile captioning and verification; it is not the default embedding path. |
| Hosted captioning/verification alternative | NVIDIA `nvidia/cosmos3-nano-reasoner` | NVIDIA API endpoint. | Explicitly labelled paid/NVIDIA API-credit required in the runtime profile. | Selectable for API-profile captioning and verification; validate current catalogue access and quotas for the account. |
| Legacy/local query decomposition fallback | Groq, configured as `openai/gpt-oss-20b` when key and feature flag allow it | Groq API. | Account, quota, and billing policy are external to the repository. | The self-hosted code falls back deterministically when no usable provider response is available; the UI label should not be read as proof of a local query LLM. |
| Optional generic hosted VLM compatibility | User-configured OpenAI-compatible Qwen endpoint | Provider chosen by operator. | Operator-specific. | This is a compatibility integration, not a hosted service operated by this project. Use a trusted endpoint and do not commit its key. |

## Hosted-provider terms and cost controls

Provider terms, regions, quotas, model availability, and pricing change independently of the repository. The UI's cost labels should be treated as guidance at the time of configuration, not a billing guarantee.

| Provider / tool | What the repository uses | Free or paid posture | Controls required before use | Authoritative reference |
|---|---|---|---|---|
| Qdrant local | Pinned `qdrant/qdrant:v1.11.5` Docker image with a named local volume. | No managed-service bill from Qdrant Cloud, but the operator provides the machine, Docker environment, storage, and network. | Keep the local service bound appropriately; back up or delete the Docker volume deliberately. | [Qdrant documentation](https://qdrant.tech/documentation/) |
| Qdrant Cloud | API-based profile's named-vector store over HTTPS. | Qdrant publishes free and paid Cloud offerings; capacity and retention are service-plan dependent. | Require cluster URL/key, test connection preflight, review region/data handling, and avoid treating a free tier as durable archival storage. | [Cloud cluster documentation](https://qdrant.tech/documentation/cloud/create-cluster/) · [pricing](https://qdrant.tech/pricing/) |
| Gemini API | Gemini Embedding 2 and Flash-Lite in the API-based default. | Google publishes free and paid tiers; free-tier limits, data-use terms, and availability can differ by account and region. | Obtain a user key, capture explicit consent before uploading footage, display quota failures, and never promise uninterrupted capacity. | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) · [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) |
| OpenAI API | Optional caption/verification provider. | Paid/API-credit-required selection in this codebase. | Obtain an operator key and budget approval; use the model's current pricing page rather than hard-coded rates in product copy. | [OpenAI API pricing](https://openai.com/api/pricing/) · [GPT-4.1 mini documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini) |
| NVIDIA API / NIM | Optional Cosmos Reasoner caption/verification provider. | The runtime profile treats it as paid/API-credit required; developer-program and evaluation access, if offered, are account-specific. | Confirm the selected model, account entitlement, quota, data policy, and regional endpoint immediately before use. | [NVIDIA Cosmos NIM documentation](https://docs.nvidia.com/nim/cosmos/latest/introduction.html) |
| Groq API | Optional legacy self-hosted query-decomposition call. | Account-specific quota and commercial terms. | Keep the feature flag explicit, configure a bounded timeout, and preserve deterministic fallback when unavailable. | [Groq documentation](https://console.groq.com/docs) |
| Docker / Docker Desktop | Runs local Qdrant in the documented developer workflow. | Docker Engine and Docker Desktop terms are distinct; Desktop commercial use may require a subscription depending on the organisation. | Review the applicable Docker agreement for the operator's organisation and avoid assuming a personal entitlement transfers to a team. | [Docker subscription agreement](https://www.docker.com/legal/docker-subscription-service-agreement/) |
| FFmpeg / FFprobe | Required system tools for probing, normalisation, audio extraction, and bounded media clips. | Distributed separately from this repository. | Verify the build's configured codecs and licence obligations; keep the executable patched and on the service path. | [FFmpeg legal information](https://ffmpeg.org/legal.html) |

## Security, licensing, and supply-chain considerations

### Credential handling

- API-profile keys are designed to live only in the backend's in-memory runtime session. The browser stores an opaque session identifier; public API responses expose only whether a key is configured.
- A backend restart or session expiry clears those in-memory keys. This is suitable for an interactive local application, not a substitute for an enterprise secret manager in a deployed service.
- Legacy environment-variable paths also exist for local/hosted integrations. `.env` files, shell history, diagnostic exports, and process listings remain sensitive operational surfaces.
- Do not log provider headers, raw configuration, URLs containing credentials, or exception text before redaction.

### Model and media supply chain

- Downloaded checkpoints are separate third-party artifacts. Each has its own model card, licence, terms, revision history, and possible gated-access requirements.
- The Qwen3-VL reranker intentionally uses `trust_remote_code=True` for one allow-listed model only. This is a material supply-chain decision: pin the reviewed model revision, inspect the model repository, and do not turn a browser-provided model name into an unrestricted remote-code loader.
- Video, image, audio, and document decoders process untrusted data. Keep FFmpeg, OpenCV, Pillow, Python, Node, and their transitive dependencies patched; test malformed and unsupported media.
- Model caches may contain large downloaded artifacts. Treat their provenance, update policy, local disk location, and removal process as operational controls.

### Licensing and attribution

- This register intentionally does not declare a project licence or make compatibility determinations. Package licences, model licences, Docker terms, and hosted-service agreements are distinct and must be evaluated together.
- Before distribution, generate a resolved dependency inventory, scan package and model licences, preserve required notices, and make a project-level licence decision.
- Prefer official release artifacts, pinned digests/revisions, dependency vulnerability scanning, and change review for every package, container, or model update.

## Explicit non-dependencies and implementation boundaries

The following should not be implied by the architecture diagrams or UI labels:

| Item | Current status |
|---|---|
| Pinecone, Weaviate, Zilliz, or another interchangeable hosted vector store | Not implemented. Qdrant Cloud is the API-based vector-store implementation; local Qdrant serves the self-hosted profile. |
| A hosted Qwen reranker | Not implemented. The optional Qwen3-VL reranker is local and runs only over the fused candidate set. |
| OpenAI text/media embeddings in the API profile | Not implemented as a selectable compatible embedding profile. OpenAI is currently a caption/verification alternative. |
| Gemma embedding or a Gemma local VLM | Not implemented in the checked runtime profiles. |
| A local query-decomposition LLM in the standard self-hosted path | Not established by the current code. The legacy path uses cached decomposition, optional Groq, then deterministic fallback. |
| A generic arbitrary remote-code model selector | Intentionally not implemented; local Qwen reranker models are allow-listed. |

## Maintenance checklist

Use this checklist when changing an external dependency, model, or service:

1. Update the direct manifest and, where applicable, the frontend lockfile or container image tag/digest.
2. Record the resolved version, model revision, provider model ID, and test environment in the change evidence.
3. Re-run the relevant unit, API, frontend, and integration tests, including profile/schema compatibility checks for any embedding change.
4. Review new data boundaries: media sent off-device, payload fields stored in Cloud Qdrant, retention, region, API permissions, and secret exposure.
5. Review licensing, notices, model-card restrictions, and the vendor's current pricing/quota documentation.
6. Update this register and the runtime-configuration guide when a dependency changes user setup, hardware, cost, or risk.

The complementary operating instructions are in [Runtime configuration](runtime-configuration.md); system boundaries and vector contracts are documented in the design section of the handbook.
