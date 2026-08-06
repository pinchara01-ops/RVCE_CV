# Control Flow

## Query: from a sentence to a playable clip

```mermaid
flowchart TD
    START(["User submits a request"]) --> HAS{"What was<br/>supplied?"}

    HAS -->|text| BUILD
    HAS -->|voice recording| BUILD
    HAS -->|reference image| BUILD
    HAS -->|reference clip| BUILD

    BUILD["Build one multimodal request<br/>all attachments travel together"] --> PROBE["ffprobe: duration + streams"]
    PROBE --> LONG{"Duration ><br/>150 s?"}

    LONG -->|no| ONE["Single pass"]
    LONG -->|yes| SPLIT["Split into 120 s chunks<br/>5 s overlap, known offsets"]

    SPLIT --> PAR["Scan chunks in parallel"]
    PAR --> OFFSET["Add chunk offset<br/>as exact arithmetic"]
    OFFSET --> MERGE["Merge, drop overlaps"]

    ONE --> VALIDATE
    MERGE --> VALIDATE

    VALIDATE{"Validate each range"} -->|starts past EOF| DROP["Drop"]
    VALIDATE -->|ends past EOF| CLAMP["Clamp to duration"]
    VALIDATE -->|longer than 30 s| TRIM["Trim"]
    VALIDATE -->|valid| KEEP["Keep"]

    CLAMP --> RANK
    TRIM --> RANK
    KEEP --> RANK

    RANK["Sort by confidence,<br/>take top 4"] --> ORDER["Re-sort into<br/>playback order"]
    ORDER --> CUT["ffmpeg cuts each section"]
    CUT --> OUT(["Playable clips + descriptions"])

    DROP --> RANK

    style START fill:#143d29,stroke:#4ade80,color:#eee
    style OUT fill:#143d29,stroke:#4ade80,color:#eee
    style VALIDATE fill:#3d2914,stroke:#c9a227,color:#eee
    style SPLIT fill:#0f3460,stroke:#60a5fa,color:#eee
```

The validation branch exists because a model's sense of elapsed time drifts on
long footage. It once placed an event at 200 s that actually occurs at 414 s,
and the clip cut from that timestamp showed the wrong footage. Chunking removes
the cause; validation catches whatever survives.

## Library search: no model in the path

```mermaid
flowchart TD
    Q(["a red car on tuesday afternoon"]) --> EX["Extract constraint"]
    EX --> SPLIT2["text: 'a red car'<br/>filter: date + time of day"]

    SPLIT2 --> FILTER["Filter windows by<br/>camera and capture time"]
    FILTER --> EMPTY{"Any text<br/>left?"}

    EMPTY -->|no| TIME["Return matching footage<br/>ordered by time"]
    EMPTY -->|yes| SCORE["Score IDF-weighted<br/>token overlap"]

    SCORE --> NORM["Normalise by window length"]
    NORM --> TOP["Rank, take top k"]
    TOP --> RESULT(["Ranked windows"])
    TIME --> RESULT

    RESULT --> PLAY{"User plays<br/>a result?"}
    PLAY -->|yes| FETCH["Stream from source<br/>on demand"]
    PLAY -->|no| NOTHING["No media transferred"]

    style Q fill:#143d29,stroke:#4ade80,color:#eee
    style RESULT fill:#143d29,stroke:#4ade80,color:#eee
    style SCORE fill:#0f3460,stroke:#60a5fa,color:#eee
```

Time words are removed from the text before scoring. Leaving them in would have
the literal matcher rank a window for containing the word "afternoon".

## Provider selection

```mermaid
flowchart TD
    M(["Selected model"]) --> KIND{"Provider"}

    KIND -->|Gemini| GV["Upload video"]
    GV --> WAIT["Wait for ACTIVE state"]
    WAIT --> GCALL["Native video call"]

    KIND -->|OpenAI| SAMPLE["Sample 16 frames<br/>with timestamps"]
    SAMPLE --> OCALL["Image call<br/>strict json_schema"]

    KIND -->|Custom endpoint| CCALL["OpenAI-compatible call"]

    GCALL --> NORM2["Normalise to one shape"]
    OCALL --> NORM2
    CCALL --> NORM2
    NORM2 --> DONE(["Structured result"])

    style M fill:#143d29,stroke:#4ade80,color:#eee
    style DONE fill:#143d29,stroke:#4ade80,color:#eee
    style SAMPLE fill:#3d2914,stroke:#c9a227,color:#eee
```

The ACTIVE wait is not optional. An uploaded video is not immediately usable,
and calling too early fails with `FAILED_PRECONDITION` intermittently, which
looks like a flaky network rather than a race.

OpenAI models cannot accept video, so that path samples frames and reports
`frames_sampled` in the response rather than implying the model watched the
file.
