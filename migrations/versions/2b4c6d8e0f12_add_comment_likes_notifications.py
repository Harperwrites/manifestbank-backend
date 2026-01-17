"""add comment likes and notifications

Revision ID: 2b4c6d8e0f12
Revises: 1c2d3e4f5a6b
Create Date: 2026-01-15
"""

from alembic import op
import sqlalchemy as sa

revision = "2b4c6d8e0f12"
down_revision = "1c2d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ether_comment_likes (
            id SERIAL PRIMARY KEY,
            comment_id INTEGER NOT NULL REFERENCES ether_comments (id),
            profile_id INTEGER NOT NULL REFERENCES profiles (id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ether_comment_like UNIQUE (comment_id, profile_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_comment_likes_comment ON ether_comment_likes (comment_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_comment_likes_profile ON ether_comment_likes (profile_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ether_notifications (
            id SERIAL PRIMARY KEY,
            recipient_profile_id INTEGER NOT NULL REFERENCES profiles (id),
            actor_profile_id INTEGER NOT NULL REFERENCES profiles (id),
            kind VARCHAR NOT NULL,
            post_id INTEGER REFERENCES ether_posts (id),
            comment_id INTEGER REFERENCES ether_comments (id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            read_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_notifications_recipient ON ether_notifications (recipient_profile_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_notifications_actor ON ether_notifications (actor_profile_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_ether_notifications_actor")
    op.execute("DROP INDEX IF EXISTS ix_ether_notifications_recipient")
    op.execute("DROP TABLE IF EXISTS ether_notifications")
    op.execute("DROP INDEX IF EXISTS ix_ether_comment_likes_profile")
    op.execute("DROP INDEX IF EXISTS ix_ether_comment_likes_comment")
    op.execute("DROP TABLE IF EXISTS ether_comment_likes")
