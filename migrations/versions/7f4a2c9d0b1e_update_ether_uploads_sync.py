"""add ether post images and sync settings

Revision ID: 7f4a2c9d0b1e
Revises: 9b2c4d7e1a0f
Create Date: 2026-01-05
"""

from alembic import op
import sqlalchemy as sa

revision = "7f4a2c9d0b1e"
down_revision = "9b2c4d7e1a0f"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS sync_requires_approval BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE ether_posts ADD COLUMN IF NOT EXISTS image_url VARCHAR")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ether_sync_requests (
            id SERIAL PRIMARY KEY,
            requester_profile_id INTEGER NOT NULL REFERENCES profiles (id),
            target_profile_id INTEGER NOT NULL REFERENCES profiles (id),
            status VARCHAR NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            responded_at TIMESTAMPTZ,
            CONSTRAINT uq_ether_sync_request UNIQUE (requester_profile_id, target_profile_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_sync_requests_requester ON ether_sync_requests (requester_profile_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ether_sync_requests_target ON ether_sync_requests (target_profile_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_ether_sync_requests_target")
    op.execute("DROP INDEX IF EXISTS ix_ether_sync_requests_requester")
    op.execute("DROP TABLE IF EXISTS ether_sync_requests")
    op.execute("ALTER TABLE ether_posts DROP COLUMN IF EXISTS image_url")
    op.execute("ALTER TABLE profiles DROP COLUMN IF EXISTS sync_requires_approval")
