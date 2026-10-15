"""Celery application for the DataBox render queue."""

from __future__ import annotations

import os

from celery import Celery

celery_app = Celery(
    "databox",
    broker=os.environ.get("DATABOX_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6380/0",
    backend=os.environ.get("DATABOX_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6380/0",
)
celery_app.conf.task_default_queue = "databox_render"
