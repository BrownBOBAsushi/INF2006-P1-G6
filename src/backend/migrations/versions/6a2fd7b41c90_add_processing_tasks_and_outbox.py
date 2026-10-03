"""add durable processing tasks and transactional outbox

Revision ID: 6a2fd7b41c90
Revises: c1a7d3f09b52
Create Date: 2026-10-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6a2fd7b41c90"
down_revision: Union[str, Sequence[str], None] = "c1a7d3f09b52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processing_tasks",
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("task_key", sa.Text(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("payload_ref", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('EXTRACTION','EMBEDDING')", name="ck_processing_tasks_kind"),
        sa.CheckConstraint(
            "state IN ('PENDING','PROCESSING','RETRY_WAIT','SUCCEEDED','FAILED','CANCELLED')",
            name="ck_processing_tasks_state",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_processing_tasks_revision_nonneg"),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts",
            name="ck_processing_tasks_attempt_bounds",
        ),
        sa.CheckConstraint(
            "(state = 'PROCESSING' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'PROCESSING' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_processing_tasks_lease_state",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id"),
        sa.UniqueConstraint("owner_id", "kind", "task_key", name="uq_processing_tasks_identity"),
    )
    op.create_index("ix_processing_tasks_owner_id", "processing_tasks", ["owner_id"])
    op.create_index("ix_processing_tasks_due", "processing_tasks", ["state", "available_at", "lease_expires_at"])

    op.create_table(
        "processing_outbox",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("state", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("state IN ('PENDING','CLAIMED','SENT','CANCELLED')", name="ck_processing_outbox_state"),
        sa.CheckConstraint("attempts >= 0", name="ck_processing_outbox_attempts_nonneg"),
        sa.CheckConstraint(
            "(state = 'CLAIMED' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'CLAIMED' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_processing_outbox_lease_state",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["processing_tasks.task_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("task_id", name="uq_processing_outbox_task"),
    )
    op.create_index("ix_processing_outbox_due", "processing_outbox", ["state", "available_at", "lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_processing_outbox_due", table_name="processing_outbox")
    op.drop_table("processing_outbox")
    op.drop_index("ix_processing_tasks_due", table_name="processing_tasks")
    op.drop_index("ix_processing_tasks_owner_id", table_name="processing_tasks")
    op.drop_table("processing_tasks")
