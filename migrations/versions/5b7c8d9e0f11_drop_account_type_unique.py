"""drop unique constraint on account type per user

Revision ID: 5b7c8d9e0f11
Revises: 1f6d9a3b8c2e
Create Date: 2026-03-13
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "5b7c8d9e0f11"
down_revision = "1f6d9a3b8c2e"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_accounts_owner_user_id_account_type", "accounts", type_="unique")


def downgrade():
    op.create_unique_constraint(
        "uq_accounts_owner_user_id_account_type",
        "accounts",
        ["owner_user_id", "account_type"],
    )
