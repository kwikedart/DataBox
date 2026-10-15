"""Render queue adapters. The API enqueues work and never rasterizes PDFs."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from uuid import UUID

logger = logging.getLogger("databox.render")


class HttpRenderQueue:
    """Development adapter. Posts the same JSON body Cloud Tasks would deliver."""

    def __init__(self, url: str, secret: str) -> None:
        self._url = url
        self._secret = secret

    def enqueue(self, *, organization_id: UUID, document_id: UUID, version_id: UUID) -> None:
        if not self._url or not self._secret:
            logger.warning("render_enqueue_skipped document_id=%s", document_id)
            return
        body = json.dumps(
            {
                "organization_id": str(organization_id),
                "document_id": str(document_id),
                "version_id": str(version_id),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self._url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Databox-Task-Secret": self._secret,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status >= 300:
                    logger.warning("render_enqueue_failed document_id=%s status=%s", document_id, response.status)
        except urllib.error.URLError:
            logger.warning("render_enqueue_failed document_id=%s", document_id)


class CloudTasksRenderQueue:
    """Production adapter. Cloud Tasks calls the render worker with an OIDC token."""

    def __init__(self) -> None:
        self._project = os.environ.get("DATABOX_GCP_PROJECT", "").strip()
        self._location = os.environ.get("DATABOX_TASKS_LOCATION", "").strip()
        self._queue = os.environ.get("DATABOX_TASKS_QUEUE", "").strip()
        self._url = os.environ.get("DATABOX_RENDER_URL", "").strip()
        self._service_account = os.environ.get("DATABOX_TASK_OIDC_SERVICE_ACCOUNT", "").strip()
        self._audience = os.environ.get("DATABOX_TASK_OIDC_AUDIENCE", "").strip() or self._url

    def enqueue(self, *, organization_id: UUID, document_id: UUID, version_id: UUID) -> None:
        if not all([self._project, self._location, self._queue, self._url, self._service_account]):
            logger.warning("render_enqueue_skipped document_id=%s", document_id)
            return
        from google.cloud import tasks_v2

        client = tasks_v2.CloudTasksClient()
        parent = client.queue_path(self._project, self._location, self._queue)
        payload = json.dumps(
            {
                "organization_id": str(organization_id),
                "document_id": str(document_id),
                "version_id": str(version_id),
            }
        ).encode("utf-8")
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": self._url,
                "headers": {"Content-Type": "application/json"},
                "body": payload,
                "oidc_token": {
                    "service_account_email": self._service_account,
                    "audience": self._audience,
                },
            }
        }
        try:
            client.create_task(request={"parent": parent, "task": task})
        except Exception:
            logger.warning("render_enqueue_failed document_id=%s", document_id)


def build_render_queue():
    mode = os.environ.get("DATABOX_RENDER_QUEUE", "http").strip().lower()
    if mode == "cloudtasks":
        return CloudTasksRenderQueue()
    if mode == "celery":
        from databox.infrastructure.celery_queue import CeleryRenderQueue

        return CeleryRenderQueue()
    return HttpRenderQueue(
        os.environ.get("DATABOX_RENDER_URL", "http://127.0.0.1:8091/internal/tasks/render"),
        os.environ.get("DATABOX_TASK_SECRET", ""),
    )
