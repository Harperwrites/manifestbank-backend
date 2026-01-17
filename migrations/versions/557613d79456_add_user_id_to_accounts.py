"""noop: accounts.user_id is created in the accounts table creation migration

Revision ID: 557613d79456
Revises: 09ede52a1d92
Create Date: 2026-01-02
"""

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

# revision identifiers, used by Alembic.
revision = "557613d79456"
down_revision = "09ede52a1d92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op: user_id already exists
    pass


def downgrade() -> None:
    pass

