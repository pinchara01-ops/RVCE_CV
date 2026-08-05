"""Helpers for using a populated Hugging Face cache without network checks."""

from __future__ import annotations

import os
from pathlib import Path


def model_load_kwargs(model_name: str) -> dict[str, bool]:
    """Prefer the local snapshot when the configured cache has this model.

    ``from_pretrained`` normally checks the Hub even when all model files are
    already present. On an offline or restricted network that can turn a
    cached model load into a long retry. If the cache contains the revision
    selected by ``refs/main`` we can load it deterministically. Missing models
    keep the default behaviour, including a first-run download.
    """
    cache_root = os.environ.get("HF_HOME")
    if not cache_root:
        return {}

    repository = Path(cache_root) / "hub" / f"models--{model_name.replace('/', '--')}"
    reference = repository / "refs" / "main"
    try:
        revision = reference.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    if revision and (repository / "snapshots" / revision).is_dir():
        return {"local_files_only": True}
    return {}
