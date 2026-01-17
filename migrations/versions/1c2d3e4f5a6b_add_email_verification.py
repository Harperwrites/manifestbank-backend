"""add email verification fields

Revision ID: 1c2d3e4f5a6b
Revises: 7f4a2c9d0b1e
Create Date: 2026-01-15
"""

from alembic import op
import sqlalchemy as sa

revision = "1c2d3e4f5a6b"
down_revision = "7f4a2c9d0b1e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("email_verification_token", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column("email_verification_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE users SET email_verified = true WHERE email_verified IS NULL")
    op.alter_column(
        "users",
        "email_verified",
        nullable=False,
        server_default=sa.text("false"),
    )


def downgrade():
    op.drop_column("users", "email_verification_expires_at")
    op.drop_column("users", "email_verification_token")
    op.drop_column("users", "email_verified")
