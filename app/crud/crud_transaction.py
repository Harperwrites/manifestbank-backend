from __future__ import annotations

from datetime import datetime, UTC
from typing import Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.transaction import Transaction
from app.models.account import Account


def get_transaction(db: Session, transaction_id: int) -> Transaction | None:
    return db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    ).scalar_one_or_none()


def _utc_now() -> datetime:
    # timezone-aware UTC datetime (Python 3.11+ supports datetime.UTC / UTC)
    return datetime.now(UTC)


def deposit(db: Session, account_id: int, amount: float, description: str | None = None) -> Transaction:
    acct = db.execute(select(Account).where(Account.id == account_id)).scalar_one()
    acct.balance += float(amount)

    txn = Transaction(
        account_id=account_id,
        amount=float(amount),
        type="deposit",
        timestamp=_utc_now(),
        description=description,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def withdraw(db: Session, account_id: int, amount: float, description: str | None = None) -> Transaction:
    acct = db.execute(select(Account).where(Account.id == account_id)).scalar_one()
    amt = float(abs(amount))
    acct.balance -= amt

    txn = Transaction(
        account_id=account_id,
        amount=-amt,
        type="withdrawal",
        timestamp=_utc_now(),
        description=description,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def transfer(
    db: Session,
    from_account_id: int,
    to_account_id: int,
    amount: float,
    description: str | None = None
) -> Tuple[Transaction, Transaction]:
    t1 = withdraw(db, from_account_id, amount, description=description or "Transfer out")
    t2 = deposit(db, to_account_id, amount, description=description or "Transfer in")
    return t1, t2
