"""add wealth target to users

Revision ID: ab3e9c2d7f01
Revises: f2c3a4b5d6e7
Create Date: 2026-01-25 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "ab3e9c2d7f01"
down_revision = "f2c3a4b5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("wealth_target_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "wealth_target_usd")
