# Modularity and Deployment

## Seven independent axes

Every layer can be swapped without touching the others. Naming a layer and
having an answer for it is the point.

```mermaid
mindmap
  root((Modularity))
    Input
      Typed text
      Spoken audio
      Reference image
      Reference clip
      Any combination, one request
    Provider
      Gemini native video
      OpenAI sampled frames
      Custom OpenAI-compatible endpoint
    Deployment
      API-based hosted
      Self-hosted local
      Per-stage selection
    Source
      Upload
      Google Drive
      Six connector slots
    Storage
      Local Qdrant
      Qdrant Cloud
      Stateless single-call
    Language
      13 interface languages
      Independent of content language
    Prompt
      Own module
      Shared edge cases
      Index and search aligned
```

## Adding a provider is an adapter, not a rewrite

```mermaid
flowchart LR
    P["Prompt builder"] --> IF{{"One interface:<br/>prompt + media + schema<br/>→ structured JSON"}}

    IF --> G["gemini_runtime"]
    IF --> O["openai_runtime"]
    IF --> C["custom endpoint"]
    IF -.->|"new provider"| N["new_runtime.py"]

    G --> R["Normalised result"]
    O --> R
    C --> R
    N -.-> R

    style IF fill:#0f3460,stroke:#c9a227,color:#eee
    style N fill:#143d29,stroke:#4ade80,color:#eee
```

## Deployment topology

```mermaid
flowchart TB
    subgraph V["Vercel"]
        FE["Static SPA<br/>Vite build"]
    end

    subgraph C["Container host: Render / Railway / Fly"]
        BE["FastAPI + Uvicorn"]
        FFM["ffmpeg + ffprobe"]
    end

    subgraph X["External"]
        GEM["Gemini API"]
        OAI["OpenAI API"]
        GD["Google Drive"]
    end

    FE -->|"VITE_SEARCH_API_URL"| BE
    BE --- FFM
    BE --> GEM
    BE --> OAI
    BE --> GD

    style V fill:#16213e,stroke:#60a5fa,color:#eee
    style C fill:#0f3460,stroke:#c9a227,color:#eee
    style X fill:#1a1a2e,stroke:#666,color:#eee
```

### Why the backend cannot be serverless

```mermaid
flowchart LR
    REQ["A search request"] --> A{"Body up to<br/>650 MB"}
    A -->|"serverless cap 4.5 MB"| F1["Upload impossible"]
    REQ --> B{"Runs 30 s<br/>to minutes"}
    B -->|"cap 10-60 s"| F2["Times out"]
    REQ --> C{"Writes clips,<br/>serves them later"}
    C -->|"ephemeral, per-invocation"| F3["404 on playback"]
    REQ --> D{"Needs ffmpeg"}
    D -->|"not present"| F4["No cutting"]

    F1 --> CONC["Container, not a function"]
    F2 --> CONC
    F3 --> CONC
    F4 --> CONC

    style CONC fill:#143d29,stroke:#4ade80,color:#eee
    style F1 fill:#3d1414,stroke:#f87171,color:#eee
    style F2 fill:#3d1414,stroke:#f87171,color:#eee
    style F3 fill:#3d1414,stroke:#f87171,color:#eee
    style F4 fill:#3d1414,stroke:#f87171,color:#eee
```

Any one of those four rules it out. The body limit and the ephemeral filesystem
are the fatal pair: a 4.5 MB cap makes video upload impossible, and `/tmp` is
not shared between invocations, so a clip written by one request would 404 when
the next request tried to serve it.
