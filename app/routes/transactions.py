# app/routes/transactions.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Any, Dict

from app.core.security import get_current_user, get_verified_user
from app.db.session import get_db
from app.schemas.transaction import DepositRequest, WithdrawRequest, TransactionRead
from app.crud.crud_account import get_account
from app.crud.crud_ledger import create_ledger_entry, create_transfer, get_account_balance
from app.schemas.ledger import LedgerEntryCreate
from app.services.fx import convert_amount_with_rate

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _account_to_dict(acct, db: Session):
    """
    Convert ORM Account -> JSON-friendly dict.
    Also normalizes user_id -> owner_id because your AccountRead uses owner_id.
    """
    if acct is None:
        return None

    bal = get_account_balance(db, acct.id, currency=(acct.currency or "USD"))
    return {
        "id": acct.id,
        "owner_id": getattr(acct, "owner_user_id", None) or getattr(acct, "user_id"),
        "type": getattr(acct, "account_type", None) or getattr(acct, "type"),
        "balance": float(bal),
    }


def _attach_account(
    entry,
    account_obj,
    db: Session,
    amount: float,
    txn_type: str,
    description: str | None = None,
):
    return {
        "id": entry.id,
        "account_id": entry.account_id,
        "amount": float(amount),
        "type": txn_type,
        "timestamp": entry.created_at,
        "description": description,
        "account": _account_to_dict(account_obj, db),
    }


@router.post("/deposit", response_model=TransactionRead, status_code=200)
def deposit_route(
    payload: DepositRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    acct = get_account(db, payload.account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")
    if acct.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    entry = create_ledger_entry(
        db,
        current_user.id,
        LedgerEntryCreate(
            account_id=payload.account_id,
            direction="credit",
            amount=str(payload.amount),
            currency=(acct.currency or "USD"),
            entry_type="deposit",
            status="posted",
            memo=payload.description,
        ),
    )
    return _attach_account(entry, acct, db, float(payload.amount), "deposit", payload.description)


@router.post("/withdraw", response_model=TransactionRead, status_code=200)
def withdraw_route(
    payload: WithdrawRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    acct = get_account(db, payload.account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")
    if acct.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    entry = create_ledger_entry(
        db,
        current_user.id,
        LedgerEntryCreate(
            account_id=payload.account_id,
            direction="debit",
            amount=str(payload.amount),
            currency=(acct.currency or "USD"),
            entry_type="withdrawal",
            status="posted",
            memo=payload.description,
        ),
    )
    return _attach_account(entry, acct, db, -float(payload.amount), "withdrawal", payload.description)


@router.post("/transfer", status_code=200)
def transfer_route(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    # ✅ Accept multiple naming conventions (tests often use from_id/to_id)
    from_id = (
        payload.get("from_id")
        or payload.get("from_account_id")
        or payload.get("from_account")
    )
    to_id = (
        payload.get("to_id")
        or payload.get("to_account_id")
        or payload.get("to_account")
    )
    amount = payload.get("amount")
    description = payload.get("description")

    if from_id is None or to_id is None or amount is None:
        raise HTTPException(status_code=422, detail="Missing required fields")

    from_acct = get_account(db, int(from_id))
    to_acct = get_account(db, int(to_id))

    if not from_acct or not to_acct:
        raise HTTPException(status_code=404, detail="Account not found")
    if from_acct.owner_user_id != current_user.id or to_acct.owner_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    base_currency = (from_acct.currency or "USD").upper()
    debit_currency = (from_acct.currency or base_currency).upper()
    credit_currency = (to_acct.currency or base_currency).upper()
    debit_amount, _, _ = convert_amount_with_rate(amount, base_currency, debit_currency)
    credit_amount, _, _ = convert_amount_with_rate(amount, base_currency, credit_currency)

    debit, credit = create_transfer(
        db,
        current_user.id,
        int(from_id),
        int(to_id),
        debit_amount,
        debit_currency,
        credit_amount,
        credit_currency,
        memo=description or "Transfer",
    )
    return {
        "out": _attach_account(debit, from_acct, db, -float(debit_amount), "transfer", description),
        "in": _attach_account(credit, to_acct, db, float(credit_amount), "transfer", description),
    }


@router.get("/{transaction_id}", response_model=TransactionRead, status_code=200)
def get_transaction_route(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    raise HTTPException(status_code=404, detail="Not Found")
