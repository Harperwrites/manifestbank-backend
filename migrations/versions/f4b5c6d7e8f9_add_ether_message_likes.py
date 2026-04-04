"""add ether message likes

Revision ID: f4b5c6d7e8f9
Revises: b34cd56ef78a
Create Date: 2026-03-29
"""

from alembic import op

revision = "f4b5c6d7e8f9"
down_revision = "b34cd56ef78a"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ether_message_likes (
            id SERIAL PRIMARY KEY,
            message_id INTEGER NOT NULL REFERENCES ether_messages (id),
            profile_id INTEGER NOT NULL REFERENCES profiles (id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ether_message_like UNIQUE (message_id, profile_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_message_likes_message_id ON ether_message_likes (message_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_message_likes_profile_id ON ether_message_likes (profile_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS ether_message_likes")
