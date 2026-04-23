"""add ether message likes

Revision ID: f4b5c6d7e8f9
Revises: b34cd56ef78a
Create Date: 2026-03-29
"""

from alembic import op
import sqlalchemy as sa

revision = "f4b5c6d7e8f9"
down_revision = "b34cd56ef78a"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ether_message_likes"):
        op.create_table(
            "ether_message_likes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("message_id", sa.Integer(), sa.ForeignKey("ether_messages.id"), nullable=False),
            sa.Column("profile_id", sa.Integer(), sa.ForeignKey("profiles.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("message_id", "profile_id", name="uq_ether_message_like"),
        )

    existing_indexes = {index["name"] for index in inspector.get_indexes("ether_message_likes")}
    if "ix_ether_message_likes_message_id" not in existing_indexes:
        op.create_index("ix_ether_message_likes_message_id", "ether_message_likes", ["message_id"])
    if "ix_ether_message_likes_profile_id" not in existing_indexes:
        op.create_index("ix_ether_message_likes_profile_id", "ether_message_likes", ["profile_id"])


def downgrade():
    op.drop_index("ix_ether_message_likes_profile_id", table_name="ether_message_likes")
    op.drop_index("ix_ether_message_likes_message_id", table_name="ether_message_likes")
    op.drop_table("ether_message_likes")
