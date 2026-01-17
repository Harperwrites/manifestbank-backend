"""add role to users

Revision ID: 4fec39d9d343
Revises: dc4761b727c3
Create Date: 2026-01-01
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "4fec39d9d343"
down_revision = "dc4761b727c3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("role", sa.String(), nullable=False, server_default="user")
    )


def downgrade():
    op.drop_column("users", "role")

