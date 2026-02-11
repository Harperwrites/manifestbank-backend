"""add deleted_at to ether_thread_members

Revision ID: 7d3b1f2a9c41
Revises: ef3c2b9b7b1a
Create Date: 2026-02-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7d3b1f2a9c41'
down_revision = 'ef3c2b9b7b1a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ether_thread_members', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_ether_thread_members_deleted_at', 'ether_thread_members', ['deleted_at'])


def downgrade():
    op.drop_index('ix_ether_thread_members_deleted_at', table_name='ether_thread_members')
    op.drop_column('ether_thread_members', 'deleted_at')
