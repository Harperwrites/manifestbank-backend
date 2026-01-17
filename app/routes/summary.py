# app/routes/summary.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.account import Account
from app.models.ledger import LedgerEntry

router = APIRouter(tags=["summary"])

# Private console • identity-bound • ledger-ready


@router.get("/summary")
def get_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Accounts owned by user
    account_ids_subq = (
        db.query(Account.id)
        .filter(Account.owner_user_id == current_user.id)
        .subquery()
    )

    accounts_count = (
        db.query(func.count(Account.id))
        .filter(Account.owner_user_id == current_user.id)
        .scalar()
        or 0
    )

    ledger_count = (
        db.query(func.count(LedgerEntry.id))
        .filter(LedgerEntry.account_id.in_(account_ids_subq))
        .scalar()
        or 0
    )

    return {
        "accounts_count": int(accounts_count),
        "ledger_entries_count": int(ledger_count),
    }
