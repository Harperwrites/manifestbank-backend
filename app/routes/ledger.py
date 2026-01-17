# app/routes/ledger.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, UTC

from app.db.session import get_db
from app.core.security import get_current_user, get_verified_user
from app.schemas.ledger import LedgerEntryCreate, LedgerEntryRead, BalanceRead, TransferCreate
from app.crud.crud_ledger import create_ledger_entry, list_ledger_entries, get_account_balance, create_transfer
from app.crud.crud_account import get_account

router = APIRouter(tags=["ledger"])


def is_admin(user) -> bool:
    return getattr(user, "role", None) == "admin"


@router.post("/ledger/entries", response_model=LedgerEntryRead)
def post_entry(
    payload: LedgerEntryCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    acct = get_account(db, payload.account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")

    if (acct.owner_user_id != current_user.id) and (not is_admin(current_user)):
        raise HTTPException(status_code=403, detail="Not allowed")

    return create_ledger_entry(db, current_user.id, payload)


@router.get("/accounts/{account_id}/ledger", response_model=list[LedgerEntryRead])
def get_ledger(
    account_id: int,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    acct = get_account(db, account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")

    if (acct.owner_user_id != current_user.id) and (not is_admin(current_user)):
        raise HTTPException(status_code=403, detail="Not allowed")

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    return list_ledger_entries(db, account_id, limit=limit, offset=offset)


@router.get("/accounts/{account_id}/balance", response_model=BalanceRead)
def get_balance(
    account_id: int,
    currency: str = "USD",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    acct = get_account(db, account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")

    if (acct.owner_user_id != current_user.id) and (not is_admin(current_user)):
        raise HTTPException(status_code=403, detail="Not allowed")

    bal = get_account_balance(db, account_id, currency=currency)
    return BalanceRead(account_id=account_id, currency=currency, balance=bal, as_of=datetime.now(UTC))


@router.post("/transfers")
def transfer_funds(
    payload: TransferCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    from_acct = get_account(db, payload.from_account_id)
    to_acct = get_account(db, payload.to_account_id)
    if not from_acct or not to_acct:
        raise HTTPException(status_code=404, detail="Account not found")
    if (from_acct.owner_user_id != current_user.id) and (not is_admin(current_user)):
        raise HTTPException(status_code=403, detail="Not allowed")
    if (to_acct.owner_user_id != current_user.id) and (not is_admin(current_user)):
        raise HTTPException(status_code=403, detail="Not allowed")

    debit, credit = create_transfer(
        db,
        current_user.id,
        payload.from_account_id,
        payload.to_account_id,
        payload.amount,
        payload.currency,
        memo=payload.memo,
        reference=payload.reference,
    )
    return {
        "debit": LedgerEntryRead.model_validate(debit),
        "credit": LedgerEntryRead.model_validate(credit),
    }
