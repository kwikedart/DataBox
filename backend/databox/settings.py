"""Runtime limits for DataBox. Secrets come from the environment, not source control."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DataboxSettings:
    token_pepper: str
    view_token_secret: str
    max_upload_bytes: int = 50 * 1024 * 1024
    max_pages: int = 500
    share_min_ttl_seconds: int = 300
    share_max_ttl_seconds: int = 7 * 24 * 3600
    view_token_ttl_seconds: int = 15 * 60
    allow_guest_edit: bool = False
    orphan_grace_seconds: int = 3600
    deletion_retention_seconds: int = 7 * 24 * 3600
    max_cascade_depth: int = 3
    collaboration_update_max_bytes: int = 256 * 1024
    snapshot_every_updates: int = 50
    share_resolve_limit: int = 30
    upload_limit: int = 20
    rate_window_seconds: int = 60
    bucket_name: str = "databox-private"


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    return int(raw)


def load_databox_settings() -> DataboxSettings:
    pepper = os.environ.get("DATABOX_TOKEN_PEPPER", "").strip()
    secret = os.environ.get("DATABOX_VIEW_TOKEN_SECRET", "").strip()
    environment = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development")).strip().lower()
    if environment in {"production", "prod"} and (not pepper or not secret):
        raise RuntimeError("DATABOX_TOKEN_PEPPER and DATABOX_VIEW_TOKEN_SECRET are required in production")
    if not pepper:
        pepper = "dev-databox-pepper"
    if not secret:
        secret = "dev-databox-view-secret"
    bucket = os.environ.get("DATABOX_GCS_BUCKET") or os.environ.get("GCS_BUCKET_NAME") or "databox-private"
    return DataboxSettings(
        token_pepper=pepper,
        view_token_secret=secret,
        max_upload_bytes=_int("DATABOX_MAX_UPLOAD_BYTES", 50 * 1024 * 1024),
        max_pages=_int("DATABOX_MAX_PAGES", 500),
        share_min_ttl_seconds=_int("DATABOX_SHARE_MIN_TTL_SECONDS", 300),
        share_max_ttl_seconds=_int("DATABOX_SHARE_MAX_TTL_SECONDS", 7 * 24 * 3600),
        view_token_ttl_seconds=min(_int("DATABOX_VIEW_TOKEN_TTL_SECONDS", 15 * 60), 30 * 60),
        allow_guest_edit=_flag("DATABOX_ALLOW_GUEST_EDIT"),
        bucket_name=bucket,
    )
