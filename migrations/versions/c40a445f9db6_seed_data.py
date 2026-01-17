"""seed data for manifest bank"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c40a445f9db6"
down_revision = "init_full_schema"
branch_labels = None
depends_on = None

SEED_EMAIL = "harper.test@example.com"
SEED_ROLE = "user"
SEED_ACCOUNT_TYPE = "checking"   # must satisfy your app's expectations
SEED_BALANCE = 1000.00

TXN_1 = {"amount": 200.00, "type": "deposit", "description": "Seed deposit"}
TXN_2 = {"amount": -50.00, "type": "withdrawal", "description": "Seed withdrawal"}


def upgrade() -> None:
    conn = op.get_bind()

    # 1) Insert user (only if not exists)
    # NOTE: hashed_password must be non-null; we use a deterministic placeholder string.
    # Replace with a real bcrypt hash later if your login flow validates it.
    conn.execute(
        sa.text("""
            INSERT INTO users (email, hashed_password, is_active, role)
            SELECT :email, :hashed_password, true, :role
            WHERE NOT EXISTS (SELECT 1 FROM users WHERE email = :email);
        """),
        {
            "email": SEED_EMAIL,
            "hashed_password": "$2b$12$fvGly.Uz6HoPaG2ZYrSnQuAMWSbt0qNJWFl1/ZmECRiOOvqsvPJHS",
            "role": SEED_ROLE,
        },
    )

    user_id = conn.execute(
        sa.text("SELECT id FROM users WHERE email = :email"),
        {"email": SEED_EMAIL},
    ).scalar_one()

    # 2) Insert account (only if not exists for this seed type)
    conn.execute(
        sa.text("""
            INSERT INTO accounts (user_id, type, balance)
            SELECT :uid, :atype, :bal
            WHERE NOT EXISTS (
                SELECT 1 FROM accounts WHERE user_id = :uid AND type = :atype
            );
        """),
        {"uid": user_id, "atype": SEED_ACCOUNT_TYPE, "bal": SEED_BALANCE},
    )

    account_id = conn.execute(
        sa.text("""
            SELECT id FROM accounts
            WHERE user_id = :uid AND type = :atype
            ORDER BY id DESC
            LIMIT 1
        """),
        {"uid": user_id, "atype": SEED_ACCOUNT_TYPE},
    ).scalar_one()

    # 3) Insert transactions (idempotent-ish: avoid duplicates by matching key fields)
    # timestamp is required, so we use NOW()
    conn.execute(
        sa.text("""
            INSERT INTO transactions (account_id, amount, type, timestamp, description)
            SELECT :aid, :amt, :ttype, NOW(), :desc
            WHERE NOT EXISTS (
                SELECT 1 FROM transactions
                WHERE account_id = :aid
                  AND amount = :amt
                  AND type = :ttype
                  AND COALESCE(description, '') = COALESCE(:desc, '')
            );
        """),
        {"aid": account_id, "amt": TXN_1["amount"], "ttype": TXN_1["type"], "desc": TXN_1["description"]},
    )

    conn.execute(
        sa.text("""
            INSERT INTO transactions (account_id, amount, type, timestamp, description)
            SELECT :aid, :amt, :ttype, NOW(), :desc
            WHERE NOT EXISTS (
                SELECT 1 FROM transactions
                WHERE account_id = :aid
                  AND amount = :amt
                  AND type = :ttype
                  AND COALESCE(description, '') = COALESCE(:desc, '')
            );
        """),
        {"aid": account_id, "amt": TXN_2["amount"], "ttype": TXN_2["type"], "desc": TXN_2["description"]},
    )


def downgrade() -> None:
    conn = op.get_bind()

    user_id = conn.execute(
        sa.text("SELECT id FROM users WHERE email = :email"),
        {"email": SEED_EMAIL},
    ).scalar_one_or_none()

    if user_id is None:
        return

    account_id = conn.execute(
        sa.text("""
            SELECT id FROM accounts
            WHERE user_id = :uid AND type = :atype
            ORDER BY id DESC
            LIMIT 1
        """),
        {"uid": user_id, "atype": SEED_ACCOUNT_TYPE},
    ).scalar_one_or_none()

    if account_id is not None:
        # Delete only the seeded transactions for this account
        conn.execute(
            sa.text("""
                DELETE FROM transactions
                WHERE account_id = :aid
                  AND (
                        (amount = :a1 AND type = :t1 AND COALESCE(description,'') = COALESCE(:d1,''))
                     OR (amount = :a2 AND type = :t2 AND COALESCE(description,'') = COALESCE(:d2,''))
                  );
            """),
            {
                "aid": account_id,
                "a1": TXN_1["amount"], "t1": TXN_1["type"], "d1": TXN_1["description"],
                "a2": TXN_2["amount"], "t2": TXN_2["type"], "d2": TXN_2["description"],
            },
        )

        # Delete the seeded account
        conn.execute(
            sa.text("DELETE FROM accounts WHERE id = :aid;"),
            {"aid": account_id},
        )

    # Delete the seeded user
    conn.execute(
        sa.text("DELETE FROM users WHERE id = :uid;"),
        {"uid": user_id},
    )
