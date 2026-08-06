# System Architecture

Mermaid renders natively on GitHub, so these diagrams stay readable in the
repository and in any Markdown viewer without an image pipeline.

## Complete system

```mermaid
flowchart TB
    subgraph Client["Browser (React 19 + Vite)"]
        Q["Query composer<br/>text · voice · image · reference clip"]
        L["Language selector<br/>13 languages"]
        D["Developer settings<br/>models · keys · profile"]
        R["Results<br/>playable clips"]
    end

    subgraph API["FastAPI backend"]
        RT["Router"]
        PR["Prompt builder<br/>search_prompt.py"]
        CH["Chunker<br/>chunking.py"]
        MD["NVR metadata<br/>camera · capture time"]
        FF["ffmpeg / ffprobe<br/>probe · cut · transcode · sample"]
    end

    subgraph Providers["Provider adapters"]
        GM["Gemini runtime<br/>native video"]
        OA["OpenAI runtime<br/>sampled frames"]
        CU["Custom endpoint<br/>OpenAI-compatible"]
    end

    subgraph Sources["Sources"]
        UP["Upload"]
        DR["Google Drive"]
        FUT["Supabase · Qdrant · Pinecone<br/>Weaviate · S3 · pgvector"]
    end

    subgraph Store["Index"]
        LIB["Window records<br/>text + camera + time"]
        QD["Qdrant<br/>named vectors"]
    end

    Q --> RT
    L --> RT
    D --> RT
    UP --> RT
    DR --> RT
    FUT -.not built.-> RT

    RT --> PR
    RT --> CH
    RT --> MD
    CH --> FF
    RT --> FF

    PR --> GM
    PR --> OA
    PR --> CU

    GM --> LIB
    OA --> LIB
    LIB -.optional.-> QD

    LIB --> RT
    RT --> R

    style Client fill:#1a1a2e,stroke:#c9a227,color:#eee
    style API fill:#16213e,stroke:#c9a227,color:#eee
    style Providers fill:#0f3460,stroke:#c9a227,color:#eee
    style Sources fill:#1a1a2e,stroke:#666,color:#eee
    style Store fill:#16213e,stroke:#666,color:#eee
```

## Why the two paths are asymmetric

Indexing is expensive and runs once per video. Retrieval is cheap and runs
constantly. Separating them is the central design decision: it is what lets a
library of hundreds of videos answer a query in microseconds while costing
kilobytes of storage.

```mermaid
flowchart LR
    subgraph Once["Indexing: once per video, expensive"]
        A1["Download / upload"] --> A2["Probe duration<br/>+ parse camera & time"]
        A2 --> A3["Segment into windows"]
        A3 --> A4["Describe each window<br/>via model"]
        A4 --> A5["Store text records"]
        A5 --> A6["Delete local media"]
    end

    subgraph Many["Retrieval: every query, cheap"]
        B1["Query"] --> B2["Extract time / camera filter"]
        B2 --> B3["Score IDF-weighted<br/>token overlap"]
        B3 --> B4["Rank"]
        B4 --> B5["Fetch media only<br/>when played"]
    end

    A5 -.text index.-> B3

    style Once fill:#3d2914,stroke:#c9a227,color:#eee
    style Many fill:#143d29,stroke:#4ade80,color:#eee
```
