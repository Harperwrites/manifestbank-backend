"""add dashboard currency to users

Revision ID: c1a2b3c4d5e6
Revises: 7a1b2c3d4e5f
Create Date: 2026-03-17 15:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c1a2b3c4d5e6"
down_revision = "7a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("dashboard_currency", sa.String(), nullable=False, server_default="USD"),
    )
    op.execute("UPDATE users SET dashboard_currency = 'USD' WHERE dashboard_currency IS NULL")


def downgrade():
    op.drop_column("users", "dashboard_currency")
