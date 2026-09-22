"""SQLAlchemy models for the catalogue tables (DATA_API_CONTRACT.md). Same Base as app.db.models."""
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
    func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_job_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    location: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    apply_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    employment_time: Mapped[str] = mapped_column(Text, nullable=False)
    work_arrangement: Mapped[str] = mapped_column(Text, nullable=False)
    eligibility_notes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "source_job_id", name="uq_jobs_source_identity"),
        CheckConstraint("job_type IN ('INTERNSHIP','OTHER','UNKNOWN')", name="ck_jobs_job_type"),
        CheckConstraint("employment_time IN ('FULL_TIME','PART_TIME','UNKNOWN')", name="ck_jobs_employment_time"),
        CheckConstraint("work_arrangement IN ('ON_SITE','HYBRID','REMOTE','UNKNOWN')", name="ck_jobs_work_arrangement"),
        CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="ck_jobs_country_code"),
        Index("ix_jobs_active_posted", "is_active", text("posted_at DESC NULLS LAST"), "job_id"),
    )


class JobRequirement(Base):
    __tablename__ = "job_requirements"

    requirement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    requirement_text: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[str] = mapped_column(Text, nullable=False)
    alternatives: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    source_quote: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_skills: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    __table_args__ = (
        UniqueConstraint("job_id", "ordinal", name="uq_job_requirements_ordinal"),
        CheckConstraint("importance IN ('REQUIRED','PREFERRED')", name="ck_job_requirements_importance"),
    )


class RequirementEmbedding(Base):
    __tablename__ = "requirement_embeddings"

    embedding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_requirements.requirement_id", ondelete="CASCADE"), nullable=False)
    alternative_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    embedding_version: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("requirement_id", "alternative_index", name="uq_requirement_embeddings_alt"),
        CheckConstraint("alternative_index >= 0", name="ck_requirement_embeddings_alt_nonneg"),
        Index("ix_requirement_embeddings_requirement_id", "requirement_id"),
    )


class AppState(Base):
    __tablename__ = "app_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    catalogue_revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    __table_args__ = (CheckConstraint("id = 1", name="ck_app_state_singleton"),)
