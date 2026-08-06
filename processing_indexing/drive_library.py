"""Drive-backed library: index once, keep only text, search without the model.

The flow is deliberately asymmetric.

Indexing is expensive and happens once per video: download it from Drive, send
it to the model, keep the returned windows, then delete the local copy. What
survives is text plus a Drive file id, so a library of hundreds of videos costs
kilobytes on disk rather than gigabytes.

Searching is cheap and happens constantly, so it never calls a model at all. It
scores the query against the stored window text with IDF-weighted token overlap,
which returns in milliseconds. The video itself is only fetched when the user
actually plays a result.
"""

from __future__ import annotations

import logging
import math
import re
import shutil
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import StreamingResponse

from .drive_connector import fetch_drive_file, list_drive_videos, parse_folder_id, _api_key
from .quick_demo import _CLIP_ROOT, _probe_duration, _resolve_api_key, DEFAULT_MODEL
from .quick_index import index_video_file
from .nvr_metadata import extract_time_filter, matches_constraint, parse_filename

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quick/library", tags=["quick"])

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens. Unicode-aware so Indic scripts are not dropped."""

    return [token.lower() for token in _TOKEN.findall(text or "")]


@dataclass
class IndexedWindow:
    video_id: str
    video_name: str
    window_id: str
    start: float
    end: float
    caption: str
    transcript: str
    objects: list[str]
    actions: list[str]
    audio_events: list[str]
    search_terms: list[str] = field(default_factory=list)
    camera: str | None = None
    recorded_at: datetime | None = None
    tokens: Counter = field(default_factory=Counter)

    def searchable_text(self) -> str:
        return " ".join(
            [
                self.caption,
                self.transcript,
                " ".join(self.objects),
                " ".join(self.actions),
                " ".join(self.audio_events),
                # Synonyms produced at index time: the whole reason a literal
                # matcher can answer a loosely worded query.
                " ".join(self.search_terms),
            ]
        )

    def public(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "video_name": self.video_name,
            "window_id": self.window_id,
            "start": self.start,
            "end": self.end,
            "caption": self.caption,
            "transcript": self.transcript,
            "objects": self.objects,
            "actions": self.actions,
            "audio_events": self.audio_events,
            "search_terms": self.search_terms,
            "camera": self.camera,
            # Absolute wall-clock time of this window, not just an offset: the
            # thing an operator actually asks for.
            "recorded_at": (
                (self.recorded_at + timedelta(seconds=self.start)).isoformat()
                if self.recorded_at
                else None
            ),
        }


class Library:
    """In-memory index. Cleared on restart, which is fine for a demo."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.windows: list[IndexedWindow] = []
        self.videos: dict[str, dict[str, Any]] = {}

    def add(self, video: dict[str, Any], windows: list[IndexedWindow]) -> None:
        with self._lock:
            # Re-indexing a video replaces its windows rather than duplicating.
            self.windows = [w for w in self.windows if w.video_id != video["id"]]
            self.windows.extend(windows)
            self.videos[video["id"]] = video

    def document_frequency(self) -> Counter:
        frequency: Counter = Counter()
        for window in self.windows:
            frequency.update(set(window.tokens))
        return frequency

    def clear(self) -> None:
        with self._lock:
            self.windows = []
            self.videos = {}


LIBRARY = Library()


def _score(query_tokens: list[str], window: IndexedWindow, idf: dict[str, float]) -> float:
    """IDF-weighted overlap, length-normalised.

    Rare words carry more weight than common ones, and a long window does not
    outrank a precise short one purely by having more text to match against.
    """

    if not query_tokens or not window.tokens:
        return 0.0
    total = sum(window.tokens.values()) or 1
    score = 0.0
    for token in set(query_tokens):
        count = window.tokens.get(token, 0)
        if count:
            # Sub-linear term frequency: a fifth repeat adds little.
            score += idf.get(token, 0.0) * (1 + math.log(count))
    return score / math.sqrt(total)


