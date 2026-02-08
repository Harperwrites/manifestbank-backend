"""add legal acceptance fields

Revision ID: ef3c2b9b7b1a
Revises: ab3e9c2d7f01
Create Date: 2026-02-08 00:12:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'ef3c2b9b7b1a'
down_revision = 'ab3e9c2d7f01'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('terms_accepted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('privacy_accepted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('terms_version', sa.String(), nullable=True))
    op.add_column('users', sa.Column('privacy_version', sa.String(), nullable=True))


def downgrade():
    op.drop_column('users', 'privacy_version')
    op.drop_column('users', 'terms_version')
    op.drop_column('users', 'privacy_accepted_at')
    op.drop_column('users', 'terms_accepted_at')
