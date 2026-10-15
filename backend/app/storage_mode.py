"""Choose where document bytes are stored. Production refuses the development folder."""

from __future__ import annotations

import os
from pathlib import Path


def production() -> bool:
    environment = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development")).strip().lower()
    return environment in {"production", "prod"}


def storage_mode() -> str:
    return os.environ.get("DATABOX_STORAGE", "local").strip().lower()


def local_storage_root() -> Path:
    """Return the directory for local or single-server volume storage."""
    mode = storage_mode()
    if production() and mode == "local":
        raise RuntimeError("DATABOX_STORAGE=local is not allowed in production")
    if mode == "volume":
        raw = os.environ.get("DATABOX_LOCAL_DIR", "/var/lib/databox/objects").strip()
        path = Path(raw)
        if not path.is_absolute() or not str(path).startswith("/var/lib/databox/"):
            raise RuntimeError("DATABOX_STORAGE=volume requires DATABOX_LOCAL_DIR under /var/lib/databox/")
        return path
    root = os.environ.get("DATABOX_LOCAL_DIR", "data/objects")
    return Path(__file__).resolve().parents[1] / root
