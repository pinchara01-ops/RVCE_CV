# Data Model

## Entities

```mermaid
erDiagram
    VIDEO ||--o{ WINDOW : "segmented into"
    WINDOW ||--|{ VECTOR : "carries"
    VIDEO {
        string video_id PK
        string name
        string camera "parsed from filename"
        datetime recorded_at "parsed from filename"
        float duration_seconds
        int window_count
        string source "upload | drive"
    }
    WINDOW {
        string window_id PK
        string video_id FK
        float start "offset in seconds"
        float end
        datetime absolute_time "recorded_at + start"
        string caption
        string transcript
        array objects
        array actions
        array audio_events
        array search_terms "synonyms for recall"
    }
    VECTOR {
        string window_id FK
        string name "visual|audio_event|speech_text|vlm_text"
        int dimensions
        string distance "cosine"
    }
```

## Vector contract per profile

The dimensions differ between profiles, which is why an index built under one
cannot be searched under the other. The UI states this rather than letting
someone discover it through bad results.

```mermaid
flowchart LR
    subgraph SH["Self-hosted"]
        S1["visual · 512<br/>X-CLIP"]
        S2["audio · 512<br/>CLAP"]
        S3["speech · 1024<br/>Whisper + BGE-M3"]
        S4["caption · 1024<br/>Qwen2.5-VL"]
    end

    subgraph AB["API-based"]
        A1["visual · 1536"]
        A2["audio · 1536"]
        A3["transcript · 1536"]
        A4["caption · 1536"]
        A5["all: Gemini Embedding 2"]
    end

    SH -.incompatible.- AB

    style SH fill:#16213e,stroke:#60a5fa,color:#eee
    style AB fill:#0f3460,stroke:#c9a227,color:#eee
```

## Why modalities stay separate

```mermaid
flowchart TD
    W["One window"] --> V["visual vector"]
    W --> A["audio vector"]
    W --> S["speech vector"]
    W --> C["caption vector"]

    V --> RRF["Reciprocal-rank fusion<br/>by rank, never by raw score"]
    A --> RRF
    S --> RRF
    C --> RRF

    RRF --> ANS["Ranked candidates"]

    BAD["Averaging into one vector"] -.->|"discarded design"| LOSS["Cannot say which<br/>modality matched.<br/>An empty channel drags<br/>the score down."]

    style RRF fill:#143d29,stroke:#4ade80,color:#eee
    style BAD fill:#3d1414,stroke:#f87171,color:#eee
    style LOSS fill:#3d1414,stroke:#f87171,color:#eee
```

This is what makes a silent video searchable. With no audio track, the audio and
speech channels contribute no rank at all, rather than contributing a zero score
that would push genuine visual matches down the ranking.

## Normalisation

Third normal form on the relational side: a window carries no video-level
attribute, so a video renamed once is renamed everywhere.

The repeated groups (`objects`, `actions`, `audio_events`, `search_terms`) are a
deliberate exception. They are denormalised into arrays because they are always
read as a unit with their window and never queried independently, so a join
table would add cost without buying anything.
