"""Session tokens and password hashes. Raw passwords and tokens are never logged."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from uuid import UUID

_DEV_AUTH_SECRET = "dev-only-databox-auth-secret-change-me"
_AUDIENCE = "databox-session"


def auth_secret() -> str:
    secret = os.environ.get("DATABOX_AUTH_SECRET", "").strip()
    environment = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development")).strip().lower()
    if environment in {"production", "prod"}:
        if len(secret) < 32 or secret == _DEV_AUTH_SECRET or secret.startswith("dev-only"):
            raise RuntimeError("DATABOX_AUTH_SECRET must be a unique secret of at least 32 characters in production")
        return secret
    return secret or _DEV_AUTH_SECRET


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"scrypt$16384$8$1${salt_b64}${digest_b64}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n_raw, r_raw, p_raw, salt_b64, digest_b64 = stored.split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_raw),
            r=int(r_raw),
            p=int(p_raw),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


@dataclass(frozen=True, slots=True)
class SessionClaims:
    user_id: UUID
    organization_id: UUID
    role: str


def issue_session_token(*, user_id: UUID, organization_id: UUID, role: str, ttl_seconds: int = 12 * 3600) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "org_id": str(organization_id),
        "role": role,
        "aud": _AUDIENCE,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing = f"{header}.{body}".encode("ascii")
    signature = _b64(hmac.new(auth_secret().encode("utf-8"), signing, hashlib.sha256).digest())
    return f"{header}.{body}.{signature}"


def read_session_token(token: str) -> SessionClaims:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("invalid token")
    signing = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected = _b64(hmac.new(auth_secret().encode("utf-8"), signing, hashlib.sha256).digest())
    if not hmac.compare_digest(expected, parts[2]):
        raise ValueError("invalid token")
    payload = json.loads(_b64_decode(parts[1]))
    if payload.get("aud") != _AUDIENCE or int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("invalid token")
    return SessionClaims(
        user_id=UUID(str(payload["sub"])),
        organization_id=UUID(str(payload["org_id"])),
        role=str(payload["role"]),
    )
