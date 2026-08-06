# Diagrammatic Explanations

Design diagrams for the video retrieval system. Written in Mermaid, which GitHub
renders inline, so they stay readable in the repository and stay in version
control as text rather than as images that drift from the code.

| File | Covers |
|---|---|
| [01_system_architecture.md](01_system_architecture.md) | Full system, and why indexing and retrieval are asymmetric |
| [02_control_flow.md](02_control_flow.md) | Query flow, library search, provider selection |
| [03_data_model.md](03_data_model.md) | Entities, vector contract, why modalities stay separate, normalisation |
| [04_sequence_diagrams.md](04_sequence_diagrams.md) | Spoken query, Drive indexing, library search |
| [05_modularity_and_deployment.md](05_modularity_and_deployment.md) | Seven modularity axes, topology, why not serverless |

## The system in one paragraph

An operator describes what they are looking for, in their own language, by
typing, speaking, or showing a reference image, and gets back the exact seconds
of footage that match, playable in place. Indexing runs once per video and is
expensive: segment, describe, store the text, discard the media. Retrieval runs
constantly and is cheap: filter by camera and capture time, score text overlap,
fetch media only when someone presses play.

## Three decisions worth defending

**Modalities are fused by rank, never averaged into one vector.** Averaging
loses the ability to say which modality matched, and lets an empty channel drag
down a genuine match. It is what makes a silent video searchable.

**Long video is scanned in chunks with known offsets.** A model's sense of
elapsed time drifts: it once placed an event at 200 s that occurs at 414 s, so
the cut clip showed the wrong footage. Chunking replaces the model's clock with
arithmetic.

**Search never calls a model.** Synonyms are generated once at index time and
stored, so a literal matcher can answer a loosely worded query in microseconds
instead of paying for inference on every keystroke.
