"""add username, parent accounts, scheduled entries

Revision ID: 3f1c9c2a7b8e
Revises: 0e3f9a2c7d1b
Create Date: 2026-01-05
"""

from alembic import op
import sqlalchemy as sa

revision = "3f1c9c2a7b8e"
down_revision = "0e3f9a2c7d1b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("username", sa.String(), nullable=True))
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.add_column("accounts", sa.Column("parent_account_id", sa.Integer(), nullable=True))
    op.create_index("ix_accounts_parent_account_id", "accounts", ["parent_account_id"])
    op.create_foreign_key(
        "fk_accounts_parent_account_id",
        "accounts",
        "accounts",
        ["parent_account_id"],
        ["id"],
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduled_entries (
            id SERIAL PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES accounts (id),
            created_by_user_id INTEGER NOT NULL REFERENCES users (id),
            direction VARCHAR NOT NULL,
            amount NUMERIC(18, 2) NOT NULL,
            currency VARCHAR NOT NULL DEFAULT 'USD',
            entry_type VARCHAR NOT NULL DEFAULT 'scheduled',
            status VARCHAR NOT NULL DEFAULT 'pending',
            reference VARCHAR,
            memo VARCHAR,
            scheduled_for TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            posted_at TIMESTAMPTZ,
            posted_entry_id INTEGER REFERENCES ledger_entries (id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_entries_account_id ON scheduled_entries (account_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_entries_created_by_user_id ON scheduled_entries (created_by_user_id)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_scheduled_entries_created_by_user_id")
    op.execute("DROP INDEX IF EXISTS ix_scheduled_entries_account_id")
    op.execute("DROP TABLE IF EXISTS scheduled_entries")

    op.drop_constraint("fk_accounts_parent_account_id", "accounts", type_="foreignkey")
    op.drop_index("ix_accounts_parent_account_id", table_name="accounts")
    op.drop_column("accounts", "parent_account_id")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "username")
