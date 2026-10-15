"""Login for this project. It does not use MedRecs Firebase or Control Plane."""

from __future__ import annotations

import os
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.security import hash_password, issue_session_token, verify_password
from databox.infrastructure.rows import MembershipRow, OrganizationRow, UserRow

router = APIRouter(prefix="/api/auth", tags=["auth"])

_DUMMY_HASH = hash_password("dummy-password-not-used")


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


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
    token = issue_session_token(
        user_id=user.id,
        organization_id=membership.organization_id,
        role=membership.role,
    )
    return {
        "token": token,
        "userId": str(user.id),
        "organizationId": str(membership.organization_id),
        "role": membership.role,
    }


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
