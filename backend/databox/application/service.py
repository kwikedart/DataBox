"""DataBox use cases. Depends on ports, not on FastAPI, SQLAlchemy, or GCS."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from databox.domain.exceptions import ConflictError, DomainError, NotFoundError, ValidationError
from databox.domain.identity import OrganizationRole, TenantIdentity

from databox.domain.entities import (
    AccessRequest,
    AuditEvent,
    CollaborationCheckpoint,
    CollaborationSession,
    Document,
    DocumentLink,
    DocumentPermission,
    DocumentVersion,
    MembershipAttributes,
    PageGrant,
    ShareLink,
    UploadOperation,
    ViewClaims,
)
from databox.domain.pdf_validation import validate_pdf
from databox.domain.policies import (
    assert_expected_version,
    assert_share_request,
    child_depth,
    epochs_match,
    id_grant_permits,
    narrow_actions,
    org_actions,
    orphan_keys,
    require_action,
    require_active_document,
    share_actions,
    share_is_usable,
)
from databox.domain.tokens import (
    generate_share_token,
    hash_share_token,
    issue_view_token,
    open_share_token,
    read_view_token,
    seal_share_token,
    share_token_matches,
)
from databox.settings import DataboxSettings

logger = logging.getLogger("databox")

_DOC_EPOCH = "databox:doc-epoch:{0}"
_SHARE_EPOCH = "databox:share-epoch:{0}"


@dataclass(frozen=True, slots=True)
class DocumentListing:
    document: Document
    can_open: bool
    pending_role: str | None = None


@dataclass(frozen=True, slots=True)
class ShareCreated:
    share_id: UUID
    url_token: str
    permission: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VersionShare:
    share_id: UUID
    version_id: UUID
    permission: str
    url_token: str
    expires_at: datetime
    current: bool


@dataclass(frozen=True, slots=True)
class CollaborationFrame:
    reply: bytes | None = None
    forward: bytes | None = None


class DataboxApplication:
    def __init__(
        self,
        *,
        store,
        storage,
        epochs,
        clock,
        settings: DataboxSettings,
        render_queue,
        transaction,
        rate_limiter,
        locks,
        tickets,
        fanout,
    ) -> None:
        self.store = store
        self.storage = storage
        self.epochs = epochs
        self.clock = clock
        self.settings = settings
        self.render_queue = render_queue
        self.transaction = transaction
        self.rate_limiter = rate_limiter
        self.locks = locks
        self.tickets = tickets
        self.fanout = fanout

    def _now(self) -> datetime:
        now = self.clock.now()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _rate(self, key: str, limit: int) -> None:
        if not self.rate_limiter.allow(
            key,
            self._now(),
            limit=limit,
            window_seconds=self.settings.rate_window_seconds,
        ):
            raise DomainError("Too many requests", code="rate_limited")

    async def _labels_for(self, organization_id: UUID, user_id: UUID | None) -> frozenset[str]:
        if user_id is None:
            return frozenset()
        return await self.store.get_attributes(organization_id, user_id)

    async def _opening(
        self, organization_id: UUID, user_id: UUID | None, document: Document
    ) -> tuple[bool, str | None, bool]:
        caller_labels = await self._labels_for(organization_id, user_id)
        direct = None
        if user_id is not None:
            direct = await self.store.get_permission(organization_id, document.id, user_id)
        if user_id is not None and user_id == document.created_by:
            return True, direct, True
        caller = {label.strip().lower() for label in caller_labels}
        restricted = {label.strip().lower() for label in document.restricted_labels}
        if caller & restricted:
            return False, direct, False
        named = direct in {"viewer", "editor"}
        if document.visibility == "private":
            return named, direct, False
        labeled = bool(document.audience_labels) and id_grant_permits(
            audience_labels=document.audience_labels,
            restricted_labels=document.restricted_labels,
            caller_labels=caller_labels,
            direct_role=None,
        )
        if labeled:
            return True, direct, True
        return named, direct, False

    async def _visible(self, actor: TenantIdentity, document_id: UUID, action: str) -> tuple[Document, frozenset[str]]:
        document = require_active_document(
            await self.store.get_document(actor.organization_id, document_id),
            organization_id=actor.organization_id,
        )
        allowed, direct, via_labels = await self._opening(actor.organization_id, actor.user_id, document)
        if not allowed:
            raise NotFoundError("Document not found")
        actions = org_actions(actor.role)
        if not via_labels:
            actions = narrow_actions(actions, direct)
        require_action(actions, action)
        return document, actions

    async def _publish_epoch(self, key: str, value: int) -> None:
        wrote = await self.epochs.set(key, value)
        if not wrote:
            await self.epochs.delete(key)

    async def _current_epoch(self, key: str, fallback: int) -> int:
        cached = await self.epochs.get(key)
        if cached is None:
            await self.epochs.set(key, fallback)
            return fallback
        return cached

    async def _audit(
        self,
        *,
        organization_id: UUID,
        actor_user_id: UUID | None,
        document_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        outcome: str,
    ) -> None:
        await self.store.append_audit(
            AuditEvent(
                id=uuid4(),
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                document_id=document_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome=outcome,
                created_at=self._now(),
            )
        )

    def _object_key(self, organization_id: UUID, document_id: UUID, version_id: UUID) -> str:
        return f"org/{organization_id}/documents/{document_id}/versions/{version_id}.pdf"

    def _render_key(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
        page: int,
        generation: int = 0,
    ) -> str:
        name = f"page-{page}.webp" if generation <= 0 else f"page-{page}-{generation}.webp"
        return f"org/{organization_id}/documents/{document_id}/renders/{version_id}/{name}"

    async def _surface(self, document: Document, version_id: UUID | None = None) -> tuple[int, int]:
        """Page count and render generation for a view token. Text documents are one picture."""
        target = version_id or document.current_version_id
        if target is None:
            raise NotFoundError("Document not found")
        if document.mime_type != "text/plain":
            return await self._page_count(document.organization_id, target), 0
        generation = len(await self.store.list_updates(document.id, target))
        self.render_queue.enqueue(
            organization_id=document.organization_id,
            document_id=document.id,
            version_id=target,
        )
        return 1, generation

    def _view_lifetime(self, now: datetime) -> tuple[int, int]:
        ttl = min(max(int(self.settings.view_token_ttl_seconds), 1), 30 * 60)
        issued_at = int(now.timestamp())
        return issued_at, issued_at + ttl

    async def _page_count(self, organization_id: UUID, version_id: UUID) -> int:
        version = await self.store.get_version(organization_id, version_id)
        if version is None:
            raise NotFoundError("Document not found")
        return version.page_count

    async def create_document(
        self,
        *,
        actor: TenantIdentity,
        title: str,
        content: bytes,
        case_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> Document:
        self._rate(f"upload:{actor.user_id}", self.settings.upload_limit)
        if "upload" not in org_actions(actor.role):
            raise NotFoundError("Document not found")
        if idempotency_key:
            existing = await self.store.find_upload(actor.organization_id, idempotency_key)
            if existing and existing.status == "completed" and existing.document_id:
                found = await self.store.get_document(actor.organization_id, existing.document_id)
                if found is not None:
                    return found
        page_count = validate_pdf(
            content,
            max_bytes=self.settings.max_upload_bytes,
            max_pages=self.settings.max_pages,
        )
        now = self._now()
        document_id = uuid4()
        version_id = uuid4()
        key = self._object_key(actor.organization_id, document_id, version_id)
        operation = UploadOperation(
            id=uuid4(),
            organization_id=actor.organization_id,
            object_key=key,
            status="pending",
            document_id=document_id,
            version_id=version_id,
            idempotency_key=idempotency_key,
            created_at=now,
        )
        await self.store.save_upload(operation)
        try:
            await self.storage.put(key, content, "application/pdf")
        except Exception:
            await self.store.save_upload(
                UploadOperation(
                    id=operation.id,
                    organization_id=operation.organization_id,
                    object_key=key,
                    status="abandoned",
                    document_id=document_id,
                    version_id=version_id,
                    idempotency_key=idempotency_key,
                    created_at=now,
                )
            )
            await self._audit(
                organization_id=actor.organization_id,
                actor_user_id=actor.user_id,
                document_id=document_id,
                action="document.upload",
                resource_type="document",
                resource_id=document_id,
                outcome="storage_failed",
            )
            raise DomainError("Document could not be stored", code="storage_failed") from None
        document = Document(
            id=document_id,
            organization_id=actor.organization_id,
            created_by=actor.user_id,
            title=title,
            status="active",
            policy_epoch=1,
            visibility="private",
            case_id=case_id,
            current_version_id=None,
            created_at=now,
            updated_at=now,
        )
        version = DocumentVersion(
            id=version_id,
            organization_id=actor.organization_id,
            document_id=document_id,
            version_number=1,
            bucket_name=self.settings.bucket_name,
            object_key=key,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            created_by=actor.user_id,
            page_count=page_count,
            created_at=now,
        )
        try:
            await self.store.save_document(document)
            saved = await self.store.commit_new_version(document, version, None)
            await self.store.save_upload(
                UploadOperation(
                    id=operation.id,
                    organization_id=operation.organization_id,
                    object_key=key,
                    status="completed",
                    document_id=document_id,
                    version_id=version_id,
                    idempotency_key=idempotency_key,
                    created_at=now,
                )
            )
            await self.transaction.commit()
        except Exception:
            await self.transaction.rollback()
            await self.store.save_upload(
                UploadOperation(
                    id=operation.id,
                    organization_id=operation.organization_id,
                    object_key=key,
                    status="abandoned",
                    document_id=None,
                    version_id=None,
                    idempotency_key=idempotency_key,
                    created_at=now,
                )
            )
            await self.transaction.commit()
            raise
        await self._publish_epoch(_DOC_EPOCH.format(saved.id), saved.policy_epoch)
        self.render_queue.enqueue(
            organization_id=saved.organization_id,
            document_id=saved.id,
            version_id=version_id,
        )
        await self._audit(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            document_id=saved.id,
            action="document.upload",
            resource_type="document",
            resource_id=saved.id,
            outcome="success",
        )
        return saved

    async def create_text_document(
        self,
        *,
        actor: TenantIdentity,
        title: str,
        idempotency_key: str | None = None,
    ) -> Document:
        """Create an empty collaborative text document. No PDF is stored or rendered."""
        self._rate(f"upload:{actor.user_id}", self.settings.upload_limit)
        if "upload" not in org_actions(actor.role):
            raise NotFoundError("Document not found")
        if idempotency_key:
            existing = await self.store.find_upload(actor.organization_id, idempotency_key)
            if existing and existing.status == "completed" and existing.document_id:
                found = await self.store.get_document(actor.organization_id, existing.document_id)
                if found is not None:
                    return found
        now = self._now()
        document_id = uuid4()
        version_id = uuid4()
        key = f"org/{actor.organization_id}/documents/{document_id}/versions/{version_id}.txt"
        content = b""
        operation = UploadOperation(
            id=uuid4(),
            organization_id=actor.organization_id,
            object_key=key,
            status="pending",
            document_id=document_id,
            version_id=version_id,
            idempotency_key=idempotency_key,
            created_at=now,
        )
        await self.store.save_upload(operation)
        try:
            await self.storage.put(key, content, "text/plain")
        except Exception:
            await self.store.save_upload(
                UploadOperation(
                    id=operation.id,
                    organization_id=operation.organization_id,
                    object_key=key,
                    status="abandoned",
                    document_id=document_id,
                    version_id=version_id,
                    idempotency_key=idempotency_key,
                    created_at=now,
                )
            )
            await self._audit(
                organization_id=actor.organization_id,
                actor_user_id=actor.user_id,
                document_id=document_id,
                action="document.create",
                resource_type="document",
                resource_id=document_id,
                outcome="storage_failed",
            )
            raise DomainError("Document could not be stored", code="storage_failed") from None
        document = Document(
            id=document_id,
            organization_id=actor.organization_id,
            created_by=actor.user_id,
            title=title,
            status="active",
            policy_epoch=1,
            mime_type="text/plain",
            visibility="private",
            current_version_id=None,
            created_at=now,
            updated_at=now,
        )
        version = DocumentVersion(
            id=version_id,
            organization_id=actor.organization_id,
            document_id=document_id,
            version_number=1,
            bucket_name=self.settings.bucket_name,
            object_key=key,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=0,
            created_by=actor.user_id,
            page_count=0,
            render_status="unavailable",
            created_at=now,
        )
        try:
            await self.store.save_document(document)
            saved = await self.store.commit_new_version(document, version, None)
            await self.store.save_upload(
                UploadOperation(
                    id=operation.id,
                    organization_id=operation.organization_id,
                    object_key=key,
                    status="completed",
                    document_id=document_id,
                    version_id=version_id,
                    idempotency_key=idempotency_key,
                    created_at=now,
                )
            )
            await self.transaction.commit()
        except Exception:
            await self.transaction.rollback()
            await self.store.save_upload(
                UploadOperation(
                    id=operation.id,
                    organization_id=operation.organization_id,
                    object_key=key,
                    status="abandoned",
                    document_id=None,
                    version_id=None,
                    idempotency_key=idempotency_key,
                    created_at=now,
                )
            )
            await self.transaction.commit()
            raise
        await self._publish_epoch(_DOC_EPOCH.format(saved.id), saved.policy_epoch)
        await self._audit(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            document_id=saved.id,
            action="document.create",
            resource_type="document",
            resource_id=saved.id,
            outcome="success",
        )
        return saved

    async def add_version(
        self,
        *,
        actor: TenantIdentity,
        document_id: UUID,
        content: bytes,
        expected_version_id: UUID | None,
    ) -> DocumentVersion:
        document, _actions = await self._visible(actor, document_id, "upload")
        assert_expected_version(document.current_version_id, expected_version_id)
        page_count = validate_pdf(
            content,
            max_bytes=self.settings.max_upload_bytes,
            max_pages=self.settings.max_pages,
        )
        return await self._store_version(
            actor=actor,
            document=document,
            content=content,
            page_count=page_count,
            expected_version_id=document.current_version_id,
            source_version_id=None,
        )

    async def restore_version(
        self,
        *,
        actor: TenantIdentity,
        document_id: UUID,
        version_id: UUID,
        expected_version_id: UUID | None,
    ) -> DocumentVersion:
        document, _actions = await self._visible(actor, document_id, "restore_version")
        assert_expected_version(document.current_version_id, expected_version_id)
        source = await self.store.get_version(actor.organization_id, version_id)
        if source is None or source.document_id != document.id:
            raise NotFoundError("Document not found")
        content = await self.storage.get(source.object_key)
        if hashlib.sha256(content).hexdigest() != source.sha256:
            raise DomainError("Stored document failed integrity check", code="integrity_failed")
        restored = await self._store_version(
            actor=actor,
            document=document,
            content=content,
            page_count=source.page_count,
            expected_version_id=document.current_version_id,
            source_version_id=source.id,
        )
        await self.store.save_checkpoint(
            CollaborationCheckpoint(document_id=document.id, version_id=restored.id, state_version=0, snapshot=None)
        )
        return restored

    async def _store_version(
        self,
        *,
        actor: TenantIdentity,
        document: Document,
        content: bytes,
        page_count: int,
        expected_version_id: UUID | None,
        source_version_id: UUID | None,
    ) -> DocumentVersion:
        now = self._now()
        version_id = uuid4()
        key = self._object_key(actor.organization_id, document.id, version_id)
        versions = await self.store.list_versions(actor.organization_id, document.id)
        next_number = (versions[0].version_number if versions else 0) + 1
        operation = UploadOperation(
            id=uuid4(),
            organization_id=actor.organization_id,
            object_key=key,
            status="pending",
            document_id=document.id,
            version_id=version_id,
            created_at=now,
        )
        await self.store.save_upload(operation)
        await self.storage.put(key, content, "application/pdf")
        version = DocumentVersion(
            id=version_id,
            organization_id=actor.organization_id,
            document_id=document.id,
            version_number=next_number,
            bucket_name=self.settings.bucket_name,
            object_key=key,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            created_by=actor.user_id,
            page_count=page_count,
            source_version_id=source_version_id,
            created_at=now,
        )
        bumped = Document(
            id=document.id,
            organization_id=document.organization_id,
            created_by=document.created_by,
            title=document.title,
            status=document.status,
            policy_epoch=document.policy_epoch + 1,
            classification_level=document.classification_level,
            audience_labels=document.audience_labels,
            restricted_labels=document.restricted_labels,
            case_id=document.case_id,
            current_version_id=document.current_version_id,
            mime_type=document.mime_type,
            visibility=document.visibility,
            created_at=document.created_at,
            updated_at=now,
            deleted_at=document.deleted_at,
        )
        try:
            await self.store.commit_new_version(bumped, version, expected_version_id)
            await self.store.save_upload(
                UploadOperation(
                    id=operation.id,
                    organization_id=operation.organization_id,
                    object_key=key,
                    status="completed",
                    document_id=document.id,
                    version_id=version_id,
                    created_at=now,
                )
            )
            await self.transaction.commit()
        except ConflictError:
            await self.transaction.rollback()
            await self.store.save_upload(
                UploadOperation(
                    id=operation.id,
                    organization_id=operation.organization_id,
                    object_key=key,
                    status="abandoned",
                    created_at=now,
                )
            )
            await self.transaction.commit()
            raise
        except Exception:
            await self.transaction.rollback()
            await self.store.save_upload(
                UploadOperation(
                    id=operation.id,
                    organization_id=operation.organization_id,
                    object_key=key,
                    status="abandoned",
                    created_at=now,
                )
            )
            await self.transaction.commit()
            raise
        await self._publish_epoch(_DOC_EPOCH.format(document.id), bumped.policy_epoch)
        self.render_queue.enqueue(
            organization_id=actor.organization_id,
            document_id=document.id,
            version_id=version_id,
        )
        await self._audit(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            document_id=document.id,
            action="version.restore" if source_version_id else "version.create",
            resource_type="document_version",
            resource_id=version_id,
            outcome="success",
        )
        return version

    async def list_documents(self, *, actor: TenantIdentity, case_id: UUID | None = None) -> list[DocumentListing]:
        rows = await self.store.list_documents(actor.organization_id, case_id)
        visible: list[DocumentListing] = []
        for document in rows:
            if document.status != "active":
                continue
            allowed, direct, via_labels = await self._opening(actor.organization_id, actor.user_id, document)
            if document.visibility != "public" and not allowed:
                continue
            actions = org_actions(actor.role)
            if allowed and not via_labels:
                actions = narrow_actions(actions, direct)
            if allowed and "read" not in actions:
                continue
            pending = None
            if not allowed:
                request = await self.store.get_access_request(actor.organization_id, document.id, actor.user_id)
                if request is not None and request.status == "pending":
                    pending = request.role
            visible.append(DocumentListing(document=document, can_open=allowed, pending_role=pending))
        return visible

    async def _managed(self, actor: TenantIdentity, document_id: UUID) -> Document:
        document = require_active_document(
            await self.store.get_document(actor.organization_id, document_id),
            organization_id=actor.organization_id,
        )
        if actor.user_id == document.created_by:
            return document
        if "manage_shares" in org_actions(actor.role) and document.visibility == "public":
            return document
        raise NotFoundError("Document not found")

    async def get_document(self, *, actor: TenantIdentity, document_id: UUID) -> Document:
        document, _actions = await self._visible(actor, document_id, "read")
        return document

    async def inspect_document(self, *, actor: TenantIdentity, document_id: UUID) -> DocumentListing:
        document = require_active_document(
            await self.store.get_document(actor.organization_id, document_id),
            organization_id=actor.organization_id,
        )
        allowed, _direct, _via_labels = await self._opening(actor.organization_id, actor.user_id, document)
        if document.visibility != "public" and not allowed:
            raise NotFoundError("Document not found")
        pending = None
        if not allowed:
            request = await self.store.get_access_request(actor.organization_id, document.id, actor.user_id)
            if request is not None and request.status == "pending":
                pending = request.role
        return DocumentListing(document=document, can_open=allowed, pending_role=pending)

    async def list_versions(self, *, actor: TenantIdentity, document_id: UUID) -> list[DocumentVersion]:
        await self._visible(actor, document_id, "read")
        return await self.store.list_versions(actor.organization_id, document_id)

    async def download(self, *, actor: TenantIdentity, document_id: UUID) -> tuple[DocumentVersion, bytes]:
        document, _actions = await self._visible(actor, document_id, "download")
        if document.current_version_id is None:
            raise NotFoundError("Document not found")
        version = await self.store.get_version(actor.organization_id, document.current_version_id)
        if version is None:
            raise NotFoundError("Document not found")
        content = await self.storage.get(version.object_key)
        await self._audit(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            document_id=document.id,
            action="document.download",
            resource_type="document",
            resource_id=document.id,
            outcome="success",
        )
        return version, content

    async def set_labels(
        self,
        *,
        actor: TenantIdentity,
        document_id: UUID,
        audience_labels: tuple[str, ...],
        restricted_labels: tuple[str, ...],
    ) -> Document:
        document = await self._managed(actor, document_id)
        now = self._now()
        updated = Document(
            id=document.id,
            organization_id=document.organization_id,
            created_by=document.created_by,
            title=document.title,
            status=document.status,
            policy_epoch=document.policy_epoch + 1,
            classification_level=document.classification_level,
            audience_labels=audience_labels,
            restricted_labels=restricted_labels,
            case_id=document.case_id,
            current_version_id=document.current_version_id,
            mime_type=document.mime_type,
            visibility=document.visibility,
            created_at=document.created_at,
            updated_at=now,
            deleted_at=document.deleted_at,
        )
        await self.store.save_document(updated)
        await self.transaction.commit()
        await self._publish_epoch(_DOC_EPOCH.format(updated.id), updated.policy_epoch)
        return updated

    async def get_membership_labels(self, *, actor: TenantIdentity) -> tuple[str, ...]:
        labels = await self.store.get_attributes(actor.organization_id, actor.user_id)
        return tuple(sorted(labels))

    async def set_membership_labels(
        self, *, actor: TenantIdentity, user_id: UUID, labels: tuple[str, ...]
    ) -> MembershipAttributes:
        if "manage_shares" not in org_actions(actor.role):
            raise NotFoundError("Document not found")
        attributes = MembershipAttributes(
            organization_id=actor.organization_id,
            user_id=user_id,
            labels=labels,
        )
        await self.store.save_attributes(attributes)
        await self.transaction.commit()
        return attributes

    async def grant_permission(
        self, *, actor: TenantIdentity, document_id: UUID, user_id: UUID, role: str
    ) -> DocumentPermission:
        document = await self._managed(actor, document_id)
        if user_id == actor.user_id:
            raise ValidationError("Share with another person's user id")
        if await self.store.get_member_role(actor.organization_id, user_id) is None:
            raise ValidationError("That user is not in this organization")
        permission = DocumentPermission(
            id=uuid4(),
            organization_id=actor.organization_id,
            document_id=document.id,
            user_id=user_id,
            role=role,
            granted_by=actor.user_id,
        )
        bumped = await self._bump_document(document)
        await self.store.save_permission(permission)
        await self.store.save_document(bumped)
        await self._audit(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            document_id=document.id,
            action="permission.grant",
            resource_type="document_permission",
            resource_id=permission.id,
            outcome="success",
        )
        await self.transaction.commit()
        await self._publish_epoch(_DOC_EPOCH.format(document.id), bumped.policy_epoch)
        return permission

    async def set_visibility(self, *, actor: TenantIdentity, document_id: UUID, visibility: str) -> Document:
        document = await self._managed(actor, document_id)
        if visibility not in {"public", "private"}:
            raise ValidationError("Document visibility must be public or private")
        updated = Document(
            id=document.id,
            organization_id=document.organization_id,
            created_by=document.created_by,
            title=document.title,
            status=document.status,
            policy_epoch=document.policy_epoch + 1,
            classification_level=document.classification_level,
            audience_labels=document.audience_labels,
            restricted_labels=document.restricted_labels,
            case_id=document.case_id,
            current_version_id=document.current_version_id,
            mime_type=document.mime_type,
            visibility=visibility,
            created_at=document.created_at,
            updated_at=self._now(),
            deleted_at=document.deleted_at,
        )
        await self.store.save_document(updated)
        await self.transaction.commit()
        await self._publish_epoch(_DOC_EPOCH.format(updated.id), updated.policy_epoch)
        return updated

    async def request_access(self, *, actor: TenantIdentity, document_id: UUID, role: str) -> AccessRequest:
        listing = await self.inspect_document(actor=actor, document_id=document_id)
        document = listing.document
        if document.visibility != "public" or actor.user_id == document.created_by:
            raise NotFoundError("Document not found")
        if listing.can_open:
            raise ValidationError("You already have access to this document")
        if role not in {"viewer", "editor"}:
            raise ValidationError("Access can only be requested as viewer or editor")
        request = AccessRequest(
            id=uuid4(),
            organization_id=actor.organization_id,
            document_id=document.id,
            user_id=actor.user_id,
            role=role,
            status="pending",
            created_at=self._now(),
        )
        await self.store.save_access_request(request)
        await self._audit(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            document_id=document.id,
            action="access.request",
            resource_type="access_request",
            resource_id=request.id,
            outcome="success",
        )
        await self.transaction.commit()
        return request

    async def list_access_requests(self, *, actor: TenantIdentity, document_id: UUID) -> list[AccessRequest]:
        document = await self._managed(actor, document_id)
        return await self.store.list_access_requests(document.organization_id, document.id)

    async def decide_access_request(
        self, *, actor: TenantIdentity, document_id: UUID, request_id: UUID, approve: bool
    ) -> None:
        document = await self._managed(actor, document_id)
        pending = await self.store.list_access_requests(document.organization_id, document.id)
        request = next((row for row in pending if row.id == request_id), None)
        if request is None:
            raise NotFoundError("Document not found")
        if not approve:
            await self.store.save_access_request(
                AccessRequest(
                    id=request.id,
                    organization_id=request.organization_id,
                    document_id=request.document_id,
                    user_id=request.user_id,
                    role=request.role,
                    status="denied",
                    created_at=request.created_at,
                    decided_by=actor.user_id,
                )
            )
            await self.transaction.commit()
            return
        if await self.store.get_member_role(actor.organization_id, request.user_id) is None:
            raise NotFoundError("Document not found")
        permission = DocumentPermission(
            id=uuid4(),
            organization_id=actor.organization_id,
            document_id=document.id,
            user_id=request.user_id,
            role=request.role,
            granted_by=actor.user_id,
        )
        bumped = await self._bump_document(document)
        await self.store.save_permission(permission)
        await self.store.save_document(bumped)
        await self.store.save_access_request(
            AccessRequest(
                id=request.id,
                organization_id=request.organization_id,
                document_id=request.document_id,
                user_id=request.user_id,
                role=request.role,
                status="approved",
                created_at=request.created_at,
                decided_by=actor.user_id,
            )
        )
        await self._audit(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            document_id=document.id,
            action="access.approve",
            resource_type="access_request",
            resource_id=request.id,
            outcome="success",
        )
        await self.transaction.commit()
        await self._publish_epoch(_DOC_EPOCH.format(document.id), bumped.policy_epoch)

    async def list_user_shares(self, *, actor: TenantIdentity, document_id: UUID) -> list[DocumentPermission]:
        document = await self._managed(actor, document_id)
        return await self.store.list_permissions(document.organization_id, document.id)

    async def revoke_user_share(self, *, actor: TenantIdentity, document_id: UUID, user_id: UUID) -> None:
        document = await self._managed(actor, document_id)
        removed = await self.store.delete_permission(actor.organization_id, document.id, user_id)
        if not removed:
            raise ValidationError("That user is not shared on this document")
        bumped = await self._bump_document(document)
        await self.store.save_document(bumped)
        await self._audit(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            document_id=document.id,
            action="permission.revoke",
            resource_type="document_permission",
            resource_id=user_id,
            outcome="success",
        )
        await self.transaction.commit()
        await self._publish_epoch(_DOC_EPOCH.format(document.id), bumped.policy_epoch)

    async def _bump_document(self, document: Document) -> Document:
        return Document(
            id=document.id,
            organization_id=document.organization_id,
            created_by=document.created_by,
            title=document.title,
            status=document.status,
            policy_epoch=document.policy_epoch + 1,
            classification_level=document.classification_level,
            audience_labels=document.audience_labels,
            restricted_labels=document.restricted_labels,
            case_id=document.case_id,
            current_version_id=document.current_version_id,
            mime_type=document.mime_type,
            visibility=document.visibility,
            created_at=document.created_at,
            updated_at=self._now(),
            deleted_at=document.deleted_at,
        )

    async def create_share_link(
        self,
        *,
        actor: TenantIdentity,
        document_id: UUID,
        permission: str,
        expires_at: datetime,
        idempotency_key: str | None = None,
        version_id: UUID | None = None,
    ) -> ShareCreated:
        document = await self._managed(actor, document_id)
        now = self._now()
        assert_share_request(
            permission=permission,
            expires_at=expires_at,
            now=now,
            min_ttl_seconds=self.settings.share_min_ttl_seconds,
            max_ttl_seconds=self.settings.share_max_ttl_seconds,
            allow_guest_edit=self.settings.allow_guest_edit or document.mime_type == "text/plain",
        )
        target_version = version_id or document.current_version_id
        if target_version is None:
            raise NotFoundError("Document not found")
        version = await self.store.get_version(actor.organization_id, target_version)
        if version is None or version.document_id != document.id:
            raise NotFoundError("Document not found")
        if permission == "editor" and target_version != document.current_version_id:
            raise ValidationError("Only the current version can be shared for editing")
        if idempotency_key:
            for share in await self.store.list_shares(actor.organization_id, document.id):
                if share.idempotency_key == idempotency_key:
                    raise ConflictError("Share link already created for this idempotency key")
        raw = generate_share_token()
        share_id = uuid4()
        share = ShareLink(
            id=share_id,
            organization_id=actor.organization_id,
            document_id=document.id,
            token_hash=hash_share_token(raw, self.settings.token_pepper),
            permission=permission,
            expires_at=expires_at.astimezone(timezone.utc),
            created_by=actor.user_id,
            created_at=now,
            idempotency_key=idempotency_key,
            version_id=target_version,
            sealed_token=seal_share_token(raw, self.settings.token_pepper, share_id),
        )
        await self.store.save_share(share)
        await self.transaction.commit()
        await self._publish_epoch(_SHARE_EPOCH.format(share.id), share.policy_epoch)
        await self._audit(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            document_id=document.id,
            action="share.create",
            resource_type="share_link",
            resource_id=share.id,
            outcome="success",
        )
        return ShareCreated(
            share_id=share.id,
            url_token=raw,
            permission=share.permission,
            expires_at=share.expires_at,
        )

    async def revoke_share_link(self, *, actor: TenantIdentity, share_id: UUID) -> ShareLink:
        share = await self.store.get_share(actor.organization_id, share_id)
        if share is None:
            raise NotFoundError("Share link not found")
        await self._managed(actor, share.document_id)
        if share.revoked_at is not None:
            return share
        revoked = _share_with(share, policy_epoch=share.policy_epoch + 1, revoked_at=self._now())
        await self.store.save_share(revoked)
        await self.transaction.commit()
        await self._publish_epoch(_SHARE_EPOCH.format(revoked.id), revoked.policy_epoch)
        await self._audit(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            document_id=share.document_id,
            action="share.revoke",
            resource_type="share_link",
            resource_id=share.id,
            outcome="success",
        )
        return revoked

    async def list_version_shares(self, *, actor: TenantIdentity, document_id: UUID) -> list[VersionShare]:
        """Return the standing edit and view links. Managers can read them on every visit."""
        document = await self._managed(actor, document_id)
        if document.current_version_id is None:
            return []
        await self._ensure_version_shares(actor, document)
        current = await self.store.get_document(actor.organization_id, document.id)
        if current is None or current.current_version_id is None:
            raise NotFoundError("Document not found")
        now = self._now()
        chosen: dict[tuple[UUID, str], ShareLink] = {}
        for share in await self.store.list_shares(actor.organization_id, document.id):
            if not _share_is_current(share, now):
                continue
            if share.version_id is None or not share.sealed_token:
                continue
            if share.permission == "editor" and share.version_id != current.current_version_id:
                continue
            key = (share.version_id, share.permission)
            previous = chosen.get(key)
            if previous is None or share.expires_at > previous.expires_at:
                chosen[key] = share
        links: list[VersionShare] = []
        for share in chosen.values():
            if share.version_id is None or not share.sealed_token:
                continue
            links.append(
                VersionShare(
                    share_id=share.id,
                    version_id=share.version_id,
                    permission=share.permission,
                    url_token=open_share_token(share.sealed_token, self.settings.token_pepper, share.id),
                    expires_at=share.expires_at,
                    current=share.version_id == current.current_version_id,
                )
            )
        links.sort(key=lambda item: (not item.current, item.permission))
        return links

    async def save_text_version(
        self,
        *,
        actor: TenantIdentity,
        document_id: UUID,
        expected_version_id: UUID | None,
    ) -> Document:
        """Freeze the current text and continue editing on a new version."""
        document, _actions = await self._visible(actor, document_id, "edit")
        if document.mime_type != "text/plain" or document.current_version_id is None:
            raise ValidationError("Only the current text document can be saved")
        assert_expected_version(document.current_version_id, expected_version_id)
        old_version_id = document.current_version_id
        checkpoint = await self.store.get_checkpoint(document.id, old_version_id)
        updates = await self.store.list_updates(document.id, old_version_id)
        if checkpoint is None:
            compact = _compact_snapshot(None, updates)
        else:
            compact = _compact_snapshot(checkpoint.snapshot, updates[checkpoint.state_version :])
        now = self._now()
        version_id = uuid4()
        key = f"org/{document.organization_id}/documents/{document.id}/versions/{version_id}.txt"
        versions = await self.store.list_versions(actor.organization_id, document.id)
        next_number = (versions[0].version_number if versions else 0) + 1
        try:
            await self.storage.put(key, b"", "text/plain")
        except Exception:
            raise DomainError("Document could not be stored", code="storage_failed") from None
        version = DocumentVersion(
            id=version_id,
            organization_id=document.organization_id,
            document_id=document.id,
            version_number=next_number,
            bucket_name=self.settings.bucket_name,
            object_key=key,
            sha256=hashlib.sha256(b"").hexdigest(),
            size_bytes=0,
            created_by=actor.user_id,
            page_count=0,
            source_version_id=old_version_id,
            render_status="unavailable",
            created_at=now,
        )
        bumped = Document(
            id=document.id,
            organization_id=document.organization_id,
            created_by=document.created_by,
            title=document.title,
            status=document.status,
            policy_epoch=document.policy_epoch + 1,
            classification_level=document.classification_level,
            audience_labels=document.audience_labels,
            restricted_labels=document.restricted_labels,
            case_id=document.case_id,
            current_version_id=document.current_version_id,
            mime_type=document.mime_type,
            visibility=document.visibility,
            created_at=document.created_at,
            updated_at=now,
            deleted_at=document.deleted_at,
        )
        try:
            saved = await self.store.commit_new_version(bumped, version, old_version_id)
            await self.store.save_checkpoint(
                CollaborationCheckpoint(
                    document_id=document.id,
                    version_id=version_id,
                    state_version=0,
                    snapshot=compact,
                )
            )
            for share in await self.store.list_shares(actor.organization_id, document.id):
                if share.permission == "editor" and share.revoked_at is None and share.version_id == old_version_id:
                    revoked = _share_with(share, policy_epoch=share.policy_epoch + 1, revoked_at=now)
                    await self.store.save_share(revoked)
                    await self._publish_epoch(_SHARE_EPOCH.format(revoked.id), revoked.policy_epoch)
            await self.transaction.commit()
        except ConflictError:
            await self.transaction.rollback()
            raise
        except Exception:
            await self.transaction.rollback()
            raise
        await self._publish_epoch(_DOC_EPOCH.format(saved.id), saved.policy_epoch)
        await self._audit(
            organization_id=actor.organization_id,
            actor_user_id=actor.user_id,
            document_id=saved.id,
            action="document.version",
            resource_type="document_version",
            resource_id=version_id,
            outcome="success",
        )
        if actor.user_id == saved.created_by or "manage_shares" in org_actions(actor.role):
            await self._ensure_version_shares(actor, saved)
        return saved

    async def _ensure_version_shares(self, actor: TenantIdentity, document: Document) -> None:
        if document.current_version_id is None:
            return
        now = self._now()
        expires_at = self._default_share_expiry(now)
        versions = await self.store.list_versions(actor.organization_id, document.id)
        shares = await self.store.list_shares(actor.organization_id, document.id)
        for share in shares:
            if (
                share.permission == "editor"
                and share.revoked_at is None
                and share.version_id != document.current_version_id
            ):
                revoked = _share_with(share, policy_epoch=share.policy_epoch + 1, revoked_at=now)
                await self.store.save_share(revoked)
                await self._publish_epoch(_SHARE_EPOCH.format(revoked.id), revoked.policy_epoch)
        await self.transaction.commit()
        for version in versions:
            permissions = ("viewer", "editor") if version.id == document.current_version_id and document.mime_type == "text/plain" else ("viewer",)
            if document.mime_type != "text/plain" and version.id != document.current_version_id:
                permissions = ("viewer",)
            for permission in permissions:
                fresh = await self.store.list_shares(actor.organization_id, document.id)
                if any(_share_is_current(share, now) and share.version_id == version.id and share.permission == permission and share.sealed_token for share in fresh):
                    continue
                await self.create_share_link(
                    actor=actor,
                    document_id=document.id,
                    permission=permission,
                    expires_at=expires_at,
                    version_id=version.id,
                )

    def _default_share_expiry(self, now: datetime) -> datetime:
        ttl = min(24 * 3600, self.settings.share_max_ttl_seconds)
        ttl = max(ttl, self.settings.share_min_ttl_seconds)
        return now + timedelta(seconds=ttl)

    async def set_share_lifetime(
        self,
        *,
        actor: TenantIdentity,
        document_id: UUID,
        version_id: UUID,
        permission: str,
        ttl_seconds: int,
    ) -> VersionShare:
        """Replace one version's link with a new token that expires after the chosen lifetime."""
        document = await self._managed(actor, document_id)
        version = await self.store.get_version(actor.organization_id, version_id)
        if version is None or version.document_id != document.id:
            raise NotFoundError("Document not found")
        if permission == "editor" and (
            document.mime_type != "text/plain" or version.id != document.current_version_id
        ):
            raise ValidationError("Only the current version can be shared for editing")
        now = self._now()
        expires_at = now + timedelta(seconds=int(ttl_seconds))
        assert_share_request(
            permission=permission,
            expires_at=expires_at,
            now=now,
            min_ttl_seconds=self.settings.share_min_ttl_seconds,
            max_ttl_seconds=self.settings.share_max_ttl_seconds,
            allow_guest_edit=self.settings.allow_guest_edit or document.mime_type == "text/plain",
        )
        for share in await self.store.list_shares(actor.organization_id, document.id):
            if share.version_id == version.id and share.permission == permission and share.revoked_at is None:
                await self.revoke_share_link(actor=actor, share_id=share.id)
        created = await self.create_share_link(
            actor=actor,
            document_id=document.id,
            permission=permission,
            expires_at=expires_at,
            version_id=version.id,
        )
        return VersionShare(
            share_id=created.share_id,
            version_id=version.id,
            permission=created.permission,
            url_token=created.url_token,
            expires_at=created.expires_at,
            current=version.id == document.current_version_id,
        )

    async def resolve_share(self, *, actor: TenantIdentity, token: str, caller_key: str) -> ShareLink:
        """Open a share only for a signed-in customer whose labels allow this document."""
        self._rate(f"share:{actor.user_id}:{caller_key}", self.settings.share_resolve_limit)
        token_hash = hash_share_token(token, self.settings.token_pepper)
        if not share_token_matches(token, self.settings.token_pepper, token_hash):
            raise NotFoundError("Share link not found")
        found = await self.store.get_share_by_hash(token_hash)
        try:
            link = share_is_usable(found, self._now())
        except NotFoundError:
            if found is not None:
                await self._audit(
                    organization_id=found.organization_id,
                    actor_user_id=actor.user_id,
                    document_id=found.document_id,
                    action="share.use",
                    resource_type="share_link",
                    resource_id=found.id,
                    outcome="denied",
                )
                await self.transaction.commit()
            raise
        if actor.organization_id != link.organization_id:
            await self._audit(
                organization_id=link.organization_id,
                actor_user_id=actor.user_id,
                document_id=link.document_id,
                action="share.use",
                resource_type="share_link",
                resource_id=link.id,
                outcome="denied",
            )
            await self.transaction.commit()
            raise NotFoundError("Share link not found")
        document = require_active_document(
            await self.store.get_document(link.organization_id, link.document_id),
            organization_id=link.organization_id,
        )
        allowed, _direct, _via_labels = await self._opening(actor.organization_id, actor.user_id, document)
        if not allowed:
            await self._audit(
                organization_id=link.organization_id,
                actor_user_id=actor.user_id,
                document_id=link.document_id,
                action="share.use",
                resource_type="share_link",
                resource_id=link.id,
                outcome="denied",
            )
            await self.transaction.commit()
            raise NotFoundError("Share link not found")
        await self._audit(
            organization_id=link.organization_id,
            actor_user_id=actor.user_id,
            document_id=link.document_id,
            action="share.use",
            resource_type="share_link",
            resource_id=link.id,
            outcome="success",
        )
        await self.transaction.commit()
        return link

    async def issue_view_token(
        self,
        *,
        actor: TenantIdentity | None,
        document_id: UUID | None = None,
        share_token: str | None = None,
        parent_token: str | None = None,
    ) -> str:
        now = self._now()
        if parent_token:
            if document_id is None:
                raise NotFoundError("Document not found")
            return await self._issue_child_token(parent_token=parent_token, target_document_id=document_id, now=now)
        if share_token:
            if actor is None:
                raise NotFoundError("Share link not found")
            digest = hashlib.sha256(share_token.encode("utf-8")).hexdigest()[:16]
            link = await self.resolve_share(actor=actor, token=share_token, caller_key=f"share:{digest}")
            if document_id is not None and link.document_id != document_id:
                raise NotFoundError("Share link not found")
            document_id = link.document_id
            document = require_active_document(
                await self.store.get_document(link.organization_id, document_id),
                organization_id=link.organization_id,
            )
            allowed, _direct, _via_labels = await self._opening(link.organization_id, actor.user_id, document)
            if not allowed:
                raise NotFoundError("Share link not found")
            version_id = link.version_id or document.current_version_id
            if version_id is None:
                raise NotFoundError("Document not found")
            version = await self.store.get_version(document.organization_id, version_id)
            if version is None or version.document_id != document.id:
                raise NotFoundError("Document not found")
            epoch = await self._current_epoch(_DOC_EPOCH.format(document.id), document.policy_epoch)
            share_epoch = await self._current_epoch(_SHARE_EPOCH.format(link.id), link.policy_epoch)
            if not epochs_match(document.policy_epoch, epoch) or not epochs_match(link.policy_epoch, share_epoch):
                raise ValidationError("Access token is not valid")
            issued_at, expires_at = self._view_lifetime(now)
            claims = ViewClaims(
                subject=str(actor.user_id) if actor else "share",
                organization_id=document.organization_id,
                document_id=document.id,
                version_id=version_id,
                scope=frozenset({"view", "render"}),
                policy_epoch=document.policy_epoch,
                root_document_id=document.id,
                current_depth=0,
                remaining_depth=self.settings.max_cascade_depth,
                expires_at=expires_at,
                page_count=(surface := await self._surface(document, version_id))[0],
                issued_at=issued_at,
                render_generation=surface[1],
                share_link_id=link.id,
                share_epoch=link.policy_epoch,
            )
            return issue_view_token(claims, secret=self.settings.view_token_secret)
        if actor is None or document_id is None:
            raise NotFoundError("Document not found")
        document, _actions = await self._visible(actor, document_id, "read")
        if document.current_version_id is None:
            raise NotFoundError("Document not found")
        await self._publish_epoch(_DOC_EPOCH.format(document.id), document.policy_epoch)
        issued_at, expires_at = self._view_lifetime(now)
        claims = ViewClaims(
            subject=str(actor.user_id),
            organization_id=document.organization_id,
            document_id=document.id,
            version_id=document.current_version_id,
            scope=frozenset({"view", "render"}),
            policy_epoch=document.policy_epoch,
            root_document_id=document.id,
            current_depth=0,
            remaining_depth=self.settings.max_cascade_depth,
            expires_at=expires_at,
            page_count=(surface := await self._surface(document))[0],
            issued_at=issued_at,
            render_generation=surface[1],
        )
        return issue_view_token(claims, secret=self.settings.view_token_secret)

    async def _issue_child_token(self, *, parent_token: str, target_document_id: UUID, now: datetime) -> str:
        parent = read_view_token(parent_token, secret=self.settings.view_token_secret, now=now)
        if "view" not in parent.scope:
            raise NotFoundError("Document not found")
        parent_epoch = await self._current_epoch(_DOC_EPOCH.format(parent.document_id), parent.policy_epoch)
        if not epochs_match(parent.policy_epoch, parent_epoch):
            raise ValidationError("Access token is not valid")
        link = await self.store.find_link(parent.organization_id, parent.document_id, target_document_id)
        if link is None:
            raise NotFoundError("Document not found")
        next_depth, remaining = child_depth(
            current_depth=parent.current_depth,
            remaining_depth=min(parent.remaining_depth, link.cascade_depth),
        )
        document = require_active_document(
            await self.store.get_document(parent.organization_id, target_document_id),
            organization_id=parent.organization_id,
        )
        subject_id: UUID | None = None
        if parent.subject and parent.subject != "share":
            try:
                subject_id = UUID(parent.subject)
            except ValueError:
                subject_id = None
        allowed, _direct, _via_labels = await self._opening(parent.organization_id, subject_id, document)
        if not allowed:
            raise NotFoundError("Document not found")
        if document.current_version_id is None:
            raise NotFoundError("Document not found")
        issued_at, lifetime_end = self._view_lifetime(now)
        claims = ViewClaims(
            subject=parent.subject,
            organization_id=document.organization_id,
            document_id=document.id,
            version_id=document.current_version_id,
            scope=frozenset({"view", "render"}),
            policy_epoch=document.policy_epoch,
            root_document_id=parent.root_document_id,
            current_depth=next_depth,
            remaining_depth=remaining,
            expires_at=min(parent.expires_at, lifetime_end),
            page_count=(surface := await self._surface(document))[0],
            issued_at=issued_at,
            render_generation=surface[1],
            share_link_id=parent.share_link_id,
            share_epoch=parent.share_epoch,
        )
        await self._publish_epoch(_DOC_EPOCH.format(document.id), document.policy_epoch)
        return issue_view_token(claims, secret=self.settings.view_token_secret)

    async def authorize_page(self, *, token: str, document_id: UUID, page: int) -> PageGrant:
        """Authorize a rendered page from the signed token alone. No database or epoch lookup."""
        if page < 1:
            raise ValidationError("Page number must be positive")
        claims = read_view_token(token, secret=self.settings.view_token_secret, now=self._now())
        if claims.document_id != document_id or "render" not in claims.scope:
            raise ValidationError("Access token is not valid")
        if claims.page_count < 1 or page > claims.page_count:
            raise NotFoundError("Document not found")
        return PageGrant(
            organization_id=claims.organization_id,
            document_id=claims.document_id,
            version_id=claims.version_id,
            page=page,
            object_key=self._render_key(
                claims.organization_id,
                claims.document_id,
                claims.version_id,
                page,
                claims.render_generation,
            ),
        )

    async def open_rendered_page(self, grant: PageGrant):
        """Stream a rendered page. A cache miss enqueues the worker and does not rasterize here."""
        chunks = self.storage.read_chunks(grant.object_key)
        try:
            first = await anext(chunks)
        except StopAsyncIteration:
            await chunks.aclose()
            raise DomainError("Page is not ready", code="page_not_ready") from None
        except FileNotFoundError:
            await chunks.aclose()
            self.render_queue.enqueue(
                organization_id=grant.organization_id,
                document_id=grant.document_id,
                version_id=grant.version_id,
            )
            raise DomainError("Page is not ready", code="page_not_ready") from None
        return first, chunks

    async def create_link(
        self,
        *,
        actor: TenantIdentity,
        document_id: UUID,
        target_document_id: UUID,
        label: str | None = None,
        cascade_depth: int = 1,
    ) -> DocumentLink:
        await self._visible(actor, document_id, "edit")
        target = require_active_document(
            await self.store.get_document(actor.organization_id, target_document_id),
            organization_id=actor.organization_id,
        )
        allowed, _direct, _via_labels = await self._opening(actor.organization_id, actor.user_id, target)
        if not allowed:
            raise NotFoundError("Document not found")
        link = DocumentLink(
            id=uuid4(),
            organization_id=actor.organization_id,
            source_document_id=document_id,
            target_document_id=target.id,
            created_by=actor.user_id,
            label=label,
            cascade_depth=cascade_depth,
            created_at=self._now(),
        )
        await self.store.save_link(link)
        await self.transaction.commit()
        return link

    async def list_links(self, *, actor: TenantIdentity, document_id: UUID) -> list[DocumentLink]:
        await self._visible(actor, document_id, "read")
        rows = await self.store.list_links(actor.organization_id, document_id)
        visible: list[DocumentLink] = []
        for link in rows:
            target = await self.store.get_document(actor.organization_id, link.target_document_id)
            if target is None or target.status != "active":
                continue
            allowed, _direct, _via_labels = await self._opening(actor.organization_id, actor.user_id, target)
            if allowed:
                visible.append(link)
        return visible

    async def open_collaboration(
        self,
        *,
        actor: TenantIdentity | None,
        document_id: UUID,
        share_token: str | None = None,
    ) -> str:
        now = self._now()
        actor_key = str(actor.user_id) if actor is not None else "anonymous"
        self._rate(f"collab-open:{actor_key}", 30)
        if share_token:
            if actor is None:
                raise NotFoundError("Share link not found")
            link = await self.resolve_share(
                actor=actor,
                token=share_token,
                caller_key=f"collab:{hashlib.sha256(share_token.encode('utf-8')).hexdigest()[:16]}",
            )
            if link.document_id != document_id:
                raise NotFoundError("Document not found")
            document = require_active_document(
                await self.store.get_document(link.organization_id, document_id),
                organization_id=link.organization_id,
            )
            actions = share_actions(link.permission)
            organization_id = link.organization_id
            user_id = actor.user_id if actor else None
            if (
                link.permission == "editor"
                and link.version_id is not None
                and link.version_id != document.current_version_id
            ):
                raise NotFoundError("Document not found")
            share_id = link.id
            share_epoch = link.policy_epoch
            role = link.permission
        else:
            if actor is None:
                raise NotFoundError("Document not found")
            document, actions = await self._visible(actor, document_id, "read")
            organization_id = actor.organization_id
            user_id = actor.user_id
            share_id = None
            share_epoch = None
            role = "editor" if "edit" in actions else "viewer"
        if document.current_version_id is None:
            raise NotFoundError("Document not found")
        raw = generate_share_token()
        self.tickets.put(
            hash_share_token(raw, self.settings.token_pepper),
            now + timedelta(seconds=60),
            {
                "organization_id": str(organization_id),
                "document_id": str(document.id),
                "version_id": str(document.current_version_id),
                "user_id": str(user_id) if user_id else "",
                "role": role,
                "actions": sorted(actions),
                "policy_epoch": document.policy_epoch,
                "share_link_id": str(share_id) if share_id else "",
                "share_epoch": share_epoch if share_epoch is not None else "",
            },
        )
        await self._audit(
            organization_id=organization_id,
            actor_user_id=user_id,
            document_id=document.id,
            action="collaboration.open",
            resource_type="document",
            resource_id=document.id,
            outcome="success",
        )
        return raw

    async def accept_collaboration_ticket(self, *, document_id: UUID, ticket: str) -> CollaborationSession:
        payload = self.tickets.consume(hash_share_token(ticket, self.settings.token_pepper), self._now())
        if payload is None or payload.get("document_id") != str(document_id):
            raise NotFoundError("Document not found")
        user_raw = payload.get("user_id") or ""
        share_raw = payload.get("share_link_id") or ""
        share_epoch = payload.get("share_epoch")
        return CollaborationSession(
            session_id=uuid4(),
            organization_id=UUID(payload["organization_id"]),
            document_id=UUID(payload["document_id"]),
            version_id=UUID(payload["version_id"]),
            user_id=UUID(user_raw) if user_raw else None,
            role=str(payload["role"]),
            actions=frozenset(payload["actions"]),
            policy_epoch=int(payload["policy_epoch"]),
            share_link_id=UUID(share_raw) if share_raw else None,
            share_epoch=int(share_epoch) if share_epoch != "" and share_epoch is not None else None,
        )

    async def session_still_valid(self, session: CollaborationSession) -> bool:
        document = await self.store.get_document(session.organization_id, session.document_id)
        if document is None or document.status != "active":
            return False
        if document.current_version_id != session.version_id:
            return False
        current = await self._current_epoch(_DOC_EPOCH.format(document.id), document.policy_epoch)
        if not epochs_match(session.policy_epoch, current):
            return False
        if session.share_link_id is not None:
            share = await self.store.get_share(session.organization_id, session.share_link_id)
            try:
                share_is_usable(share, self._now())
            except NotFoundError:
                return False
            share_epoch = await self._current_epoch(_SHARE_EPOCH.format(session.share_link_id), share.policy_epoch)
            if session.share_epoch is None or not epochs_match(session.share_epoch, share_epoch):
                return False
        return True

    async def apply_collaboration_update(self, *, session: CollaborationSession, update: bytes) -> int:
        if "edit" not in session.actions:
            raise NotFoundError("Document not found")
        if not update or len(update) > self.settings.collaboration_update_max_bytes:
            raise ValidationError("Collaboration update is empty or too large")
        _require_yjs_update(update)
        actor_key = str(session.user_id) if session.user_id else "anonymous"
        self._rate(f"collab-update:{actor_key}", 120)
        if not await self.locks.acquire(session.document_id):
            raise ConflictError("Collaboration document is busy")
        try:
            if not await self.session_still_valid(session):
                raise NotFoundError("Document not found")
            sequence = await self.store.append_update(session.document_id, session.version_id, update)
            checkpoint = await self.store.get_checkpoint(session.document_id, session.version_id)
            state_version = 0 if checkpoint is None else checkpoint.state_version
            snapshot = None if checkpoint is None else checkpoint.snapshot
            if sequence % self.settings.snapshot_every_updates == 0:
                snapshot = _compact_snapshot(snapshot, await self.store.list_updates(session.document_id, session.version_id))
                state_version = sequence
            await self.store.save_checkpoint(
                CollaborationCheckpoint(
                    document_id=session.document_id,
                    version_id=session.version_id,
                    state_version=state_version,
                    snapshot=snapshot,
                )
            )
            await self.transaction.commit()
        finally:
            await self.locks.release(session.document_id)
        from pycrdt import create_update_message

        await self.fanout.publish(session.document_id, create_update_message(update))
        return sequence

    async def load_collaboration_document(self, session: CollaborationSession):
        from pycrdt import Doc

        if not await self.session_still_valid(session):
            raise NotFoundError("Document not found")
        snapshot, updates = await self.collaboration_state(session)
        document = Doc()
        if snapshot:
            document.apply_update(snapshot)
        for update in updates:
            document.apply_update(update)
        return document

    async def handle_collaboration_message(
        self,
        *,
        session: CollaborationSession,
        frame: bytes,
        document,
    ) -> CollaborationFrame:
        """Apply one Yjs sync or awareness frame. Awareness is never persisted."""
        from pycrdt import YMessageType, YSyncMessageType, handle_sync_message, read_message

        if not frame or len(frame) > self.settings.collaboration_update_max_bytes:
            raise ValidationError("Collaboration update is empty or too large")
        if frame[0] == YMessageType.AWARENESS:
            return CollaborationFrame(forward=frame)
        if frame[0] != YMessageType.SYNC or len(frame) < 2:
            raise ValidationError("Collaboration update is empty or too large")
        sync_type = frame[1]
        if sync_type == YSyncMessageType.SYNC_STEP1:
            return CollaborationFrame(reply=handle_sync_message(frame[1:], document))
        if sync_type not in (YSyncMessageType.SYNC_STEP2, YSyncMessageType.SYNC_UPDATE):
            raise ValidationError("Collaboration update is empty or too large")
        update = read_message(frame[2:])
        if not update or update == b"\x00\x00":
            return CollaborationFrame()
        if "edit" not in session.actions:
            return CollaborationFrame()
        await self.apply_collaboration_update(session=session, update=update)
        document.apply_update(update)
        return CollaborationFrame()

    async def collaboration_state(self, session: CollaborationSession) -> tuple[bytes | None, list[bytes]]:
        if not await self.session_still_valid(session):
            raise NotFoundError("Document not found")
        checkpoint = await self.store.get_checkpoint(session.document_id, session.version_id)
        updates = await self.store.list_updates(session.document_id, session.version_id)
        if checkpoint is None:
            return None, updates
        return checkpoint.snapshot, updates[checkpoint.state_version :]

    async def delete_document(self, *, actor: TenantIdentity, document_id: UUID) -> Document:
        document, _actions = await self._visible(actor, document_id, "delete")
        now = self._now()
        deleting = Document(
            id=document.id,
            organization_id=document.organization_id,
            created_by=document.created_by,
            title=document.title,
            status="deleting",
            policy_epoch=document.policy_epoch + 1,
            classification_level=document.classification_level,
            audience_labels=document.audience_labels,
            restricted_labels=document.restricted_labels,
            case_id=document.case_id,
            current_version_id=document.current_version_id,
            mime_type=document.mime_type,
            visibility=document.visibility,
            created_at=document.created_at,
            updated_at=now,
            deleted_at=now,
        )
        await self.store.save_document(deleting)
        for share in await self.store.list_shares(actor.organization_id, document.id):
            if share.revoked_at is None:
                await self.store.save_share(_share_with(share, policy_epoch=share.policy_epoch + 1, revoked_at=now))
                await self._publish_epoch(_SHARE_EPOCH.format(share.id), share.policy_epoch + 1)
        await self.transaction.commit()
        await self._publish_epoch(_DOC_EPOCH.format(document.id), deleting.policy_epoch)
        return deleting

    async def cleanup_orphans(self) -> list[str]:
        now = self._now()
        ready = orphan_keys(
            await self.store.abandoned_uploads(),
            await self.store.referenced_object_keys(),
            now=now,
            grace_seconds=self.settings.orphan_grace_seconds,
        )
        deleted: list[str] = []
        for operation in ready:
            await self.storage.delete(operation.object_key)
            deleted.append(operation.object_key)
            await self.store.save_upload(
                UploadOperation(
                    id=operation.id,
                    organization_id=operation.organization_id,
                    object_key=operation.object_key,
                    status="completed",
                    document_id=operation.document_id,
                    version_id=operation.version_id,
                    idempotency_key=operation.idempotency_key,
                    created_at=operation.created_at,
                )
            )
        return deleted


