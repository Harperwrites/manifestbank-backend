"""add ether message indexes

Revision ID: 1f6d9a3b8c2e
Revises: c48639d8969f, dc4761b727c3
Create Date: 2026-03-12 11:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "1f6d9a3b8c2e"
down_revision: Union[str, Sequence[str], None] = ("c48639d8969f", "dc4761b727c3")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_ether_messages_thread_created_at",
        "ether_messages",
        ["thread_id", "created_at"],
    )
    op.create_index(
        "ix_ether_thread_members_profile_thread",
        "ether_thread_members",
        ["profile_id", "thread_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ether_thread_members_profile_thread", table_name="ether_thread_members")
    op.drop_index("ix_ether_messages_thread_created_at", table_name="ether_messages")
