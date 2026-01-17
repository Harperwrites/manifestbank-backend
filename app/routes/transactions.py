# app/routes/transactions.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Any, Dict

from app.core.security import get_current_user, get_verified_user
from app.db.session import get_db
from app.schemas.transaction import (
    DepositRequest,
    WithdrawRequest,
    TransactionRead,
)
from app.crud.crud_account import get_account
from app.crud.crud_transaction import deposit, withdraw, transfer, get_transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _account_to_dict(acct):
    """
    Convert ORM Account -> JSON-friendly dict.
    Also normalizes user_id -> owner_id because your AccountRead uses owner_id.
    """
    if acct is None:
        return None

    return {
        "id": acct.id,
        "owner_id": getattr(acct, "owner_id", None) or getattr(acct, "user_id"),
        "type": acct.type,
        "balance": float(acct.balance),
    }


def _attach_account(txn, account_obj):
    # Return a dict that matches TransactionRead + nested account dict
    return {
        "id": txn.id,
        "account_id": txn.account_id,
        "amount": float(txn.amount),
        "type": txn.type,
        "timestamp": txn.timestamp,
        "description": txn.description,
        "account": _account_to_dict(account_obj),
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
    if acct.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    txn = deposit(db, payload.account_id, payload.amount, payload.description)
    return _attach_account(txn, acct)


@router.post("/withdraw", response_model=TransactionRead, status_code=200)
def withdraw_route(
    payload: WithdrawRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    acct = get_account(db, payload.account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")
    if acct.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    txn = withdraw(db, payload.account_id, payload.amount, payload.description)
    return _attach_account(txn, acct)


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
    if from_acct.user_id != current_user.id or to_acct.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    t_out, t_in = transfer(db, int(from_id), int(to_id), float(amount), description)
    return {
        "out": _attach_account(t_out, from_acct),
        "in": _attach_account(t_in, to_acct),
    }


@router.get("/{transaction_id}", response_model=TransactionRead, status_code=200)
def get_transaction_route(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    txn = get_transaction(db, transaction_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Not Found")

    acct = get_account(db, txn.account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")
    if acct.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    return _attach_account(txn, acct)
