"""add signature welcome email sent timestamp

Revision ID: 2a8c6e4f1b90
Revises: fa5e1d2c3b4a
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


revision = "2a8c6e4f1b90"
down_revision = "fa5e1d2c3b4a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("signature_welcome_email_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("users", "signature_welcome_email_sent_at")
