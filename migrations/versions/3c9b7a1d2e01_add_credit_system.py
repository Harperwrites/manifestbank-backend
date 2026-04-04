"""add credit system

Revision ID: 3c9b7a1d2e01
Revises: 2f7c1a6b9d21
Create Date: 2026-02-27 19:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "3c9b7a1d2e01"
down_revision = "2f7c1a6b9d21"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "credit_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("primary_bureau", sa.String(length=40), nullable=False),
        sa.Column("secondary_bureau", sa.String(length=40), nullable=True),
        sa.Column("confirmation_copy", sa.String(length=200), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=True),
        sa.Column("action_route", sa.String(length=120), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_credit_actions_id"), "credit_actions", ["id"], unique=False)
    op.create_index(op.f("ix_credit_actions_action_type"), "credit_actions", ["action_type"], unique=False)

    op.create_table(
        "credit_action_completions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["action_id"], ["credit_actions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_credit_action_completions_id"), "credit_action_completions", ["id"], unique=False)
    op.create_index(op.f("ix_credit_action_completions_user_id"), "credit_action_completions", ["user_id"], unique=False)
    op.create_index(op.f("ix_credit_action_completions_action_id"), "credit_action_completions", ["action_id"], unique=False)

    op.create_table(
        "credit_score_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("bureau", sa.String(length=40), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_credit_score_snapshots_id"), "credit_score_snapshots", ["id"], unique=False)
    op.create_index(op.f("ix_credit_score_snapshots_user_id"), "credit_score_snapshots", ["user_id"], unique=False)

    op.create_table(
        "credit_todos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["action_id"], ["credit_actions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_credit_todos_id"), "credit_todos", ["id"], unique=False)
    op.create_index(op.f("ix_credit_todos_user_id"), "credit_todos", ["user_id"], unique=False)
    op.create_index(op.f("ix_credit_todos_action_id"), "credit_todos", ["action_id"], unique=False)
    op.create_index(op.f("ix_credit_todos_action_type"), "credit_todos", ["action_type"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_credit_todos_action_type"), table_name="credit_todos")
    op.drop_index(op.f("ix_credit_todos_action_id"), table_name="credit_todos")
    op.drop_index(op.f("ix_credit_todos_user_id"), table_name="credit_todos")
    op.drop_index(op.f("ix_credit_todos_id"), table_name="credit_todos")
    op.drop_table("credit_todos")

    op.drop_index(op.f("ix_credit_score_snapshots_user_id"), table_name="credit_score_snapshots")
    op.drop_index(op.f("ix_credit_score_snapshots_id"), table_name="credit_score_snapshots")
    op.drop_table("credit_score_snapshots")

    op.drop_index(op.f("ix_credit_action_completions_action_id"), table_name="credit_action_completions")
    op.drop_index(op.f("ix_credit_action_completions_user_id"), table_name="credit_action_completions")
    op.drop_index(op.f("ix_credit_action_completions_id"), table_name="credit_action_completions")
    op.drop_table("credit_action_completions")

    op.drop_index(op.f("ix_credit_actions_action_type"), table_name="credit_actions")
    op.drop_index(op.f("ix_credit_actions_id"), table_name="credit_actions")
    op.drop_table("credit_actions")
