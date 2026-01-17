"""unique account type per user

Revision ID: 49c374139b6b
Revises: 95e8d56b303b
Create Date: 2026-01-02 22:47:03.708971

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa  # noqa: F401


# revision identifiers, used by Alembic.
revision: str = "49c374139b6b"
down_revision: Union[str, Sequence[str], None] = "95e8d56b303b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # 1) Deduplicate existing accounts by (user_id, type)
    # Keep the newest (highest id), delete the rest.
    # Also remove dependent transactions for accounts we delete.
    conn.execute(sa.text("""
        WITH ranked AS (
            SELECT
                id,
                user_id,
                type,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id, type
                    ORDER BY id DESC
                ) AS rn
            FROM accounts
        ),
        to_delete AS (
            SELECT id FROM ranked WHERE rn > 1
        )
        DELETE FROM transactions
        WHERE account_id IN (SELECT id FROM to_delete);
    """))

    conn.execute(sa.text("""
        WITH ranked AS (
            SELECT
                id,
                user_id,
                type,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id, type
                    ORDER BY id DESC
                ) AS rn
            FROM accounts
        )
        DELETE FROM accounts
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1);
    """))

    # 2) Add the uniqueness guarantee going forward
    op.create_unique_constraint(
        "uq_accounts_user_id_type",
        "accounts",
        ["user_id", "type"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_accounts_user_id_type",
        "accounts",
        type_="unique",
    )
