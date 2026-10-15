"""Share-token HMAC and view-token signatures. Stdlib only."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from databox.domain.exceptions import ValidationError

from databox.domain.entities import ViewClaims

_AUD = "databox-view"


def generate_share_token() -> str:
    return secrets.token_urlsafe(32)


def hash_share_token(token: str, pepper: str) -> str:
    if not pepper:
        raise ValidationError("Share token pepper is not configured")
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def share_token_matches(token: str, pepper: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_share_token(token, pepper), token_hash)


def seal_share_token(token: str, pepper: str, share_id: UUID) -> str:
    """Encrypt a share token so a manager can display it again. The lookup still uses the hash."""
    if not pepper:
        raise ValidationError("Share token pepper is not configured")
    raw = token.encode("utf-8")
    stream = _keystream(pepper, share_id, len(raw))
    return _b64(bytes(byte ^ stream[index] for index, byte in enumerate(raw)))


def open_share_token(sealed: str, pepper: str, share_id: UUID) -> str:
    if not pepper or not sealed:
        raise ValidationError("Share token pepper is not configured")
    raw = _b64_decode(sealed)
    stream = _keystream(pepper, share_id, len(raw))
    try:
        return bytes(byte ^ stream[index] for index, byte in enumerate(raw)).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("Share link is not available") from exc


def _keystream(pepper: str, share_id: UUID, length: int) -> bytes:
    stream = b""
    counter = 0
    while len(stream) < length:
        stream += hmac.new(
            pepper.encode("utf-8"),
            str(share_id).encode("utf-8") + counter.to_bytes(4, "big"),
            hashlib.sha256,
        ).digest()
        counter += 1
    return stream[:length]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_view_token(claims: ViewClaims, *, secret: str) -> str:
    if not secret:
        raise ValidationError("View token secret is not configured")
    payload: dict[str, Any] = {
        "sub": claims.subject,
        "org_id": str(claims.organization_id),
        "doc_id": str(claims.document_id),
        "ver_id": str(claims.version_id),
        "scope": sorted(claims.scope),
        "policy_epoch": claims.policy_epoch,
        "root_doc_id": str(claims.root_document_id),
        "current_depth": claims.current_depth,
        "remaining_depth": claims.remaining_depth,
        "page_count": claims.page_count,
        "iat": claims.issued_at,
        "exp": claims.expires_at,
        "aud": _AUD,
    }
    if claims.render_generation > 0:
        payload["render_generation"] = claims.render_generation
    if claims.share_link_id is not None:
        payload["share_link_id"] = str(claims.share_link_id)
    if claims.share_epoch is not None:
        payload["share_epoch"] = claims.share_epoch
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(secret.encode("utf-8"), f"{header}.{body}".encode("ascii"), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(signature)}"


def read_view_token(token: str, *, secret: str, now: datetime) -> ViewClaims:
    if not secret:
        raise ValidationError("View token secret is not configured")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValidationError("Access token is not valid")
    header, body, signature = parts
    expected = hmac.new(secret.encode("utf-8"), f"{header}.{body}".encode("ascii"), hashlib.sha256).digest()
    try:
        presented = _b64_decode(signature)
    except (ValueError, TypeError) as exc:
        raise ValidationError("Access token is not valid") from exc
    if not hmac.compare_digest(expected, presented):
        raise ValidationError("Access token is not valid")
    try:
        payload = json.loads(_b64_decode(body))
        header_data = json.loads(_b64_decode(header))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValidationError("Access token is not valid") from exc
    if header_data.get("alg") != "HS256" or payload.get("aud") != _AUD:
        raise ValidationError("Access token is not valid")
    expires_at = int(payload.get("exp") or 0)
    issued_at = int(payload.get("iat") or 0)
    current = int(now.astimezone(timezone.utc).timestamp())
    if issued_at <= 0 or expires_at <= issued_at or expires_at <= current:
        raise ValidationError("Access token is not valid")
    if expires_at - issued_at > 30 * 60:
        raise ValidationError("Access token is not valid")
    try:
        page_count = int(payload["page_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("Access token is not valid") from exc
    if page_count < 0:
        raise ValidationError("Access token is not valid")
    scope = frozenset(str(item) for item in payload.get("scope") or [])
    share_raw = payload.get("share_link_id")
    share_epoch = payload.get("share_epoch")
    return ViewClaims(
        subject=str(payload.get("sub") or ""),
        organization_id=UUID(str(payload["org_id"])),
        document_id=UUID(str(payload["doc_id"])),
        version_id=UUID(str(payload["ver_id"])),
        scope=scope,
        policy_epoch=int(payload["policy_epoch"]),
        root_document_id=UUID(str(payload["root_doc_id"])),
        current_depth=int(payload["current_depth"]),
        remaining_depth=int(payload["remaining_depth"]),
        expires_at=expires_at,
        page_count=page_count,
        issued_at=issued_at,
        render_generation=int(payload.get("render_generation") or 0),
        share_link_id=UUID(str(share_raw)) if share_raw else None,
        share_epoch=int(share_epoch) if share_epoch is not None else None,
    )
