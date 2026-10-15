"""Compose DataBox for one request."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionTransaction, get_db_session
from app.security import read_session_token
from databox.application.service import DataboxApplication
from databox.domain.identity import OrganizationRole, TenantIdentity
from databox.infrastructure.gcs import GcsDataboxStorage
from databox.infrastructure.local_files import LocalFileStorage
from databox.infrastructure.memory import (
    MemoryDocumentLock,
    MemoryEpochCache,
    MemoryFanout,
    MemoryRateLimiter,
    MemoryTicketStore,
)
from databox.infrastructure.render_queue import build_render_queue
from databox.infrastructure.rows import MembershipRow
from databox.infrastructure.sqlalchemy_store import SqlAlchemyDataboxStore
from databox.settings import load_databox_settings

_runtime: dict | None = None


def _runtime_state() -> dict:
    global _runtime
    if _runtime is None:
        redis_url = os.environ.get("DATABOX_REDIS_URL") or os.environ.get("REDIS_URL")
        if redis_url:
            from databox.infrastructure.redis_support import (
                RedisDocumentLock,
                RedisEpochCache,
                RedisFanout,
                RedisTicketStore,
            )

            epochs = RedisEpochCache(redis_url)
            locks = RedisDocumentLock(redis_url)
            tickets = RedisTicketStore(redis_url)
            fanout = RedisFanout(redis_url)
        else:
            epochs = MemoryEpochCache()
            locks = MemoryDocumentLock()
            tickets = MemoryTicketStore()
            fanout = MemoryFanout()
        _runtime = {
            "epochs": epochs,
            "locks": locks,
            "tickets": tickets,
            "fanout": fanout,
            "rate": MemoryRateLimiter(),
        }
    return _runtime


class _Clock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def _storage(settings):
    mode = os.environ.get("DATABOX_STORAGE", "local").strip().lower()
    environment = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development")).strip().lower()
    if environment in {"production", "prod"} and mode == "local":
        raise RuntimeError("DATABOX_STORAGE=local is not allowed in production")
    if mode == "gcs":
        return GcsDataboxStorage(settings.bucket_name)
    root = os.environ.get("DATABOX_LOCAL_DIR", "data/objects")
    return LocalFileStorage(Path(__file__).resolve().parents[1] / root)


def get_databox_application(db: AsyncSession = Depends(get_db_session)) -> DataboxApplication:
    runtime = _runtime_state()
    settings = load_databox_settings()
    return DataboxApplication(
        store=SqlAlchemyDataboxStore(db),
        storage=_storage(settings),
        epochs=runtime["epochs"],
        clock=_Clock(),
        settings=settings,
        render_queue=build_render_queue(),
        transaction=SessionTransaction(db),
        rate_limiter=runtime["rate"],
        locks=runtime["locks"],
        tickets=runtime["tickets"],
        fanout=runtime["fanout"],
    )


async def get_actor(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> TenantIdentity:
    header = request.headers.get("authorization") or ""
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication failed")
    try:
        claims = read_session_token(header.removeprefix("Bearer ").strip())
    except (ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Authentication failed") from None
    membership = await db.scalar(
        select(MembershipRow).where(
            MembershipRow.organization_id == claims.organization_id,
            MembershipRow.user_id == claims.user_id,
        )
    )
    if membership is None or membership.role not in {"owner", "admin", "member", "viewer"}:
        raise HTTPException(status_code=401, detail="Authentication failed")
    return TenantIdentity(
        user_id=membership.user_id,
        organization_id=membership.organization_id,
        role=OrganizationRole(membership.role),
    )


async def get_optional_actor(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> TenantIdentity | None:
    header = request.headers.get("authorization") or ""
    if not header.startswith("Bearer "):
        return None
    return await get_actor(request, db)
