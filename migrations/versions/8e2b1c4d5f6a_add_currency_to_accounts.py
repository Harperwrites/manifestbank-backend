"""add currency to accounts

Revision ID: 8e2b1c4d5f6a
Revises: 7a1b2c3d4e5f
Create Date: 2026-03-17 15:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "8e2b1c4d5f6a"
down_revision = "7a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(sa.Column("currency", sa.String(), nullable=False, server_default="USD"))
    op.execute("UPDATE accounts SET currency = 'USD' WHERE currency IS NULL")


def downgrade():
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("currency")
