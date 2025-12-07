"""seed data for manifest bank"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c40a445f9db6'
down_revision = 'init_full_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Insert User
    op.execute("""
        INSERT INTO users (name)
        VALUES ('Harper Test User');
    """)

    # Get inserted user ID
    user_id = op.get_bind().execute(sa.text("""
        SELECT id FROM users WHERE name='Harper Test User'
    """)).fetchone()[0]

    # Insert Bank Account
    op.execute(f"""
        INSERT INTO bank_account (user_id, balance)
        VALUES ({user_id}, 1000.00);
    """)

    # Get bank account ID
    bank_id = op.get_bind().execute(sa.text("""
        SELECT id FROM bank_account WHERE user_id=:uid
    """), {"uid": user_id}).fetchone()[0]

    # Insert Transactions
    op.execute(f"""
        INSERT INTO transactions (bank_account_id, amount, type)
        VALUES 
            ({bank_id}, 200.00, 'deposit'),
            ({bank_id}, -50.00, 'withdrawal');
    """)

    # Insert Manifest Goal
    op.execute(f"""
        INSERT INTO manifest_goal (user_id, description, target_amount)
        VALUES 
            ({user_id}, 'Build Manifest Bank', 1000000000);
    """)

    # Get goal ID
    goal_id = op.get_bind().execute(sa.text("""
        SELECT id FROM manifest_goal WHERE user_id=:uid
    """), {"uid": user_id}).fetchone()[0]

    # Insert Ledger Entry
    op.execute(f"""
        INSERT INTO ledger_entry (goal_id, description, value)
        VALUES 
            ({goal_id}, 'Initial energy imprint', 111.11);
    """)


def downgrade() -> None:
    # Remove seed data (reverse order)
    op.execute("DELETE FROM ledger_entry WHERE description='Initial energy imprint';")
    op.execute("DELETE FROM transactions;")
    op.execute("DELETE FROM bank_account;")
    op.execute("DELETE FROM manifest_goal WHERE description='Build Manifest Bank';")
    op.execute("DELETE FROM users WHERE name='Harper Test User';")
