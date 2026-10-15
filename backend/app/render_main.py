"""Dedicated PDF render worker. The API process does not import this module."""

from __future__ import annotations

import hmac
import os
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request

from app.worker import _render

app = FastAPI(title="DataBox Render Worker")


def _production() -> bool:
    environment = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development")).strip().lower()
    return environment in {"production", "prod"}


@app.on_event("startup")
def _refuse_open_worker() -> None:
    secret = os.environ.get("DATABOX_TASK_SECRET", "").strip()
    audience = os.environ.get("DATABOX_TASK_OIDC_AUDIENCE", "").strip()
    if _production() and not secret and not audience:
        raise RuntimeError("The render worker requires DATABOX_TASK_SECRET or DATABOX_TASK_OIDC_AUDIENCE in production")
    if os.environ.get("DATABOX_STORAGE", "local").strip().lower() == "local" and _production():
        raise RuntimeError("DATABOX_STORAGE=local is not allowed in production")


def _secret_matches(request: Request) -> bool:
    secret = os.environ.get("DATABOX_TASK_SECRET", "").strip()
    presented = request.headers.get("x-databox-task-secret", "")
    if not secret or not presented:
        return False
    return hmac.compare_digest(presented, secret)


def _oidc_matches(request: Request) -> bool:
    audience = os.environ.get("DATABOX_TASK_OIDC_AUDIENCE", "").strip()
    header = request.headers.get("authorization", "")
    if not audience or not header.startswith("Bearer "):
        return False
    token = header.removeprefix("Bearer ").strip()
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        id_token.verify_oauth2_token(token, google_requests.Request(), audience)
    except Exception:
        return False
    return True


@app.post("/internal/tasks/render")
async def render_task(request: Request) -> dict:
    if not _secret_matches(request) and not _oidc_matches(request):
        raise HTTPException(status_code=401, detail="Render task was not authorized")
    try:
        body = await request.json()
        organization_id = str(UUID(str(body["organization_id"])))
        document_id = str(UUID(str(body["document_id"])))
        version_id = str(UUID(str(body["version_id"])))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Render task is invalid") from None
    return await _render(organization_id, document_id, version_id)
