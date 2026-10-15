"""Add DataBox document, share, and collaboration tables.

Revision ID: d4b0c0a1e2f3
Revises: c3d4e5f6a7b8
Create Date: 2026-10-14 03:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member', 'viewer')", name="ck_memberships_role"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_memberships_org_user"),
    )
    op.create_table(
        "databox_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False, server_default="application/pdf"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("classification_level", sa.String(50), nullable=False, server_default="internal"),
        sa.Column("audience_labels", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("restricted_labels", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("policy_epoch", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'deleting', 'deleted')", name="ck_databox_documents_status"),
        sa.CheckConstraint("policy_epoch >= 1", name="ck_databox_documents_epoch"),
    )
    op.create_index("idx_databox_documents_org_status", "databox_documents", ["organization_id", "status"])
    op.create_table(
        "databox_document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("databox_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("bucket_name", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("render_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("size_bytes >= 0", name="ck_databox_versions_size"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_databox_version_number"),
        sa.UniqueConstraint("bucket_name", "object_key", name="uq_databox_object_key"),
    )
    op.create_index("idx_databox_versions_document", "databox_document_versions", ["document_id", "version_number"])
    op.create_foreign_key(
        "fk_databox_documents_current_version",
        "databox_documents",
        "databox_document_versions",
        ["current_version_id"],
        ["id"],
    )
    op.create_table(
        "databox_membership_attributes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("labels", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_databox_membership_attributes"),
    )
    op.create_table(
        "databox_document_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("databox_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('viewer', 'editor')", name="ck_databox_permission_role"),
        sa.UniqueConstraint("document_id", "user_id", name="uq_databox_document_permission"),
    )
    op.create_index("idx_databox_permissions_user", "databox_document_permissions", ["user_id", "document_id"])
    op.create_table(
        "databox_share_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("databox_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("permission", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_epoch", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("access_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("token_hash", name="uq_databox_share_token_hash"),
    )
    op.create_index("idx_databox_share_links_document", "databox_share_links", ["document_id"])
    op.create_index(
        "idx_databox_share_links_expiry",
        "databox_share_links",
        ["expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "databox_document_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("databox_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("databox_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("cascade_depth", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "databox_upload_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "databox_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_databox_audit_document_time", "databox_audit_logs", ["document_id", "created_at"])
    op.create_index("idx_databox_audit_actor_time", "databox_audit_logs", ["actor_user_id", "created_at"])
    op.create_table(
        "databox_collaboration_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("databox_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("databox_document_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("snapshot", sa.LargeBinary(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("document_id", "version_id", name="uq_databox_collab_version"),
    )
    op.create_table(
        "databox_yjs_updates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("databox_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("databox_document_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("document_id", "version_id", "sequence", name="uq_databox_yjs_sequence"),
    )


def downgrade() -> None:
    op.drop_table("databox_yjs_updates")
    op.drop_table("databox_collaboration_documents")
    op.drop_index("idx_databox_audit_actor_time", table_name="databox_audit_logs")
    op.drop_index("idx_databox_audit_document_time", table_name="databox_audit_logs")
    op.drop_table("databox_audit_logs")
    op.drop_table("databox_upload_operations")
    op.drop_table("databox_document_links")
    op.drop_index("idx_databox_share_links_expiry", table_name="databox_share_links")
    op.drop_index("idx_databox_share_links_document", table_name="databox_share_links")
    op.drop_table("databox_share_links")
    op.drop_index("idx_databox_permissions_user", table_name="databox_document_permissions")
    op.drop_table("databox_document_permissions")
    op.drop_table("databox_membership_attributes")
    op.drop_constraint("fk_databox_documents_current_version", "databox_documents", type_="foreignkey")
    op.drop_index("idx_databox_versions_document", table_name="databox_document_versions")
    op.drop_table("databox_document_versions")
    op.drop_index("idx_databox_documents_org_status", table_name="databox_documents")
    op.drop_table("databox_documents")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("organizations")
