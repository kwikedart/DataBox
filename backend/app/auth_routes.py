"""Login for this project. It does not use MedRecs Firebase or Control Plane."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.security import hash_password, issue_session_token, verify_password
from databox.infrastructure.memory import MemoryRateLimiter
from databox.infrastructure.rows import MembershipRow, OrganizationRow, UserRow

router = APIRouter(prefix="/api/auth", tags=["auth"])

_DUMMY_HASH = hash_password("dummy-password-not-used")
_signup_limiter = MemoryRateLimiter()
_SIGNUP_LIMIT = 5
_SIGNUP_WINDOW_SECONDS = 3600


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=200)
    organization_name: str | None = Field(default=None, max_length=80)
    organization_id: UUID | None = None


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _email_is_valid(email: str) -> bool:
    if email.count("@") != 1 or any(char.isspace() for char in email):
        return False
    local, domain = email.split("@")
    return bool(local) and bool(domain) and "." not in local[:1]


def _session_payload(*, user_id, organization_id, role: str) -> dict:
    token = issue_session_token(user_id=user_id, organization_id=organization_id, role=role)
    return {
        "token": token,
        "userId": str(user_id),
        "organizationId": str(organization_id),
        "role": role,
    }


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db_session)) -> dict:
    email = _normalize_email(body.email)
    user = await db.scalar(select(UserRow).where(UserRow.email == email))
    stored = user.password_hash if user is not None else _DUMMY_HASH
    if user is None or not verify_password(body.password, stored):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    membership = await db.scalar(select(MembershipRow).where(MembershipRow.user_id == user.id))
    if membership is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _session_payload(
        user_id=user.id,
        organization_id=membership.organization_id,
        role=membership.role,
    )


@router.post("/signup", status_code=201)
async def signup(body: SignupRequest, request: Request, db: AsyncSession = Depends(get_db_session)) -> dict:
    """Create a member of the existing organization. The request cannot choose a role."""
    caller = request.client.host if request.client else "unknown"
    now = datetime.now(timezone.utc)
    if not _signup_limiter.allow(f"signup:{caller}", now, limit=_SIGNUP_LIMIT, window_seconds=_SIGNUP_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail="Too many accounts were created from this address. Try again later.")
    email = _normalize_email(body.email)
    if not _email_is_valid(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if body.organization_id is not None and body.organization_name:
        raise HTTPException(status_code=400, detail="Create a new organization or join one, not both")
    password_hash = hash_password(body.password)
    existing = await db.scalar(select(UserRow).where(UserRow.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    role = "member"
    if body.organization_id is not None:
        organization = await db.scalar(select(OrganizationRow).where(OrganizationRow.id == body.organization_id))
        if organization is None:
            raise HTTPException(status_code=400, detail="That organization was not found")
    else:
        name = (body.organization_name or "").strip()
        if not name or len(name) > 80:
            raise HTTPException(status_code=400, detail="Enter a name for the new organization")
        organization = OrganizationRow(id=uuid4(), name=name)
        db.add(organization)
        role = "owner"
        await db.flush()
    user = UserRow(id=uuid4(), email=email, password_hash=password_hash)
    db.add(user)
    await db.flush()
    db.add(MembershipRow(id=uuid4(), organization_id=organization.id, user_id=user.id, role=role))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with that email already exists") from None
    return _session_payload(user_id=user.id, organization_id=organization.id, role=role)


async def bootstrap_owner(db: AsyncSession) -> None:
    """Create the first owner only in development, and only when the user table is empty."""
    environment = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development")).strip().lower()
    if environment in {"production", "prod"}:
        if os.environ.get("DATABOX_BOOTSTRAP_PASSWORD"):
            raise RuntimeError("DATABOX_BOOTSTRAP_PASSWORD must not be set in production")
        return
    email = _normalize_email(os.environ.get("DATABOX_BOOTSTRAP_EMAIL", ""))
    password = os.environ.get("DATABOX_BOOTSTRAP_PASSWORD", "")
    if not email or not password:
        return
    if len(password) < 12:
        raise RuntimeError("DATABOX_BOOTSTRAP_PASSWORD must be at least 12 characters")
    count = await db.scalar(select(func.count()).select_from(UserRow))
    if count:
        return
    organization = OrganizationRow(id=uuid4(), name="Local")
    user = UserRow(id=uuid4(), email=email, password_hash=hash_password(password))
    db.add(organization)
    db.add(user)
    # Models have no relationship(), so the unit of work orders inserts by class
    # name and would write the membership before its parent rows.
    await db.flush()
    db.add(MembershipRow(id=uuid4(), organization_id=organization.id, user_id=user.id, role="owner"))
    await db.commit()
