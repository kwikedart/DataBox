"""Enqueue PDF rendering on an isolated Celery queue. The API process does not rasterize."""

from __future__ import annotations

from uuid import UUID


class CeleryRenderQueue:
    def enqueue(self, *, organization_id: UUID, document_id: UUID, version_id: UUID) -> None:
        from app.celery_app import celery_app

        celery_app.send_task(
            "databox.render_version",
            args=[str(organization_id), str(document_id), str(version_id)],
            queue="databox_render",
        )
