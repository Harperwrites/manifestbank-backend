"""add legal acceptance history

Revision ID: fa5e1d2c3b4a
Revises: f4b5c6d7e8f9
Create Date: 2026-04-05 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "fa5e1d2c3b4a"
down_revision = "f4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("legal_acceptances"):
        op.create_table(
            "legal_acceptances",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("document_type", sa.String(), nullable=False),
            sa.Column("version", sa.String(), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "document_type", "version", name="uq_legal_acceptance_user_doc_version"),
        )

    existing_indexes = {index["name"] for index in inspector.get_indexes("legal_acceptances")}
    if "ix_legal_acceptances_id" not in existing_indexes:
        op.create_index(op.f("ix_legal_acceptances_id"), "legal_acceptances", ["id"], unique=False)
    if "ix_legal_acceptances_user_id" not in existing_indexes:
        op.create_index(op.f("ix_legal_acceptances_user_id"), "legal_acceptances", ["user_id"], unique=False)

    op.execute(
        """
        INSERT INTO legal_acceptances (user_id, document_type, version, accepted_at)
        SELECT id, 'terms', terms_version, terms_accepted_at
        FROM users
        WHERE terms_version IS NOT NULL AND terms_accepted_at IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM legal_acceptances
            WHERE legal_acceptances.user_id = users.id
            AND legal_acceptances.document_type = 'terms'
            AND legal_acceptances.version = users.terms_version
        )
        """
    )
    op.execute(
        """
        INSERT INTO legal_acceptances (user_id, document_type, version, accepted_at)
        SELECT id, 'privacy', privacy_version, privacy_accepted_at
        FROM users
        WHERE privacy_version IS NOT NULL AND privacy_accepted_at IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM legal_acceptances
            WHERE legal_acceptances.user_id = users.id
            AND legal_acceptances.document_type = 'privacy'
            AND legal_acceptances.version = users.privacy_version
        )
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_legal_acceptances_user_id"), table_name="legal_acceptances")
    op.drop_index(op.f("ix_legal_acceptances_id"), table_name="legal_acceptances")
    op.drop_table("legal_acceptances")
