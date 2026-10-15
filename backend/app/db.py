"""Database sessions for the standalone DataBox API."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from databox.infrastructure.rows import Base


def database_url() -> str:
    external = os.environ.get("DATABASE_URL", "").strip()
    if external:
        if external.startswith("postgres://"):
            external = "postgresql://" + external[len("postgres://") :]
        if external.startswith("postgresql://"):
            external = "postgresql+asyncpg://" + external[len("postgresql://") :]
        return external
    user = os.environ.get("POSTGRES_USER", "databox")
    password = quote_plus(os.environ.get("POSTGRES_PASSWORD", "databox_local_password"))
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5434")
    name = os.environ.get("POSTGRES_DB", "databox")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


def sync_database_url() -> str:
    url = database_url().replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if os.environ.get("DATABASE_URL", "").strip() and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _engine_connect_args() -> dict:
    if not os.environ.get("DATABASE_URL", "").strip():
        return {}
    return {"ssl": True}


engine = create_async_engine(database_url(), pool_pre_ping=True, connect_args=_engine_connect_args())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


class SessionTransaction:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


__all__ = ["Base", "SessionLocal", "SessionTransaction", "database_url", "get_db_session", "sync_database_url"]
