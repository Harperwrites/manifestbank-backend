"""add wealth target to users

Revision ID: ab3e9c2d7f01
Revises: f2c3a4b5d6e7
Create Date: 2026-01-25 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "ab3e9c2d7f01"
down_revision = "f2c3a4b5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("users")]
    if "wealth_target_usd" not in columns:
        op.add_column("users", sa.Column("wealth_target_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("users")]
    if "wealth_target_usd" in columns:
        op.drop_column("users", "wealth_target_usd")
