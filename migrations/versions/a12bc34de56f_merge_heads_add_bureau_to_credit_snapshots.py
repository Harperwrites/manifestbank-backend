"""merge heads + add bureau to credit_score_snapshots

Revision ID: a12bc34de56f
Revises: 3c9b7a1d2e01, 5b7c8d9e0f11
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "a12bc34de56f"
down_revision = ("3c9b7a1d2e01", "5b7c8d9e0f11")
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("credit_score_snapshots")]
    if "bureau" not in columns:
        with op.batch_alter_table("credit_score_snapshots") as batch_op:
            batch_op.add_column(sa.Column("bureau", sa.String(length=40), nullable=True))
        op.execute("UPDATE credit_score_snapshots SET bureau = 'composite' WHERE bureau IS NULL")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("credit_score_snapshots")]
    if "bureau" in columns:
        with op.batch_alter_table("credit_score_snapshots") as batch_op:
            batch_op.drop_column("bureau")
