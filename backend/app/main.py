"""DataBox API."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from app.auth_routes import bootstrap_owner, router as auth_router
from app.db import SessionLocal
from app.routes import router as databox_router
from app.security import auth_secret


def _refuse_unsafe_production() -> None:
    auth_secret()
    environment = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development")).strip().lower()
    if environment in {"production", "prod"} and os.environ.get("DATABOX_STORAGE", "local").strip().lower() == "local":
        raise RuntimeError("DATABOX_STORAGE=local is not allowed in production")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _refuse_unsafe_production()
    async with SessionLocal() as session:
        await bootstrap_owner(session)
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="DataBox", lifespan=_lifespan)
    application.include_router(auth_router)
    application.include_router(databox_router)
    return application


app = create_app()
