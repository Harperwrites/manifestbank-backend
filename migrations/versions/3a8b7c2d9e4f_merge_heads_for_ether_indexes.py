"""merge heads for ether indexes

Revision ID: 3a8b7c2d9e4f
Revises: c48639d8969f, dc4761b727c3
Create Date: 2026-03-13 03:50:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "3a8b7c2d9e4f"
down_revision: Union[str, Sequence[str], None] = ("c48639d8969f", "dc4761b727c3")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
