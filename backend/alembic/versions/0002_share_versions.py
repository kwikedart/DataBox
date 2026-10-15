"""Store the version and a sealed copy of each share link.

Revision ID: 0002_share_versions
Revises: 0001_initial
Create Date: 2026-10-15 07:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_share_versions"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "databox_share_links",
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "databox_share_links",
        sa.Column("sealed_token", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_databox_share_links_version",
        "databox_share_links",
        "databox_document_versions",
        ["version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("idx_databox_share_links_version", "databox_share_links", ["version_id"])


def downgrade() -> None:
    op.drop_index("idx_databox_share_links_version", table_name="databox_share_links")
    op.drop_constraint("fk_databox_share_links_version", "databox_share_links", type_="foreignkey")
    op.drop_column("databox_share_links", "sealed_token")
    op.drop_column("databox_share_links", "version_id")
