"""Add durable email center records without changing existing data."""
from alembic import op
from app.models.email_center import EmailJob, EmailJobRecipient, EmailSenderDay, EmailCenterAudit
revision='email_center_2026'
down_revision='november_offer_2026'
branch_labels=None
depends_on=None

def upgrade():
    for model in (EmailJob,EmailJobRecipient,EmailSenderDay,EmailCenterAudit):
        model.__table__.create(bind=op.get_bind(),checkfirst=True)

def downgrade():
    raise RuntimeError('Email history removal requires explicit user permission. Nothing deleted.')