def _share_with(share: ShareLink, **changes: object) -> ShareLink:
    values: dict[str, object] = {
        "id": share.id,
        "organization_id": share.organization_id,
        "document_id": share.document_id,
        "token_hash": share.token_hash,
        "permission": share.permission,
        "expires_at": share.expires_at,
        "created_by": share.created_by,
        "policy_epoch": share.policy_epoch,
        "revoked_at": share.revoked_at,
        "created_at": share.created_at,
        "access_count": share.access_count,
        "idempotency_key": share.idempotency_key,
        "version_id": share.version_id,
        "sealed_token": share.sealed_token,
    }
    values.update(changes)
    return ShareLink(**values)  # type: ignore[arg-type]


def _share_is_current(share: ShareLink, now: datetime) -> bool:
    return share.revoked_at is None and share.expires_at > now


def _require_yjs_update(update: bytes) -> None:
    from pycrdt import Doc

    document = Doc()
    try:
        document.apply_update(update)
    except Exception as exc:
        raise ValidationError("Collaboration update is not a valid document update") from exc


def _compact_snapshot(snapshot: bytes | None, updates: list[bytes]) -> bytes:
    try:
        from pycrdt import Doc
    except ImportError:
        parts = []
        if snapshot:
            parts.append(snapshot)
        parts.extend(updates)
        return b"".join(parts)
    document = Doc()
    if snapshot:
        document.apply_update(snapshot)
    for update in updates:
        document.apply_update(update)
    return document.get_update()


def actor_for_role(user_id: UUID, organization_id: UUID, role: str) -> TenantIdentity:
    return TenantIdentity(user_id=user_id, organization_id=organization_id, role=OrganizationRole(role))