@router.post("/index-drive")
async def index_drive_folder(
    folder: str = Form(...),
    api_key: str | None = Form(None),
    model: str | None = Form(None),
    max_videos: int = Form(10),
) -> dict[str, Any]:
    """Download, index, and discard each video in a Drive folder in turn."""

    folder_id = parse_folder_id(folder)
    drive_key = _api_key(api_key)
    resolved_model = (model or "").strip() or DEFAULT_MODEL
    model_key = _resolve_api_key(None, resolved_model)

    listing = list_drive_videos(folder=folder_id, api_key=drive_key)
    files = listing["files"][: max(1, min(int(max_videos), 50))]
    if not files:
        raise HTTPException(status_code=400, detail="No videos found in that folder.")

    workspace = _CLIP_ROOT / f"drive_{uuid.uuid4().hex}"
    workspace.mkdir(parents=True, exist_ok=True)

    indexed: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    try:
        for item in files:
            local = workspace / f"{item['id']}.mp4"
            try:
                # One at a time: never hold more than a single video on disk.
                fetch_drive_file(item["id"], local, drive_key)
                duration = _probe_duration(local)
                meta = parse_filename(item["name"])
                result = index_video_file(
                    source=local,
                    duration=duration,
                    api_key=model_key,
                    model=resolved_model,
                    language="",
                    workspace=workspace,
                )
                windows = [
                    IndexedWindow(
                        video_id=item["id"],
                        video_name=item["name"],
                        window_id=window["window_id"],
                        start=window["start"],
                        end=window["end"],
                        caption=window["caption"],
                        transcript=window["transcript"],
                        objects=window["objects"],
                        actions=window["actions"],
                        audio_events=window["audio_events"],
                        search_terms=window.get("search_terms", []),
                        camera=meta.camera,
                        recorded_at=meta.recorded_at,
                    )
                    for window in result["windows"]
                ]
                for window in windows:
                    window.tokens = Counter(tokenize(window.searchable_text()))

                LIBRARY.add(
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "duration_seconds": duration,
                        "window_count": len(windows),
                        **meta.public(),
                    },
                    windows,
                )
                indexed.append(
                    {"id": item["id"], "name": item["name"], "windows": len(windows)}
                )
            except HTTPException as exc:
                failures.append({"name": item["name"], "error": str(exc.detail)[:160]})
            except Exception as exc:  # noqa: BLE001 - one bad video must not stop the run
                logger.warning("indexing %s failed: %s", item["name"], exc)
                failures.append({"name": item["name"], "error": str(exc)[:160]})
            finally:
                # Discard the download immediately; only text is kept.
                local.unlink(missing_ok=True)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    return {
        "folder_id": folder_id,
        "indexed": indexed,
        "failed": failures,
        "total_windows": len(LIBRARY.windows),
        "total_videos": len(LIBRARY.videos),
        "model": resolved_model,
    }


@router.post("/search")
def search_library(query: str = Form(...), top_k: int = Form(8)) -> dict[str, Any]:
    """Rank stored windows against the query. No model call, no video access."""

    text = (query or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Enter something to search for.")
    if not LIBRARY.windows:
        return {"query": text, "results": [], "searched_windows": 0, "note": "library is empty"}

    # Pull "tuesday afternoon" / "CAM02" out before scoring, so the literal
    # matcher never scores a window for containing the word "afternoon".
    text, constraint = extract_time_filter(text, datetime.now())
    candidates = [
        window
        for window in LIBRARY.windows
        if matches_constraint(window.recorded_at, window.camera, constraint)
    ]
    if not text.strip():
        # Time or camera alone is a valid query: return that footage in order.
        ordered = sorted(candidates, key=lambda w: (w.recorded_at or datetime.min, w.start))
        results = []
        for window in ordered[: max(1, min(int(top_k), 50))]:
            payload = window.public()
            payload["score"] = 1.0
            payload["relative"] = 1.0
            payload["media_url"] = f"/api/quick/library/media/{window.video_id}"
            results.append(payload)
        return {
            "query": query,
            "filter": constraint,
            "results": results,
            "searched_windows": len(LIBRARY.windows),
            "matched_windows": len(candidates),
        }

    query_tokens = tokenize(text)
    frequency = LIBRARY.document_frequency()
    total = len(LIBRARY.windows) or 1
    idf = {
        token: math.log(1 + total / (1 + frequency.get(token, 0)))
        for token in set(query_tokens)
    }

    scored = [(_score(query_tokens, window, idf), window) for window in candidates]
    scored = [pair for pair in scored if pair[0] > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    best = scored[0][0] if scored else 1.0
    results = []
    for score, window in scored[: max(1, min(int(top_k), 50))]:
        payload = window.public()
        payload["score"] = round(score, 5)
        # Relative to the top hit, so the bar reads as ranking not probability.
        payload["relative"] = round(score / best, 3) if best else 0.0
        payload["media_url"] = f"/api/quick/library/media/{window.video_id}"
        results.append(payload)

    return {
        "query": query,
        "effective_query": text,
        "filter": constraint,
        "results": results,
        "searched_windows": len(LIBRARY.windows),
        "matched_windows": len(scored),
    }


@router.get("/videos")
def list_library() -> dict[str, Any]:
    return {
        "videos": list(LIBRARY.videos.values()),
        "total_windows": len(LIBRARY.windows),
    }


@router.post("/clear")
def clear_library() -> dict[str, Any]:
    LIBRARY.clear()
    return {"cleared": True}


@router.get("/media/{video_id}")
def library_media(video_id: str) -> StreamingResponse:
    """Stream one indexed video from Drive on demand.

    Nothing is cached locally: the file was deleted after indexing, so playback
    fetches it fresh. Only videos in the library are reachable, so this cannot
    be used to proxy arbitrary Drive ids.
    """

    if video_id not in LIBRARY.videos:
        raise HTTPException(status_code=404, detail="Not in the library.")

    key = _api_key(None)
    query = urllib.parse.urlencode(
        {"alt": "media", "key": key, "supportsAllDrives": "true"}
    )
    url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(video_id)}?{query}"

    try:
        upstream = urllib.request.urlopen(url, timeout=600)
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Drive refused playback ({exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Drive: {exc}") from exc

    def chunks():
        try:
            while True:
                block = upstream.read(262_144)
                if not block:
                    break
                yield block
        finally:
            upstream.close()

    return StreamingResponse(chunks(), media_type="video/mp4")
