"""Add promotion login counters, email dispatch history and opt-outs. No existing data changed."""
from alembic import op
import sqlalchemy as sa
revision = 'november_offer_2026'
# Independent of Seed Bank so the promotion can be released on its own.
down_revision = ('557613d79456', '2a8c6e4f1b90', '7d3b1f2a9c41', '95e8d56b303b', 'c40a445f9db6')
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if 'promotion_logins' not in existing:
        op.create_table('promotion_logins', sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True), sa.Column('is_new_signup', sa.Boolean(), nullable=False), sa.Column('login_count', sa.Integer(), nullable=False), sa.Column('last_login_at', sa.DateTime(timezone=True)))
    if 'promotion_emails' not in existing:
        op.create_table('promotion_emails', sa.Column('id', sa.Integer(), primary_key=True), sa.Column('campaign', sa.String(80), nullable=False), sa.Column('email', sa.String(320), nullable=False), sa.Column('status', sa.String(30), nullable=False), sa.Column('sent_at', sa.DateTime(timezone=True)), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint('campaign', 'email'))
    if 'promotion_opt_outs' not in existing:
        op.create_table('promotion_opt_outs', sa.Column('email', sa.String(320), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    raise RuntimeError('Removing promotion history requires explicit permission. No data deleted.')
