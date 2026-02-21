"""add is_premium to users

Revision ID: 9c2f4d6e8a10
Revises: 8b4c1d2e7a11
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa


revision = "9c2f4d6e8a10"
down_revision = "8b4c1d2e7a11"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("is_premium", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.alter_column("users", "is_premium", server_default=None)


def downgrade():
    op.drop_column("users", "is_premium")
