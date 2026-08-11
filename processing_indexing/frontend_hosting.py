"""Serve the compiled Aperture SPA from the API process on Cloud Run."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def frontend_dist_dir() -> Path:
    configured = os.environ.get("FRONTEND_DIST_DIR", "").strip()
    if configured:
        return Path(configured).resolve()
    return (Path(__file__).resolve().parents[1] / "video_search_frontend" / "dist").resolve()


def install_frontend(app: FastAPI, dist_dir: Path | None = None) -> bool:
    """Install static and SPA-fallback routes after every API route is registered."""

    dist = (dist_dir or frontend_dist_dir()).resolve()
    index = dist / "index.html"
    if not index.is_file():
        return False

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        requested = (dist / full_path).resolve()
        if requested != dist and dist in requested.parents and requested.is_file():
            return FileResponse(requested)
        return FileResponse(index)

    return True
