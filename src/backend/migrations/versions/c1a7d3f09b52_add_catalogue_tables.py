"""add catalogue tables (jobs, job_requirements, requirement_embeddings, app_state)

Revision ID: c1a7d3f09b52
Revises: e378f7a1a884
Create Date: 2026-09-21

Forward-only addition per DATA_API_CONTRACT.md. Does not touch any existing table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision: str = 'c1a7d3f09b52'
down_revision: Union[str, Sequence[str], None] = 'e378f7a1a884'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('jobs',
        sa.Column('job_id', sa.UUID(), nullable=False),
        sa.Column('source', sa.String(length=80), nullable=False),
        sa.Column('source_job_id', sa.Text(), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('company_name', sa.String(length=200), nullable=False),
        sa.Column('country_code', sa.String(length=2), nullable=False),
        sa.Column('location', sa.String(length=300), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('apply_url', sa.Text(), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('job_type', sa.Text(), nullable=False),
        sa.Column('employment_time', sa.Text(), nullable=False),
        sa.Column('work_arrangement', sa.Text(), nullable=False),
        sa.Column('eligibility_notes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_imported_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("job_type IN ('INTERNSHIP','OTHER','UNKNOWN')", name='ck_jobs_job_type'),
        sa.CheckConstraint("employment_time IN ('FULL_TIME','PART_TIME','UNKNOWN')", name='ck_jobs_employment_time'),
        sa.CheckConstraint("work_arrangement IN ('ON_SITE','HYBRID','REMOTE','UNKNOWN')", name='ck_jobs_work_arrangement'),
        sa.CheckConstraint("country_code ~ '^[A-Z]{2}$'", name='ck_jobs_country_code'),
        sa.PrimaryKeyConstraint('job_id'),
        sa.UniqueConstraint('source', 'source_job_id', name='uq_jobs_source_identity'),
    )
    op.create_index('ix_jobs_active_posted', 'jobs', ['is_active', sa.text('posted_at DESC NULLS LAST'), 'job_id'])

    op.create_table('job_requirements',
        sa.Column('requirement_id', sa.UUID(), nullable=False),
        sa.Column('job_id', sa.UUID(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('requirement_text', sa.Text(), nullable=False),
        sa.Column('importance', sa.Text(), nullable=False),
        sa.Column('alternatives', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('source_quote', sa.Text(), nullable=False),
        sa.Column('evidence_skills', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.CheckConstraint("importance IN ('REQUIRED','PREFERRED')", name='ck_job_requirements_importance'),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.job_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('requirement_id'),
        sa.UniqueConstraint('job_id', 'ordinal', name='uq_job_requirements_ordinal'),
    )

    op.create_table('requirement_embeddings',
        sa.Column('embedding_id', sa.UUID(), nullable=False),
        sa.Column('requirement_id', sa.UUID(), nullable=False),
        sa.Column('alternative_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(384), nullable=False),
        sa.Column('embedding_version', sa.Text(), nullable=False),
        sa.CheckConstraint('alternative_index >= 0', name='ck_requirement_embeddings_alt_nonneg'),
        sa.ForeignKeyConstraint(['requirement_id'], ['job_requirements.requirement_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('embedding_id'),
        sa.UniqueConstraint('requirement_id', 'alternative_index', name='uq_requirement_embeddings_alt'),
    )
    op.create_index('ix_requirement_embeddings_requirement_id', 'requirement_embeddings', ['requirement_id'])

    op.create_table('app_state',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('catalogue_revision', sa.BigInteger(), server_default='0', nullable=False),
        sa.CheckConstraint('id = 1', name='ck_app_state_singleton'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute("INSERT INTO app_state (id, catalogue_revision) VALUES (1, 0)")


def downgrade() -> None:
    op.drop_table('app_state')
    op.drop_index('ix_requirement_embeddings_requirement_id', table_name='requirement_embeddings')
    op.drop_table('requirement_embeddings')
    op.drop_table('job_requirements')
    op.drop_index('ix_jobs_active_posted', table_name='jobs')
    op.drop_table('jobs')
