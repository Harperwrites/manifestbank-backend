"""add ether social tables

Revision ID: 9b2c4d7e1a0f
Revises: 6a5d9d3f2a1c
Create Date: 2026-01-05
"""

from alembic import op
import sqlalchemy as sa

revision = "9b2c4d7e1a0f"
down_revision = "6a5d9d3f2a1c"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE REFERENCES users (id),
            display_name VARCHAR NOT NULL,
            bio TEXT,
            avatar_url VARCHAR,
            is_public BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_profiles_user_id ON profiles (user_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ether_posts (
            id SERIAL PRIMARY KEY,
            author_profile_id INTEGER NOT NULL REFERENCES profiles (id),
            kind VARCHAR NOT NULL DEFAULT 'post',
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_posts_author_profile_id ON ether_posts (author_profile_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ether_comments (
            id SERIAL PRIMARY KEY,
            post_id INTEGER NOT NULL REFERENCES ether_posts (id),
            author_profile_id INTEGER NOT NULL REFERENCES profiles (id),
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_comments_post_id ON ether_comments (post_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_comments_author_profile_id ON ether_comments (author_profile_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ether_likes (
            id SERIAL PRIMARY KEY,
            post_id INTEGER NOT NULL REFERENCES ether_posts (id),
            profile_id INTEGER NOT NULL REFERENCES profiles (id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ether_like_post_profile UNIQUE (post_id, profile_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_likes_post_id ON ether_likes (post_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_likes_profile_id ON ether_likes (profile_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ether_groups (
            id SERIAL PRIMARY KEY,
            name VARCHAR NOT NULL UNIQUE,
            description TEXT,
            is_private BOOLEAN NOT NULL DEFAULT false,
            created_by_profile_id INTEGER NOT NULL REFERENCES profiles (id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_groups_created_by_profile_id ON ether_groups (created_by_profile_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ether_group_members (
            id SERIAL PRIMARY KEY,
            group_id INTEGER NOT NULL REFERENCES ether_groups (id),
            profile_id INTEGER NOT NULL REFERENCES profiles (id),
            role VARCHAR NOT NULL DEFAULT 'member',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ether_group_member UNIQUE (group_id, profile_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_group_members_group_id ON ether_group_members (group_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_group_members_profile_id ON ether_group_members (profile_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ether_threads (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ether_thread_members (
            id SERIAL PRIMARY KEY,
            thread_id INTEGER NOT NULL REFERENCES ether_threads (id),
            profile_id INTEGER NOT NULL REFERENCES profiles (id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ether_thread_member UNIQUE (thread_id, profile_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_thread_members_thread_id ON ether_thread_members (thread_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_thread_members_profile_id ON ether_thread_members (profile_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ether_messages (
            id SERIAL PRIMARY KEY,
            thread_id INTEGER NOT NULL REFERENCES ether_threads (id),
            sender_profile_id INTEGER NOT NULL REFERENCES profiles (id),
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_messages_thread_id ON ether_messages (thread_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_messages_sender_profile_id ON ether_messages (sender_profile_id)")


def downgrade():
    op.execute("DROP TABLE IF EXISTS ether_messages")
    op.execute("DROP TABLE IF EXISTS ether_thread_members")
    op.execute("DROP TABLE IF EXISTS ether_threads")
    op.execute("DROP TABLE IF EXISTS ether_group_members")
    op.execute("DROP TABLE IF EXISTS ether_groups")
    op.execute("DROP TABLE IF EXISTS ether_likes")
    op.execute("DROP TABLE IF EXISTS ether_comments")
    op.execute("DROP TABLE IF EXISTS ether_posts")
    op.execute("DROP TABLE IF EXISTS profiles")
