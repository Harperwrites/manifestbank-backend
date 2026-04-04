"""add teller tables

Revision ID: 2f7c1a6b9d21
Revises: 0f3d8c7a2b11
Create Date: 2026-02-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2f7c1a6b9d21"
down_revision = "0f3d8c7a2b11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teller_threads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default="New Teller Session"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_teller_threads_user_id", "teller_threads", ["user_id"])

    op.create_table(
        "teller_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("teller_threads.id"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_teller_messages_thread_id", "teller_messages", ["thread_id"])

    op.create_table(
        "teller_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("teller_threads.id"), nullable=True),
        sa.Column("action_type", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="recorded"),
        sa.Column("action_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_teller_audit_logs_user_id", "teller_audit_logs", ["user_id"])
    op.create_index("ix_teller_audit_logs_thread_id", "teller_audit_logs", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_teller_audit_logs_thread_id", table_name="teller_audit_logs")
    op.drop_index("ix_teller_audit_logs_user_id", table_name="teller_audit_logs")
    op.drop_table("teller_audit_logs")
    op.drop_index("ix_teller_messages_thread_id", table_name="teller_messages")
    op.drop_table("teller_messages")
    op.drop_index("ix_teller_threads_user_id", table_name="teller_threads")
    op.drop_table("teller_threads")
