"""Labels record who created them, their tag, and who assigned them.

Revision ID: 0004_label_directory
Revises: 0003_document_visibility
Create Date: 2026-10-17 05:00:00.000000 
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_label_directory"
down_revision: Union[str, Sequence[str], None] = "0003_document_visibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "databox_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("tag", sa.String(length=64), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_databox_labels_org_name"),
    )
    op.create_table(
        "databox_label_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("databox_labels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("label_id", "user_id", name="uq_databox_label_assignment"),
    )
    op.create_index("ix_databox_label_assignments_user", "databox_label_assignments", ["organization_id", "user_id"])
    op.execute(
        """
        INSERT INTO databox_labels (id, organization_id, name, tag, created_by)
        SELECT gen_random_uuid(), organization_id, label_name, 'imported', NULL
        FROM (
            SELECT DISTINCT organization_id, btrim(lower(label_name)) AS label_name
            FROM databox_membership_attributes
            CROSS JOIN LATERAL unnest(labels) AS label_name
        ) existing
        WHERE label_name <> '' AND position(' ' in label_name) = 0 AND char_length(label_name) <= 64
        """
    )
    op.execute(
        """
        INSERT INTO databox_label_assignments (id, organization_id, label_id, user_id, assigned_by)
        SELECT gen_random_uuid(), attributes.organization_id, labels.id, attributes.user_id, NULL
        FROM databox_membership_attributes AS attributes
        CROSS JOIN LATERAL unnest(attributes.labels) AS label_name
        JOIN databox_labels AS labels
          ON labels.organization_id = attributes.organization_id
         AND labels.name = btrim(lower(label_name))
        ON CONFLICT (label_id, user_id) DO NOTHING
        """
    )
    op.execute("UPDATE databox_membership_attributes SET labels = '{}'")


def downgrade() -> None:
    op.drop_index("ix_databox_label_assignments_user", table_name="databox_label_assignments")
    op.drop_table("databox_label_assignments")
    op.drop_table("databox_labels")
