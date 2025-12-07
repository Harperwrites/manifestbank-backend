from alembic import op
import sqlalchemy as sa

# Revision identifiers
revision = 'init_full_schema'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # USERS
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
    )

    # BANK ACCOUNT
    op.create_table(
        "bank_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("balance", sa.Float(), server_default="0.0"),
    )

    # TRANSACTIONS
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bank_account_id", sa.Integer(), sa.ForeignKey("bank_account.id")),
        sa.Column("amount", sa.Float()),
        sa.Column("type", sa.String()),
    )

    # MANIFEST GOAL
    op.create_table(
        "manifest_goal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("description", sa.String()),
        sa.Column("target_amount", sa.Float()),
    )

    # LEDGER ENTRIES
    op.create_table(
        "ledger_entry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("manifest_goal.id")),
        sa.Column("description", sa.String()),
        sa.Column("value", sa.Float()),
    )


def downgrade():
    op.drop_table("ledger_entry")
    op.drop_table("manifest_goal")
    op.drop_table("transactions")
    op.drop_table("bank_account")
    op.drop_table("users")
