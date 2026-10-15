"""PostgreSQL adapter for DataBox. Every lookup except share-token hash is organization-scoped."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from databox.infrastructure.rows import (
    DataboxAuditLogRow,
    DataboxCollaborationCheckpointRow,
    DataboxDocumentLinkRow,
    DataboxDocumentPermissionRow,
    DataboxDocumentRow,
    DataboxDocumentVersionRow,
    DataboxMembershipAttributeRow,
    DataboxShareLinkRow,
    MembershipRow,
    DataboxUploadOperationRow,
    DataboxYjsUpdateRow,
)
from databox.domain.entities import (
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
from databox.domain.exceptions import ConflictError


def _document(row: DataboxDocumentRow) -> Document:
    return Document(
        id=row.id,
        organization_id=row.organization_id,
        created_by=row.created_by,
        title=row.title,
        status=row.status,
        policy_epoch=int(row.policy_epoch),
        classification_level=row.classification_level,
        audience_labels=tuple(row.audience_labels or ()),
        restricted_labels=tuple(row.restricted_labels or ()),
        case_id=row.case_id,
        current_version_id=row.current_version_id,
        mime_type=row.mime_type,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
    )


def _version(row: DataboxDocumentVersionRow) -> DocumentVersion:
    return DocumentVersion(
        id=row.id,
        organization_id=row.organization_id,
        document_id=row.document_id,
        version_number=row.version_number,
        bucket_name=row.bucket_name,
        object_key=row.object_key,
        sha256=row.sha256,
        size_bytes=int(row.size_bytes),
        created_by=row.created_by,
        page_count=row.page_count,
        source_version_id=row.source_version_id,
        render_status=row.render_status,
        created_at=row.created_at,
    )


def _share(row: DataboxShareLinkRow) -> ShareLink:
    return ShareLink(
        id=row.id,
        organization_id=row.organization_id,
        document_id=row.document_id,
        token_hash=row.token_hash,
        permission=row.permission,
        expires_at=row.expires_at,
        created_by=row.created_by,
        policy_epoch=int(row.policy_epoch),
        revoked_at=row.revoked_at,
        created_at=row.created_at,
        access_count=int(row.access_count or 0),
        idempotency_key=row.idempotency_key,
        version_id=row.version_id,
        sealed_token=row.sealed_token,
    )


class SqlAlchemyDataboxStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_document(self, organization_id: UUID, document_id: UUID) -> Document | None:
        row = await self.session.scalar(
            select(DataboxDocumentRow).where(
                DataboxDocumentRow.id == document_id,
                DataboxDocumentRow.organization_id == organization_id,
            )
        )
        return None if row is None else _document(row)

    async def list_documents(self, organization_id: UUID, case_id: UUID | None = None) -> list[Document]:
        stmt = select(DataboxDocumentRow).where(DataboxDocumentRow.organization_id == organization_id)
        if case_id is not None:
            stmt = stmt.where(DataboxDocumentRow.case_id == case_id)
        rows = (await self.session.scalars(stmt)).all()
        return [_document(row) for row in rows]

    async def save_document(self, document: Document) -> None:
        row = await self.session.scalar(select(DataboxDocumentRow).where(DataboxDocumentRow.id == document.id))
        if row is None:
            self.session.add(
                DataboxDocumentRow(
                    id=document.id,
                    organization_id=document.organization_id,
                    case_id=document.case_id,
                    created_by=document.created_by,
                    title=document.title,
                    mime_type=document.mime_type,
                    status=document.status,
                    current_version_id=document.current_version_id,
                    classification_level=document.classification_level,
                    audience_labels=list(document.audience_labels),
                    restricted_labels=list(document.restricted_labels),
                    policy_epoch=document.policy_epoch,
                    created_at=document.created_at,
                    updated_at=document.updated_at,
                    deleted_at=document.deleted_at,
                )
            )
        else:
            if row.organization_id != document.organization_id:
                raise ConflictError("Document version changed")
            row.title = document.title
            row.status = document.status
            row.policy_epoch = document.policy_epoch
            row.audience_labels = list(document.audience_labels)
            row.restricted_labels = list(document.restricted_labels)
            row.current_version_id = document.current_version_id
            row.updated_at = document.updated_at
            row.deleted_at = document.deleted_at
        await self.session.flush()

    async def get_version(self, organization_id: UUID, version_id: UUID) -> DocumentVersion | None:
        row = await self.session.scalar(
            select(DataboxDocumentVersionRow).where(
                DataboxDocumentVersionRow.id == version_id,
                DataboxDocumentVersionRow.organization_id == organization_id,
            )
        )
        return None if row is None else _version(row)

    async def list_versions(self, organization_id: UUID, document_id: UUID) -> list[DocumentVersion]:
        rows = (
            await self.session.scalars(
                select(DataboxDocumentVersionRow)
                .where(
                    DataboxDocumentVersionRow.organization_id == organization_id,
                    DataboxDocumentVersionRow.document_id == document_id,
                )
                .order_by(DataboxDocumentVersionRow.version_number.desc())
            )
        ).all()
        return [_version(row) for row in rows]

    async def commit_new_version(
        self,
        document: Document,
        version: DocumentVersion,
        expected_version_id: UUID | None,
    ) -> Document:
        row = await self.session.scalar(
            select(DataboxDocumentRow)
            .where(
                DataboxDocumentRow.id == document.id,
                DataboxDocumentRow.organization_id == document.organization_id,
            )
            .with_for_update()
        )
        if row is None or row.current_version_id != expected_version_id:
            raise ConflictError("Document version changed")
        current_max = await self.session.scalar(
            select(func.max(DataboxDocumentVersionRow.version_number)).where(
                DataboxDocumentVersionRow.document_id == document.id
            )
        )
        next_number = int(current_max or 0) + 1
        if version.version_number != next_number:
            raise ConflictError("Document version changed")
        self.session.add(
            DataboxDocumentVersionRow(
                id=version.id,
                organization_id=version.organization_id,
                document_id=version.document_id,
                version_number=version.version_number,
                bucket_name=version.bucket_name,
                object_key=version.object_key,
                sha256=version.sha256,
                size_bytes=version.size_bytes,
                page_count=version.page_count,
                created_by=version.created_by,
                source_version_id=version.source_version_id,
                render_status=version.render_status,
                created_at=version.created_at,
            )
        )
        # current_version_id references this row. Insert it before the document
        # update, or Postgres rejects the foreign key.
        await self.session.flush()
        row.current_version_id = version.id
        row.policy_epoch = document.policy_epoch
        row.updated_at = document.updated_at
        await self.session.flush()
        return _document(row)

    async def get_share_by_hash(self, token_hash: str) -> ShareLink | None:
        row = await self.session.scalar(select(DataboxShareLinkRow).where(DataboxShareLinkRow.token_hash == token_hash))
        return None if row is None else _share(row)

    async def get_share(self, organization_id: UUID, share_id: UUID) -> ShareLink | None:
        row = await self.session.scalar(
            select(DataboxShareLinkRow).where(
                DataboxShareLinkRow.id == share_id,
                DataboxShareLinkRow.organization_id == organization_id,
            )
        )
        return None if row is None else _share(row)

    async def list_shares(self, organization_id: UUID, document_id: UUID) -> list[ShareLink]:
        rows = (
            await self.session.scalars(
                select(DataboxShareLinkRow).where(
                    DataboxShareLinkRow.organization_id == organization_id,
                    DataboxShareLinkRow.document_id == document_id,
                )
            )
        ).all()
        return [_share(row) for row in rows]

    async def save_share(self, share: ShareLink) -> None:
        row = await self.session.scalar(select(DataboxShareLinkRow).where(DataboxShareLinkRow.id == share.id))
        if row is None:
            self.session.add(
                DataboxShareLinkRow(
                    id=share.id,
                    organization_id=share.organization_id,
                    document_id=share.document_id,
                    token_hash=share.token_hash,
                    permission=share.permission,
                    expires_at=share.expires_at,
                    revoked_at=share.revoked_at,
                    created_by=share.created_by,
                    policy_epoch=share.policy_epoch,
                    access_count=share.access_count,
                    idempotency_key=share.idempotency_key,
                    created_at=share.created_at,
                    version_id=share.version_id,
                    sealed_token=share.sealed_token,
                )
            )
        else:
            if row.organization_id != share.organization_id:
                raise ConflictError("Document version changed")
            row.revoked_at = share.revoked_at
            row.policy_epoch = share.policy_epoch
            row.access_count = share.access_count
        await self.session.flush()

    async def find_upload(self, organization_id: UUID, idempotency_key: str) -> UploadOperation | None:
        row = await self.session.scalar(
            select(DataboxUploadOperationRow).where(
                DataboxUploadOperationRow.organization_id == organization_id,
                DataboxUploadOperationRow.idempotency_key == idempotency_key,
            )
        )
        return None if row is None else _upload(row)

    async def save_upload(self, operation: UploadOperation) -> None:
        row = await self.session.scalar(select(DataboxUploadOperationRow).where(DataboxUploadOperationRow.id == operation.id))
        if row is None:
            self.session.add(
                DataboxUploadOperationRow(
                    id=operation.id,
                    organization_id=operation.organization_id,
                    object_key=operation.object_key,
                    status=operation.status,
                    document_id=operation.document_id,
                    version_id=operation.version_id,
                    idempotency_key=operation.idempotency_key,
                    created_at=operation.created_at,
                )
            )
        else:
            row.status = operation.status
            row.document_id = operation.document_id
            row.version_id = operation.version_id
        await self.session.flush()

    async def abandoned_uploads(self) -> list[UploadOperation]:
        rows = (
            await self.session.scalars(
                select(DataboxUploadOperationRow).where(DataboxUploadOperationRow.status == "abandoned")
            )
        ).all()
        return [_upload(row) for row in rows]

    async def referenced_object_keys(self) -> set[str]:
        rows = (await self.session.scalars(select(DataboxDocumentVersionRow.object_key))).all()
        return set(rows)

    async def get_attributes(self, organization_id: UUID, user_id: UUID) -> frozenset[str]:
        row = await self.session.scalar(
            select(DataboxMembershipAttributeRow).where(
                DataboxMembershipAttributeRow.organization_id == organization_id,
                DataboxMembershipAttributeRow.user_id == user_id,
            )
        )
        if row is None:
            return frozenset()
        return frozenset(row.labels or ())

    async def save_attributes(self, attributes: MembershipAttributes) -> None:
        row = await self.session.scalar(
            select(DataboxMembershipAttributeRow).where(
                DataboxMembershipAttributeRow.organization_id == attributes.organization_id,
                DataboxMembershipAttributeRow.user_id == attributes.user_id,
            )
        )
        if row is None:
            self.session.add(
                DataboxMembershipAttributeRow(
                    id=uuid4(),
                    organization_id=attributes.organization_id,
                    user_id=attributes.user_id,
                    labels=list(attributes.labels),
                )
            )
        else:
            row.labels = list(attributes.labels)
        await self.session.flush()

    async def get_member_role(self, organization_id: UUID, user_id: UUID) -> str | None:
        row = await self.session.scalar(
            select(MembershipRow).where(
                MembershipRow.organization_id == organization_id,
                MembershipRow.user_id == user_id,
            )
        )
        return None if row is None else row.role

    async def get_permission(self, organization_id: UUID, document_id: UUID, user_id: UUID) -> str | None:
        row = await self.session.scalar(
            select(DataboxDocumentPermissionRow).where(
                DataboxDocumentPermissionRow.organization_id == organization_id,
                DataboxDocumentPermissionRow.document_id == document_id,
                DataboxDocumentPermissionRow.user_id == user_id,
            )
        )
        return None if row is None else row.role

    async def save_permission(self, permission: DocumentPermission) -> None:
        row = await self.session.scalar(
            select(DataboxDocumentPermissionRow).where(
                DataboxDocumentPermissionRow.document_id == permission.document_id,
                DataboxDocumentPermissionRow.user_id == permission.user_id,
            )
        )
        if row is None:
            self.session.add(
                DataboxDocumentPermissionRow(
                    id=permission.id,
                    organization_id=permission.organization_id,
                    document_id=permission.document_id,
                    user_id=permission.user_id,
                    role=permission.role,
                    granted_by=permission.granted_by,
                )
            )
        else:
            if row.organization_id != permission.organization_id:
                raise ConflictError("Document version changed")
            row.role = permission.role
            row.granted_by = permission.granted_by
        await self.session.flush()

    async def list_permissions(self, organization_id: UUID, document_id: UUID) -> list[DocumentPermission]:
        rows = (
            await self.session.scalars(
                select(DataboxDocumentPermissionRow).where(
                    DataboxDocumentPermissionRow.organization_id == organization_id,
                    DataboxDocumentPermissionRow.document_id == document_id,
                )
            )
        ).all()
        return [
            DocumentPermission(
                id=row.id,
                organization_id=row.organization_id,
                document_id=row.document_id,
                user_id=row.user_id,
                role=row.role,
                granted_by=row.granted_by,
            )
            for row in rows
        ]

    async def delete_permission(self, organization_id: UUID, document_id: UUID, user_id: UUID) -> bool:
        row = await self.session.scalar(
            select(DataboxDocumentPermissionRow).where(
                DataboxDocumentPermissionRow.organization_id == organization_id,
                DataboxDocumentPermissionRow.document_id == document_id,
                DataboxDocumentPermissionRow.user_id == user_id,
            )
        )
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def list_links(self, organization_id: UUID, source_document_id: UUID) -> list[DocumentLink]:
        rows = (
            await self.session.scalars(
                select(DataboxDocumentLinkRow).where(
                    DataboxDocumentLinkRow.organization_id == organization_id,
                    DataboxDocumentLinkRow.source_document_id == source_document_id,
                )
            )
        ).all()
        return [_link(row) for row in rows]

    async def find_link(
        self, organization_id: UUID, source_document_id: UUID, target_document_id: UUID
    ) -> DocumentLink | None:
        row = await self.session.scalar(
            select(DataboxDocumentLinkRow).where(
                DataboxDocumentLinkRow.organization_id == organization_id,
                DataboxDocumentLinkRow.source_document_id == source_document_id,
                DataboxDocumentLinkRow.target_document_id == target_document_id,
            )
        )
        return None if row is None else _link(row)

    async def save_link(self, link: DocumentLink) -> None:
        self.session.add(
            DataboxDocumentLinkRow(
                id=link.id,
                organization_id=link.organization_id,
                source_document_id=link.source_document_id,
                target_document_id=link.target_document_id,
                label=link.label,
                cascade_depth=link.cascade_depth,
                created_by=link.created_by,
                created_at=link.created_at,
            )
        )
        await self.session.flush()

    async def delete_link(self, organization_id: UUID, link_id: UUID) -> None:
        row = await self.session.scalar(
            select(DataboxDocumentLinkRow).where(
                DataboxDocumentLinkRow.id == link_id,
                DataboxDocumentLinkRow.organization_id == organization_id,
            )
        )
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()

    async def append_audit(self, event: AuditEvent) -> None:
        self.session.add(
            DataboxAuditLogRow(
                id=event.id,
                organization_id=event.organization_id,
                actor_user_id=event.actor_user_id,
                document_id=event.document_id,
                action=event.action,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                outcome=event.outcome,
                metadata_json=event.metadata,
                created_at=event.created_at,
            )
        )
        await self.session.flush()

    async def append_update(self, document_id: UUID, version_id: UUID, update: bytes) -> int:
        version = await self.session.scalar(
            select(DataboxDocumentVersionRow).where(DataboxDocumentVersionRow.id == version_id)
        )
        if version is None or version.document_id != document_id:
            raise ConflictError("Document version changed")
        current = await self.session.scalar(
            select(func.max(DataboxYjsUpdateRow.sequence)).where(
                DataboxYjsUpdateRow.document_id == document_id,
                DataboxYjsUpdateRow.version_id == version_id,
            )
        )
        sequence = int(current or 0) + 1
        self.session.add(
            DataboxYjsUpdateRow(
                id=uuid4(),
                organization_id=version.organization_id,
                document_id=document_id,
                version_id=version_id,
                sequence=sequence,
                payload=update,
            )
        )
        await self.session.flush()
        return sequence

    async def list_updates(self, document_id: UUID, version_id: UUID) -> list[bytes]:
        rows = (
            await self.session.scalars(
                select(DataboxYjsUpdateRow)
                .where(
                    DataboxYjsUpdateRow.document_id == document_id,
                    DataboxYjsUpdateRow.version_id == version_id,
                )
                .order_by(DataboxYjsUpdateRow.sequence.asc())
            )
        ).all()
        return [row.payload for row in rows]

    async def save_checkpoint(self, checkpoint: CollaborationCheckpoint) -> None:
        version = await self.session.scalar(
            select(DataboxDocumentVersionRow).where(DataboxDocumentVersionRow.id == checkpoint.version_id)
        )
        if version is None:
            return
        row = await self.session.scalar(
            select(DataboxCollaborationCheckpointRow).where(
                DataboxCollaborationCheckpointRow.document_id == checkpoint.document_id,
                DataboxCollaborationCheckpointRow.version_id == checkpoint.version_id,
            )
        )
        if row is None:
            self.session.add(
                DataboxCollaborationCheckpointRow(
                    id=uuid4(),
                    organization_id=version.organization_id,
                    document_id=checkpoint.document_id,
                    version_id=checkpoint.version_id,
                    state_version=checkpoint.state_version,
                    snapshot=checkpoint.snapshot,
                )
            )
        else:
            row.state_version = checkpoint.state_version
            row.snapshot = checkpoint.snapshot
        await self.session.flush()

    async def get_checkpoint(self, document_id: UUID, version_id: UUID) -> CollaborationCheckpoint | None:
        row = await self.session.scalar(
            select(DataboxCollaborationCheckpointRow).where(
                DataboxCollaborationCheckpointRow.document_id == document_id,
                DataboxCollaborationCheckpointRow.version_id == version_id,
            )
        )
        if row is None:
            return None
        return CollaborationCheckpoint(
            document_id=row.document_id,
            version_id=row.version_id,
            state_version=int(row.state_version),
            snapshot=row.snapshot,
        )

    async def set_render_status(self, organization_id: UUID, version_id: UUID, status: str) -> None:
        row = await self.session.scalar(
            select(DataboxDocumentVersionRow).where(
                DataboxDocumentVersionRow.id == version_id,
                DataboxDocumentVersionRow.organization_id == organization_id,
            )
        )
        if row is None:
            return
        row.render_status = status
        await self.session.flush()


def _upload(row: DataboxUploadOperationRow) -> UploadOperation:
    return UploadOperation(
        id=row.id,
        organization_id=row.organization_id,
        object_key=row.object_key,
        status=row.status,
        document_id=row.document_id,
        version_id=row.version_id,
        idempotency_key=row.idempotency_key,
        created_at=row.created_at,
    )


def _link(row: DataboxDocumentLinkRow) -> DocumentLink:
    return DocumentLink(
        id=row.id,
        organization_id=row.organization_id,
        source_document_id=row.source_document_id,
        target_document_id=row.target_document_id,
        created_by=row.created_by,
        label=row.label,
        cascade_depth=row.cascade_depth,
        created_at=row.created_at,
    )
