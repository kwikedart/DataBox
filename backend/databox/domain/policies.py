"""Authorization, share, version, and cleanup rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from databox.domain.exceptions import ConflictError, NotFoundError, ValidationError
from databox.domain.identity import OrganizationRole

from databox.domain.entities import Document, ShareLink, UploadOperation

OWNER_ACTIONS = frozenset(
    {"read", "download", "annotate", "edit", "upload", "manage_shares", "restore_version", "delete"}
)
EDITOR_ACTIONS = frozenset({"read", "download", "annotate", "edit", "upload"})
VIEWER_ACTIONS = frozenset({"read"})
SHARE_EDITOR_ACTIONS = frozenset({"read", "annotate", "edit"})
SHARE_VIEWER_ACTIONS = frozenset({"read"})

_HIDDEN = "Document not found"
_SHARE_HIDDEN = "Share link not found"


def org_actions(role: OrganizationRole | str) -> frozenset[str]:
    value = role.value if isinstance(role, OrganizationRole) else str(role)
    if value in {OrganizationRole.OWNER.value, OrganizationRole.ADMIN.value}:
        return OWNER_ACTIONS
    if value == OrganizationRole.MEMBER.value:
        return EDITOR_ACTIONS
    if value == OrganizationRole.VIEWER.value:
        return VIEWER_ACTIONS
    raise ValidationError("Unknown organization role")


def narrow_actions(actions: frozenset[str], grant_role: str | None) -> frozenset[str]:
    """A document grant can only remove capabilities."""
    if grant_role is None:
        return actions
    if grant_role == "viewer":
        return actions & VIEWER_ACTIONS
    if grant_role == "editor":
        return actions & EDITOR_ACTIONS
    raise ValidationError("Invalid document grant")


def labels_permit(
    *,
    audience_labels: tuple[str, ...],
    restricted_labels: tuple[str, ...],
    caller_labels: frozenset[str],
) -> bool:
    caller = {label.strip().lower() for label in caller_labels}
    restricted = {label.strip().lower() for label in restricted_labels}
    audience = {label.strip().lower() for label in audience_labels}
    if caller & restricted:
        return False
    if audience and not (caller & audience):
        return False
    return True


def require_active_document(document: Document | None, *, organization_id: UUID) -> Document:
    if (
        document is None
        or document.organization_id != organization_id
        or document.status != "active"
    ):
        raise NotFoundError(_HIDDEN)
    return document


def require_action(actions: frozenset[str], action: str) -> None:
    if action not in actions:
        raise NotFoundError(_HIDDEN)


def id_grant_permits(
    *,
    audience_labels: tuple[str, ...],
    restricted_labels: tuple[str, ...],
    caller_labels: frozenset[str],
    direct_role: str | None,
) -> bool:
    """A blocked label always denies. A named user id can open when audience labels would not."""
    caller = {label.strip().lower() for label in caller_labels}
    restricted = {label.strip().lower() for label in restricted_labels}
    if caller & restricted:
        return False
    if labels_permit(
        audience_labels=audience_labels,
        restricted_labels=restricted_labels,
        caller_labels=caller_labels,
    ):
        return True
    return direct_role in {"viewer", "editor"}


def require_labels(document: Document, caller_labels: frozenset[str]) -> None:
    if not labels_permit(
        audience_labels=document.audience_labels,
        restricted_labels=document.restricted_labels,
        caller_labels=caller_labels,
    ):
        raise NotFoundError(_HIDDEN)


def assert_expected_version(current_version_id: UUID | None, expected_version_id: UUID | None) -> None:
    if expected_version_id is not None and current_version_id != expected_version_id:
        raise ConflictError("Document version changed")


def assert_share_request(
    *,
    permission: str,
    expires_at: datetime,
    now: datetime,
    min_ttl_seconds: int,
    max_ttl_seconds: int,
    allow_guest_edit: bool,
) -> None:
    if permission not in {"viewer", "editor"}:
        raise ValidationError("Share permission must be viewer or editor")
    if permission == "editor" and not allow_guest_edit:
        raise ValidationError("Guest editing is not enabled")
    if expires_at.tzinfo is None:
        raise ValidationError("Share expiry must be timezone-aware UTC")
    expires_at = expires_at.astimezone(timezone.utc)
    now = now.astimezone(timezone.utc)
    delta = expires_at - now
    if delta <= timedelta(0):
        raise ValidationError("Share expiry must be in the future")
    if delta < timedelta(seconds=min_ttl_seconds) or delta > timedelta(seconds=max_ttl_seconds):
        raise ValidationError("Share expiry is outside the allowed lifetime")


def share_is_usable(link: ShareLink | None, now: datetime) -> ShareLink:
    if link is None or link.revoked_at is not None or link.expires_at <= now:
        raise NotFoundError(_SHARE_HIDDEN)
    return link


def share_actions(permission: str) -> frozenset[str]:
    if permission == "editor":
        return SHARE_EDITOR_ACTIONS
    return SHARE_VIEWER_ACTIONS


def child_depth(*, current_depth: int, remaining_depth: int) -> tuple[int, int]:
    if remaining_depth <= 0:
        raise NotFoundError("Document not found")
    return current_depth + 1, remaining_depth - 1


def epochs_match(token_epoch: int, current_epoch: int | None) -> bool:
    return current_epoch is not None and token_epoch == current_epoch


def orphan_keys(
    operations: list[UploadOperation],
    referenced_keys: set[str],
    *,
    now: datetime,
    grace_seconds: int,
) -> list[UploadOperation]:
    cutoff = now - timedelta(seconds=grace_seconds)
    ready: list[UploadOperation] = []
    for operation in operations:
        created = operation.created_at or now
        if operation.status != "abandoned":
            continue
        if created > cutoff:
            continue
        if operation.object_key in referenced_keys:
            continue
        ready.append(operation)
    return ready
