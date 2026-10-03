"""add expiring extraction result payloads

Revision ID: 1f02c7a89d31
Revises: 6a2fd7b41c90
Create Date: 2026-10-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "1f02c7a89d31"
down_revision: Union[str, Sequence[str], None] = "6a2fd7b41c90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("processing_tasks", sa.Column("result_data", postgresql.JSONB(), nullable=True))
    op.add_column("processing_tasks", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("processing_tasks", "expires_at")
    op.drop_column("processing_tasks", "result_data")
