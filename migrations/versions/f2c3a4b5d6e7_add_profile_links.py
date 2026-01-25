"""add profile links

Revision ID: f2c3a4b5d6e7
Revises: e7c1b3d4f5a6
Create Date: 2026-01-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2c3a4b5d6e7"
down_revision = "e7c1b3d4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("links", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "links")
