# app/crud/crud_account.py

from sqlalchemy.orm import Session
from app.models.account import Account
from app.models.ledger import LedgerEntry
from app.models.transaction import Transaction
from app.models.scheduled_entry import ScheduledEntry
from app.schemas.account import AccountCreate


def get_account(db: Session, account_id: int) -> Account | None:
    return db.query(Account).filter(Account.id == account_id).first()


def user_owns_account(account: Account | None, user_id: int) -> bool:
    return bool(account) and account.owner_user_id == user_id


def create_account(db: Session, owner_user_id: int, data: AccountCreate) -> Account:
    account = Account(
        owner_user_id=owner_user_id,
        parent_account_id=data.parent_account_id,
        name=data.name,
        account_type=data.account_type,
        legal_name=data.legal_name,
        jurisdiction=data.jurisdiction,
        notes=data.notes,
        is_active=data.is_active,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def list_accounts_for_user(db: Session, owner_user_id: int) -> list[Account]:
    return (
        db.query(Account)
        .filter(Account.owner_user_id == owner_user_id)
        .order_by(Account.created_at.desc())
        .all()
    )


def update_account_name(db: Session, account: Account, name: str) -> Account:
    account.name = name
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def delete_account(db: Session, account: Account) -> None:
    child_ids = [
        row.id
        for row in db.query(Account.id)
        .filter(Account.parent_account_id == account.id)
        .all()
    ]
    target_ids = [account.id] + child_ids

    db.query(LedgerEntry).filter(LedgerEntry.account_id.in_(target_ids)).delete()
    db.query(Transaction).filter(Transaction.account_id.in_(target_ids)).delete()
    db.query(ScheduledEntry).filter(ScheduledEntry.account_id.in_(target_ids)).delete()
    db.query(Account).filter(Account.id.in_(target_ids)).delete()
    db.commit()
