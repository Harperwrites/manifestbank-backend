"""add affirmations entries

Revision ID: 8b4c1d2e7a11
Revises: 7d3b1f2a9c41
Create Date: 2026-02-11 19:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8b4c1d2e7a11"
down_revision: Union[str, Sequence[str], None] = "7d3b1f2a9c41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "affirmation_entries",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("affirmation_entries")}
    if "ix_affirmation_entries_user_id" not in existing_indexes:
        op.create_index("ix_affirmation_entries_user_id", "affirmation_entries", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_affirmation_entries_user_id", table_name="affirmation_entries")
    op.drop_table("affirmation_entries")
