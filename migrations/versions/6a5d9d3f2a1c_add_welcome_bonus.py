"""add welcome bonus flag to users

Revision ID: 6a5d9d3f2a1c
Revises: 3f1c9c2a7b8e
Create Date: 2026-01-05
"""

from alembic import op
import sqlalchemy as sa

revision = "6a5d9d3f2a1c"
down_revision = "3f1c9c2a7b8e"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS welcome_bonus_claimed BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade():
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS welcome_bonus_claimed")
