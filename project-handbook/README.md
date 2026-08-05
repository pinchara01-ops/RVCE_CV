# Project Handbook

This handbook is the authoritative human-facing guide to the Video Search
Workbench. It explains the implemented system, the boundaries around external
services, and the evidence required to accept a release. It complements the
root [README](../README.md), which remains the fastest route to installation
and first use.

## What this handbook covers

| Reader goal | Start here | Then read |
|---|---|---|
| Understand the system end-to-end | [System architecture](design/system-architecture.md) | [Data and retrieval design](design/data-and-retrieval-design.md) |
| Understand the browser experience | [Interaction design](design/interaction-design.md) | [Acceptance test cases](delivery/acceptance-test-cases.md) |
| Evaluate libraries, tools, cost, and operational dependence | [Dependency register](reference/dependency-register.md) | [Runtime configuration](reference/runtime-configuration.md) |
| Run or review quality checks | [Engineering process](delivery/engineering-process.md) | [Acceptance test plan](delivery/acceptance-test-plan.md) |

## Evidence and terminology

The documents distinguish three states deliberately:

- **Implemented** — behavior represented in the current source tree. Relevant
  automated and manual evidence is identified in the acceptance material; a
  selectable provider is not thereby claimed to have a live account validation.
- **Selectable** — a model or provider presented in the UI or runtime profile;
  selecting it may still require a local model download, a compatible device,
  a valid API key, or provider quota.
- **Proposed scale-up** — an operational next step, not a claim that the
  current local development setup already operates at that scale.

The distinction prevents an architectural diagram from overstating validation
or turning a configuration option into a production guarantee.

## Documentation model

The layout keeps explanation, reference, operational process, and acceptance
work separate:

```text
project-handbook/
├── design/       # Why the system is shaped this way and how data moves
├── reference/    # Stable contracts: providers, tools, configuration, schemas
└── delivery/     # How the system is built, tested, and accepted
```

This makes it possible to answer a conceptual question without wading through
commands, and to execute a test without inferring behavior from a diagram.

## Source-of-truth map

| Concern | Primary implementation source |
|---|---|
| Runtime profiles and provider compatibility | [`processing_indexing/runtime_profiles.py`](../processing_indexing/runtime_profiles.py) |
| Credential lifecycle and redaction | [`processing_indexing/runtime_sessions.py`](../processing_indexing/runtime_sessions.py) |
| Self-hosted indexing contract | [`processing_indexing/pipeline.py`](../processing_indexing/pipeline.py), [`processing_indexing/models.py`](../processing_indexing/models.py) |
| API-based indexing contract | [`processing_indexing/api_pipeline.py`](../processing_indexing/api_pipeline.py) |
| Named-vector persistence | [`processing_indexing/qdrant_store.py`](../processing_indexing/qdrant_store.py), [`processing_indexing/profile_qdrant_store.py`](../processing_indexing/profile_qdrant_store.py) |
| Query, fusion, reranking, and verification | [`query_retrieval/api.py`](../query_retrieval/api.py), [`query_retrieval/fusion.py`](../query_retrieval/fusion.py), [`query_retrieval/reranking.py`](../query_retrieval/reranking.py), [`query_retrieval/verification.py`](../query_retrieval/verification.py) |
| Browser routes and interaction states | [`processing_debug_frontend/src/app`](../processing_debug_frontend/src/app) |
| API surface | [`processing_indexing/debug_api.py`](../processing_indexing/debug_api.py) |

When code and a handbook page disagree, code is the operational source of
truth. Update the relevant handbook page in the same change that alters a
public contract, a profile, a schema, or a user-visible workflow.

## Maintenance rules

1. Update **design** when a new data path, collection schema, or trust boundary
   is introduced.
2. Update the **dependency register** when adding a package, model, hosted
   provider, runtime tool, or commercial service.
3. Update the **acceptance plan and cases** when a user journey gains a new
   success or failure state.
4. Keep provider pricing and quotas date-stamped and linked to the provider's
   official page; they are commercial facts, not constants in this repository.
5. Never put credentials, source-video paths, customer footage, or raw model
   responses in handbook examples.
