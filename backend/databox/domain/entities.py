"""Immutable DataBox snapshots. Persistence behavior stays in adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from databox.domain.exceptions import ValidationError
from databox.domain.identity import ObjectKey


def _labels(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    cleaned: list[str] = []
    for raw in values:
        label = str(raw).strip().lower()
        if not label or len(label) > 64 or any(ch.isspace() for ch in label):
            raise ValidationError("Document labels must be short tokens without spaces")
        if label not in cleaned:
            cleaned.append(label)
    return tuple(cleaned)


@dataclass(frozen=True, slots=True)
class Document:
    id: UUID
    organization_id: UUID
    created_by: UUID
    title: str
    status: str
    policy_epoch: int
    classification_level: str = "internal"
    audience_labels: tuple[str, ...] = ()
    restricted_labels: tuple[str, ...] = ()
    case_id: UUID | None = None
    current_version_id: UUID | None = None
    mime_type: str = "application/pdf"
    visibility: str = "public"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not title or len(title) > 255:
            raise ValidationError("Document title must be between 1 and 255 characters")
        if self.status not in {"active", "deleting", "deleted"}:
            raise ValidationError("Invalid document status")
        if self.policy_epoch < 1:
            raise ValidationError("Policy epoch must be positive")
        if self.visibility not in {"public", "private"}:
            raise ValidationError("Document visibility must be public or private")
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "audience_labels", _labels(self.audience_labels))
        object.__setattr__(self, "restricted_labels", _labels(self.restricted_labels))


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    id: UUID
    organization_id: UUID
    document_id: UUID
    version_number: int
    bucket_name: str
    object_key: str
    sha256: str
    size_bytes: int
    created_by: UUID
    page_count: int = 0
    source_version_id: UUID | None = None
    render_status: str = "pending"
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.version_number < 1:
            raise ValidationError("Version number must be positive")
        if self.size_bytes < 0:
            raise ValidationError("Version size cannot be negative")
        if len(self.sha256) != 64:
            raise ValidationError("Version checksum must be a SHA-256 hex digest")
        ObjectKey(self.object_key)
        if self.render_status not in {"pending", "ready", "failed", "unavailable"}:
            raise ValidationError("Invalid render status")


@dataclass(frozen=True, slots=True)
class ShareLink:
    id: UUID
    organization_id: UUID
    document_id: UUID
    token_hash: str
    permission: str
    expires_at: datetime
    created_by: UUID
    policy_epoch: int = 1
    revoked_at: datetime | None = None
    created_at: datetime | None = None
    access_count: int = 0
    idempotency_key: str | None = None
    version_id: UUID | None = None
    sealed_token: str | None = None

    def __post_init__(self) -> None:
        if self.permission not in {"viewer", "editor"}:
            raise ValidationError("Share permission must be viewer or editor")
        if len(self.token_hash) != 64:
            raise ValidationError("Share token hash must be 64 hex characters")
        if self.policy_epoch < 1:
            raise ValidationError("Policy epoch must be positive")


@dataclass(frozen=True, slots=True)
class DocumentPermission:
    id: UUID
    organization_id: UUID
    document_id: UUID
    user_id: UUID
    role: str
    granted_by: UUID

    def __post_init__(self) -> None:
        if self.role not in {"viewer", "editor"}:
            raise ValidationError("Document grants can only narrow access to viewer or editor")


@dataclass(frozen=True, slots=True)
class AccessRequest:
    id: UUID
    organization_id: UUID
    document_id: UUID
    user_id: UUID
    role: str
    status: str
    created_at: datetime | None = None
    decided_by: UUID | None = None

    def __post_init__(self) -> None:
        if self.role not in {"viewer", "editor"}:
            raise ValidationError("Access can only be requested as viewer or editor")
        if self.status not in {"pending", "approved", "denied"}:
            raise ValidationError("Invalid access request")


@dataclass(frozen=True, slots=True)
class MembershipAttributes:
    organization_id: UUID
    user_id: UUID
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", _labels(self.labels))


@dataclass(frozen=True, slots=True)
class DocumentLink:
    id: UUID
    organization_id: UUID
    source_document_id: UUID
    target_document_id: UUID
    created_by: UUID
    label: str | None = None
    cascade_depth: int = 1
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.cascade_depth < 0:
            raise ValidationError("Cascade depth cannot be negative")
        if self.source_document_id == self.target_document_id:
            raise ValidationError("A document cannot link to itself")


@dataclass(frozen=True, slots=True)
class UploadOperation:
    id: UUID
    organization_id: UUID
    object_key: str
    status: str
    document_id: UUID | None = None
    version_id: UUID | None = None
    idempotency_key: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.status not in {"pending", "completed", "abandoned"}:
            raise ValidationError("Invalid upload status")
        if self.object_key:
            ObjectKey(self.object_key)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: UUID
    organization_id: UUID
    action: str
    resource_type: str
    outcome: str
    actor_user_id: UUID | None = None
    document_id: UUID | None = None
    resource_id: UUID | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CollaborationCheckpoint:
    document_id: UUID
    version_id: UUID
    state_version: int = 0
    snapshot: bytes | None = None


@dataclass(frozen=True, slots=True)
class ViewClaims:
    subject: str
    organization_id: UUID
    document_id: UUID
    version_id: UUID
    scope: frozenset[str]
    policy_epoch: int
    root_document_id: UUID
    current_depth: int
    remaining_depth: int
    expires_at: int
    page_count: int = 0
    issued_at: int = 0
    render_generation: int = 0
    share_link_id: UUID | None = None
    share_epoch: int | None = None


@dataclass(frozen=True, slots=True)
class PageGrant:
    """Page access decided only from a signed view token."""

    organization_id: UUID
    document_id: UUID
    version_id: UUID
    page: int
    object_key: str


@dataclass(frozen=True, slots=True)
class CollaborationSession:
    session_id: UUID
    organization_id: UUID
    document_id: UUID
    version_id: UUID
    user_id: UUID | None
    role: str
    actions: frozenset[str]
    policy_epoch: int
    share_link_id: UUID | None = None
    share_epoch: int | None = None
