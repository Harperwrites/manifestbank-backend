"""merge heads

Revision ID: c48639d8969f
Revises: 09ede52a1d92, 557613d79456
Create Date: 2026-01-02 01:41:13.365221

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c48639d8969f'
down_revision: Union[str, Sequence[str], None] = ('09ede52a1d92', '557613d79456')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
