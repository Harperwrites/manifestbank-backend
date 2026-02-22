"""add stripe fields to users

Revision ID: 0f3d8c7a2b11
Revises: 9c2f4d6e8a10
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0f3d8c7a2b11"
down_revision = "9c2f4d6e8a10"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("stripe_customer_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("stripe_subscription_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("stripe_price_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("stripe_status", sa.String(), nullable=True))
    op.add_column("users", sa.Column("stripe_current_period_end", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("stripe_trial_end", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("stripe_cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column("users", "stripe_cancel_at_period_end", server_default=None)
    op.create_index("ix_users_stripe_customer_id", "users", ["stripe_customer_id"])
    op.create_index("ix_users_stripe_subscription_id", "users", ["stripe_subscription_id"])


def downgrade():
    op.drop_index("ix_users_stripe_subscription_id", table_name="users")
    op.drop_index("ix_users_stripe_customer_id", table_name="users")
    op.drop_column("users", "stripe_cancel_at_period_end")
    op.drop_column("users", "stripe_trial_end")
    op.drop_column("users", "stripe_current_period_end")
    op.drop_column("users", "stripe_status")
    op.drop_column("users", "stripe_price_id")
    op.drop_column("users", "stripe_subscription_id")
    op.drop_column("users", "stripe_customer_id")
