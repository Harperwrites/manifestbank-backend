"""align accounts schema with owner_user_id model

Revision ID: c8a1f7c2b9d1
Revises: 49c374139b6b
Create Date: 2026-01-05
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c8a1f7c2b9d1"
down_revision = "49c374139b6b"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_accounts_user_id_type", "accounts", type_="unique")
    op.alter_column("accounts", "user_id", new_column_name="owner_user_id")
    op.alter_column("accounts", "type", new_column_name="account_type")

    op.add_column("accounts", sa.Column("name", sa.String(), nullable=True))
    op.add_column("accounts", sa.Column("legal_name", sa.String(), nullable=True))
    op.add_column("accounts", sa.Column("jurisdiction", sa.String(), nullable=True))
    op.add_column("accounts", sa.Column("notes", sa.String(), nullable=True))
    op.add_column(
        "accounts",
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
    )

    op.execute(
        "UPDATE accounts SET name = COALESCE(name, account_type) WHERE name IS NULL"
    )
    op.execute("UPDATE accounts SET is_active = true WHERE is_active IS NULL")
    op.execute("UPDATE accounts SET created_at = now() WHERE created_at IS NULL")

    op.alter_column("accounts", "name", nullable=False)
    op.alter_column("accounts", "account_type", nullable=False)
    op.alter_column("accounts", "owner_user_id", nullable=False)
    op.alter_column("accounts", "is_active", nullable=False)
    op.alter_column("accounts", "created_at", nullable=False)

    op.create_unique_constraint(
        "uq_accounts_owner_user_id_account_type",
        "accounts",
        ["owner_user_id", "account_type"],
    )


def downgrade():
    op.drop_constraint(
        "uq_accounts_owner_user_id_account_type", "accounts", type_="unique"
    )

    op.alter_column("accounts", "owner_user_id", new_column_name="user_id")
    op.alter_column("accounts", "account_type", new_column_name="type")

    op.drop_column("accounts", "created_at")
    op.drop_column("accounts", "is_active")
    op.drop_column("accounts", "notes")
    op.drop_column("accounts", "jurisdiction")
    op.drop_column("accounts", "legal_name")
    op.drop_column("accounts", "name")

    op.create_unique_constraint(
        "uq_accounts_user_id_type", "accounts", ["user_id", "type"]
    )
