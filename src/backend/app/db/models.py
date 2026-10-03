import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, ForeignKey, Integer, JSON, String,
    Text, UniqueConstraint, func,DateTime
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    google_sub: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resume_revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("resume_revision >= 0", name="ck_users_resume_revision_nonneg"),
    )


class Session(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    csrf_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)



class ResumeProfile(Base):
    __tablename__ = "resume_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    


class ResumeChunk(Base):
    __tablename__ = "resume_chunks"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True),
    ForeignKey("resume_profiles.user_id", ondelete="CASCADE"),
    nullable=False,
    index=True,
    )
    profile_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    section: Mapped[str] = mapped_column(Text, nullable=False)
    entry_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    embedding_version: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "section IN ('PROJECT','EXPERIENCE')", name="ck_resume_chunks_section"
        ),
        UniqueConstraint(
            "user_id", "section", "entry_index", "chunk_index",
            name="uq_resume_chunks_position",
        ),
    )
class SaveOperation(Base):
    __tablename__ = "save_operations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    expected_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    result_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('PROCESSING','SUCCEEDED','FAILED')",
            name="ck_save_operations_state",
        ),
    )


class ProcessingTask(Base):
    """Durable identity and fenced lease for one extraction or embedding task."""

    __tablename__ = "processing_tasks"

    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    task_key: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_data: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("owner_id", "kind", "task_key", name="uq_processing_tasks_identity"),
        CheckConstraint("kind IN ('EXTRACTION','EMBEDDING')", name="ck_processing_tasks_kind"),
        CheckConstraint(
            "state IN ('PENDING','PROCESSING','RETRY_WAIT','SUCCEEDED','FAILED','CANCELLED')",
            name="ck_processing_tasks_state",
        ),
        CheckConstraint("revision >= 0", name="ck_processing_tasks_revision_nonneg"),
        CheckConstraint("attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts",
                        name="ck_processing_tasks_attempt_bounds"),
        CheckConstraint(
            "(state = 'PROCESSING' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'PROCESSING' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_processing_tasks_lease_state",
        ),
    )


class OutboxEvent(Base):
    """One retryable publication record per stable task identity."""

    __tablename__ = "processing_outbox"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processing_tasks.task_id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("task_id", name="uq_processing_outbox_task"),
        CheckConstraint("state IN ('PENDING','CLAIMED','SENT','CANCELLED')", name="ck_processing_outbox_state"),
        CheckConstraint("attempts >= 0", name="ck_processing_outbox_attempts_nonneg"),
        CheckConstraint(
            "(state = 'CLAIMED' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'CLAIMED' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_processing_outbox_lease_state",
        ),
    )
