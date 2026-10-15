"""Rasterize PDFs outside the API process."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from app.celery_app import celery_app
from app.db import SessionLocal, SessionTransaction, engine

logger = logging.getLogger("databox.render")


async def _render(organization_id: str, document_id: str, version_id: str) -> dict:
    from databox.infrastructure.gcs import GcsDataboxStorage
    from databox.infrastructure.local_files import LocalFileStorage
    from databox.infrastructure.render_job import render_stored_version
    from databox.infrastructure.sqlalchemy_store import SqlAlchemyDataboxStore
    from databox.settings import load_databox_settings

    settings = load_databox_settings()
    mode = os.environ.get("DATABOX_STORAGE", "local").strip().lower()
    if mode == "gcs":
        storage = GcsDataboxStorage(settings.bucket_name)
    else:
        root = os.environ.get("DATABOX_LOCAL_DIR", "data/objects")
        storage = LocalFileStorage(Path(__file__).resolve().parents[1] / root)
    try:
        async with SessionLocal() as session:
            count = await render_stored_version(
                store=SqlAlchemyDataboxStore(session),
                storage=storage,
                organization_id=UUID(organization_id),
                document_id=UUID(document_id),
                version_id=UUID(version_id),
                max_pages=settings.max_pages,
            )
            await SessionTransaction(session).commit()
        return {"pages": count}
    finally:
        await engine.dispose()


@celery_app.task(name="databox.render_version")
def render_version(organization_id: str, document_id: str, version_id: str) -> dict:
    try:
        return asyncio.run(_render(organization_id, document_id, version_id))
    except Exception:
        logger.exception("databox_render_failed document_id=%s version_id=%s", document_id, version_id)
        return {"pages": 0, "status": "failed"}
