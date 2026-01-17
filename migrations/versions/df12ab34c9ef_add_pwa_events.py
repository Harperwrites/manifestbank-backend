"""add pwa events

Revision ID: df12ab34c9ef
Revises: 2b4c6d8e0f12
Create Date: 2026-01-16
"""

from alembic import op
import sqlalchemy as sa


revision = "df12ab34c9ef"
down_revision = "2b4c6d8e0f12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pwa_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("install_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("install_id", "event_type", name="uq_pwa_event_install_type"),
    )
    op.create_index("ix_pwa_events_install_id", "pwa_events", ["install_id"])
    op.create_index("ix_pwa_events_event_type", "pwa_events", ["event_type"])
    op.create_index("ix_pwa_events_user_id", "pwa_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_pwa_events_user_id", table_name="pwa_events")
    op.drop_index("ix_pwa_events_event_type", table_name="pwa_events")
    op.drop_index("ix_pwa_events_install_id", table_name="pwa_events")
    op.drop_table("pwa_events")
