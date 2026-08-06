"""Google Drive folder connector.

Deliberately uses an API key against a link-shared folder rather than OAuth.
OAuth needs a consent screen, a redirect URI, and a token exchange, none of
which is worth doing live; an API key reaches any folder set to "anyone with
the link", which is all a shared video library needs.

Only listing and fetching are implemented. Nothing is written back to Drive.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quick/drive", tags=["quick"])

_FOLDER_PATTERNS = (
    re.compile(r"/folders/([A-Za-z0-9_-]{10,})"),
    re.compile(r"[?&]id=([A-Za-z0-9_-]{10,})"),
)

VIDEO_MIME_PREFIX = "video/"


def parse_folder_id(value: str) -> str:
    """Accept either a raw folder id or any Drive folder URL."""

    text = (value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Enter a Drive folder link or id.")
    for pattern in _FOLDER_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", text):
        return text
    raise HTTPException(
        status_code=400,
        detail="That does not look like a Drive folder link or id.",
    )


def _api_key(supplied: str | None) -> str:
    key = (
        (supplied or "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
    )
    if not key:
        raise HTTPException(
            status_code=400,
            detail="No Google API key available for Drive access.",
        )
    return key


def _get(url: str, timeout: int = 60) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        detail = body[:200]
        try:
            parsed = json.loads(body)
            detail = parsed.get("error", {}).get("message", detail)
        except json.JSONDecodeError:
            pass
        if exc.code in {403, 404}:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Drive refused the request ({exc.code}): {detail}. Check the "
                    "folder is shared with 'anyone with the link' and that the "
                    "Drive API is enabled for this key."
                ),
            ) from exc
        raise HTTPException(status_code=502, detail=f"Drive error {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Drive: {exc}") from exc


@router.post("/list")
def list_drive_videos(
    folder: str = Form(...),
    api_key: str | None = Form(None),
) -> dict[str, object]:
    """List the video files in a link-shared Drive folder."""

    folder_id = parse_folder_id(folder)
    key = _api_key(api_key)

    query = urllib.parse.urlencode(
        {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "files(id,name,mimeType,size,videoMediaMetadata/durationMillis)",
            "pageSize": "100",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "key": key,
        }
    )
    payload = json.loads(_get(f"https://www.googleapis.com/drive/v3/files?{query}"))

    files = []
    for item in payload.get("files", []):
        if not str(item.get("mimeType", "")).startswith(VIDEO_MIME_PREFIX):
            continue
        millis = (item.get("videoMediaMetadata") or {}).get("durationMillis")
        files.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "mime_type": item.get("mimeType"),
                "size_bytes": int(item["size"]) if str(item.get("size", "")).isdigit() else None,
                "duration_seconds": round(int(millis) / 1000, 1) if millis else None,
            }
        )

    return {"folder_id": folder_id, "count": len(files), "files": files}


def fetch_drive_file(file_id: str, destination: Path, api_key: str) -> None:
    """Download one Drive file to disk."""

    query = urllib.parse.urlencode({"alt": "media", "key": api_key, "supportsAllDrives": "true"})
    url = f"https://www.googleapis.com/drive/v3/files/{urllib.parse.quote(file_id)}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=600) as response, destination.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Drive would not return that file ({exc.code}).",
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=f"Could not download from Drive: {exc}") from exc
