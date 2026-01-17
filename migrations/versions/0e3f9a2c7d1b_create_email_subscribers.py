"""create email subscribers table

Revision ID: 0e3f9a2c7d1b
Revises: c8a1f7c2b9d1
Create Date: 2026-01-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0e3f9a2c7d1b"
down_revision = "c8a1f7c2b9d1"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_subscribers (
            id SERIAL PRIMARY KEY,
            email VARCHAR NOT NULL,
            source VARCHAR,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_email_subscribers_email ON email_subscribers (email)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_email_subscribers_email")
    op.execute("DROP TABLE IF EXISTS email_subscribers")
