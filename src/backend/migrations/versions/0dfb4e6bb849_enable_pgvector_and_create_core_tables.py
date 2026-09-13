"""enable pgvector and create core tables

Revision ID: 0dfb4e6bb849
Revises: 
Create Date: 2026-09-13 13:32:16.608550

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '0dfb4e6bb849'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table('users',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('google_sub', sa.Text(), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=True),
    sa.Column('resume_revision', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('resume_revision >= 0', name='ck_users_resume_revision_nonneg'),
    sa.PrimaryKeyConstraint('user_id'),
    sa.UniqueConstraint('google_sub')
    )
    op.create_table('resume_profiles',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('revision', sa.BigInteger(), nullable=False),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('embedding_version', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('sessions',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('csrf_token', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_active_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_table('resume_chunks',
    sa.Column('chunk_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('profile_revision', sa.BigInteger(), nullable=False),
    sa.Column('section', sa.Text(), nullable=False),
    sa.Column('entry_index', sa.Integer(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('embedding', Vector(384), nullable=False),
    sa.Column('embedding_version', sa.Text(), nullable=False),
    sa.CheckConstraint("section IN ('PROJECT','EXPERIENCE')", name='ck_resume_chunks_section'),
    sa.ForeignKeyConstraint(['user_id'], ['resume_profiles.user_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('chunk_id'),
    sa.UniqueConstraint('user_id', 'section', 'entry_index', 'chunk_index', name='uq_resume_chunks_position')
    )
    op.create_index('ix_resume_chunks_user_id', 'resume_chunks', ['user_id'])
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_resume_chunks_user_id', table_name='resume_chunks')
    op.drop_table('resume_chunks')
    op.drop_table('sessions')
    op.drop_table('resume_profiles')
    op.drop_table('users')
    op.execute("DROP EXTENSION IF EXISTS vector")
    # ### end Alembic commands ###