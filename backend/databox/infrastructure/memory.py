"""In-memory adapters used by tests and single-process development."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

from databox.domain.exceptions import ConflictError

from databox.domain.entities import (
    AccessRequest,
    AuditEvent,
    CollaborationCheckpoint,
    Document,
    DocumentLink,
    DocumentPermission,
    DocumentVersion,
    MembershipAttributes,
    ShareLink,
    UploadOperation,
)


class MemoryDataboxStore:
    def __init__(self) -> None:
        self.documents: dict[UUID, Document] = {}
        self.versions: dict[UUID, DocumentVersion] = {}
        self.shares: dict[UUID, ShareLink] = {}
        self.permissions: list[DocumentPermission] = []
        self.requests: dict[tuple[UUID, UUID], AccessRequest] = {}
        self.members: dict[tuple[UUID, UUID], str] = {}
        self.attributes: dict[tuple[UUID, UUID], MembershipAttributes] = {}
        self.links: dict[UUID, DocumentLink] = {}
        self.uploads: dict[UUID, UploadOperation] = {}
        self.audits: list[AuditEvent] = []
        self.updates: dict[tuple[UUID, UUID], list[bytes]] = defaultdict(list)
        self.checkpoints: dict[tuple[UUID, UUID], CollaborationCheckpoint] = {}
        self._lock = asyncio.Lock()

    async def get_document(self, organization_id: UUID, document_id: UUID) -> Document | None:
        document = self.documents.get(document_id)
        if document is None or document.organization_id != organization_id:
            return None
        return document

    async def list_documents(self, organization_id: UUID, case_id: UUID | None = None) -> list[Document]:
        rows = [row for row in self.documents.values() if row.organization_id == organization_id]
        if case_id is not None:
            rows = [row for row in rows if row.case_id == case_id]
        return rows

    async def save_document(self, document: Document) -> None:
        self.documents[document.id] = document

    async def get_version(self, organization_id: UUID, version_id: UUID) -> DocumentVersion | None:
        version = self.versions.get(version_id)
        if version is None or version.organization_id != organization_id:
            return None
        return version

    async def list_versions(self, organization_id: UUID, document_id: UUID) -> list[DocumentVersion]:
        rows = [
            row
            for row in self.versions.values()
            if row.organization_id == organization_id and row.document_id == document_id
        ]
        return sorted(rows, key=lambda row: row.version_number, reverse=True)

    async def commit_new_version(
        self,
        document: Document,
        version: DocumentVersion,
        expected_version_id: UUID | None,
    ) -> Document:
        async with self._lock:
            current = self.documents.get(document.id)
            if current is None or current.organization_id != document.organization_id:
                raise ConflictError("Document version changed")
            if current.current_version_id != expected_version_id:
                raise ConflictError("Document version changed")
            numbers = [
                row.version_number
                for row in self.versions.values()
                if row.document_id == document.id
            ]
            if version.version_number != (max(numbers) if numbers else 0) + 1:
                raise ConflictError("Document version changed")
            self.versions[version.id] = version
            saved = Document(
                id=current.id,
                organization_id=current.organization_id,
                created_by=current.created_by,
                title=current.title,
                status=current.status,
                policy_epoch=document.policy_epoch,
                classification_level=current.classification_level,
                audience_labels=current.audience_labels,
                restricted_labels=current.restricted_labels,
                case_id=current.case_id,
                current_version_id=version.id,
                mime_type=current.mime_type,
                visibility=current.visibility,
                created_at=current.created_at,
                updated_at=document.updated_at,
                deleted_at=current.deleted_at,
            )
            self.documents[saved.id] = saved
            return saved

    async def get_share_by_hash(self, token_hash: str) -> ShareLink | None:
        for share in self.shares.values():
            if share.token_hash == token_hash:
                return share
        return None

    async def get_share(self, organization_id: UUID, share_id: UUID) -> ShareLink | None:
        share = self.shares.get(share_id)
        if share is None or share.organization_id != organization_id:
            return None
        return share

    async def list_shares(self, organization_id: UUID, document_id: UUID) -> list[ShareLink]:
        return [
            row
            for row in self.shares.values()
            if row.organization_id == organization_id and row.document_id == document_id
        ]

    async def save_share(self, share: ShareLink) -> None:
        self.shares[share.id] = share

    async def find_upload(self, organization_id: UUID, idempotency_key: str) -> UploadOperation | None:
        for operation in self.uploads.values():
            if operation.organization_id == organization_id and operation.idempotency_key == idempotency_key:
                return operation
        return None

    async def save_upload(self, operation: UploadOperation) -> None:
        self.uploads[operation.id] = operation

    async def abandoned_uploads(self) -> list[UploadOperation]:
        return [row for row in self.uploads.values() if row.status == "abandoned"]

    async def referenced_object_keys(self) -> set[str]:
        return {row.object_key for row in self.versions.values()}

    async def get_attributes(self, organization_id: UUID, user_id: UUID) -> frozenset[str]:
        row = self.attributes.get((organization_id, user_id))
        if row is None:
            return frozenset()
        return frozenset(row.labels)

    async def save_attributes(self, attributes: MembershipAttributes) -> None:
        self.attributes[(attributes.organization_id, attributes.user_id)] = attributes

    async def get_member_role(self, organization_id: UUID, user_id: UUID) -> str | None:
        return self.members.get((organization_id, user_id))

    async def get_permission(self, organization_id: UUID, document_id: UUID, user_id: UUID) -> str | None:
        for row in self.permissions:
            if (
                row.organization_id == organization_id
                and row.document_id == document_id
                and row.user_id == user_id
            ):
                return row.role
        return None

    async def save_permission(self, permission: DocumentPermission) -> None:
        self.permissions = [
            row
            for row in self.permissions
            if not (row.document_id == permission.document_id and row.user_id == permission.user_id)
        ]
        self.permissions.append(permission)

    async def get_access_request(self, organization_id: UUID, document_id: UUID, user_id: UUID) -> AccessRequest | None:
        row = self.requests.get((document_id, user_id))
        if row is None or row.organization_id != organization_id:
            return None
        return row

    async def save_access_request(self, request: AccessRequest) -> None:
        self.requests[(request.document_id, request.user_id)] = request

    async def list_access_requests(self, organization_id: UUID, document_id: UUID) -> list[AccessRequest]:
        return [
            row
            for row in self.requests.values()
            if row.organization_id == organization_id and row.document_id == document_id and row.status == "pending"
        ]

    async def list_permissions(self, organization_id: UUID, document_id: UUID) -> list[DocumentPermission]:
        return [
            row
            for row in self.permissions
            if row.organization_id == organization_id and row.document_id == document_id
        ]

    async def delete_permission(self, organization_id: UUID, document_id: UUID, user_id: UUID) -> bool:
        kept: list[DocumentPermission] = []
        removed = False
        for row in self.permissions:
            if row.organization_id == organization_id and row.document_id == document_id and row.user_id == user_id:
                removed = True
                continue
            kept.append(row)
        self.permissions = kept
        return removed

    async def list_links(self, organization_id: UUID, source_document_id: UUID) -> list[DocumentLink]:
        return [
            row
            for row in self.links.values()
            if row.organization_id == organization_id and row.source_document_id == source_document_id
        ]

    async def find_link(
        self, organization_id: UUID, source_document_id: UUID, target_document_id: UUID
    ) -> DocumentLink | None:
        for row in self.links.values():
            if (
                row.organization_id == organization_id
                and row.source_document_id == source_document_id
                and row.target_document_id == target_document_id
            ):
                return row
        return None

    async def save_link(self, link: DocumentLink) -> None:
        self.links[link.id] = link

    async def delete_link(self, organization_id: UUID, link_id: UUID) -> None:
        row = self.links.get(link_id)
        if row is not None and row.organization_id == organization_id:
            del self.links[link_id]

    async def append_audit(self, event: AuditEvent) -> None:
        self.audits.append(event)

    async def append_update(self, document_id: UUID, version_id: UUID, update: bytes) -> int:
        bucket = self.updates[(document_id, version_id)]
        bucket.append(update)
        return len(bucket)

    async def list_updates(self, document_id: UUID, version_id: UUID) -> list[bytes]:
        return list(self.updates.get((document_id, version_id), []))

    async def save_checkpoint(self, checkpoint: CollaborationCheckpoint) -> None:
        self.checkpoints[(checkpoint.document_id, checkpoint.version_id)] = checkpoint

    async def get_checkpoint(self, document_id: UUID, version_id: UUID) -> CollaborationCheckpoint | None:
        return self.checkpoints.get((document_id, version_id))

    async def set_render_status(self, organization_id: UUID, version_id: UUID, status: str) -> None:
        version = self.versions.get(version_id)
        if version is None or version.organization_id != organization_id:
            return
        self.versions[version_id] = replace(version, render_status=status)


class MemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_next = False

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        del content_type
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("storage failed")
        self.objects[key] = data

    async def read_chunks(self, key: str, chunk_size: int = 64 * 1024):
        data = await self.get(key)
        for offset in range(0, len(data), chunk_size):
            yield data[offset : offset + chunk_size]

    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class MemoryEpochCache:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.fail_set = False

    async def get(self, key: str) -> int | None:
        return self.values.get(key)

    async def set(self, key: str, value: int) -> bool:
        if self.fail_set:
            return False
        self.values[key] = value
        return True

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


class MemoryRateLimiter:
    def __init__(self) -> None:
        self.hits: dict[str, list[datetime]] = defaultdict(list)

    def allow(self, key: str, now: datetime, *, limit: int, window_seconds: int) -> bool:
        cutoff = now - timedelta(seconds=window_seconds)
        recent = [stamp for stamp in self.hits[key] if stamp > cutoff]
        if len(recent) >= limit:
            self.hits[key] = recent
            return False
        recent.append(now)
        self.hits[key] = recent
        return True


class MemoryDocumentLock:
    def __init__(self) -> None:
        self._locks: dict[UUID, asyncio.Lock] = {}

    async def acquire(self, document_id: UUID) -> bool:
        lock = self._locks.setdefault(document_id, asyncio.Lock())
        await lock.acquire()
        return True

    async def release(self, document_id: UUID) -> None:
        lock = self._locks.get(document_id)
        if lock is not None and lock.locked():
            lock.release()


class MemoryTicketStore:
    def __init__(self) -> None:
        self.tickets: dict[str, tuple[datetime, dict]] = {}

    def put(self, token_hash: str, expires_at: datetime, payload: dict) -> None:
        self.tickets[token_hash] = (expires_at, payload)

    def consume(self, token_hash: str, now: datetime) -> dict | None:
        row = self.tickets.pop(token_hash, None)
        if row is None:
            return None
        expires_at, payload = row
        if expires_at <= now:
            return None
        return payload


class MemoryFanout:
    def __init__(self) -> None:
        self.messages: dict[UUID, list[bytes]] = defaultdict(list)
        self.subscribers: dict[UUID, set[asyncio.Queue]] = defaultdict(set)

    async def publish(self, document_id: UUID, message: bytes) -> None:
        self.messages[document_id].append(message)
        for queue in list(self.subscribers[document_id]):
            await queue.put(message)

    def subscribe(self, document_id: UUID) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers[document_id].add(queue)
        return queue

    def unsubscribe(self, document_id: UUID, queue: asyncio.Queue) -> None:
        self.subscribers[document_id].discard(queue)


class NullTransaction:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class RecordingRenderQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[UUID, UUID, UUID]] = []

    def enqueue(self, *, organization_id: UUID, document_id: UUID, version_id: UUID) -> None:
        self.jobs.append((organization_id, document_id, version_id))
