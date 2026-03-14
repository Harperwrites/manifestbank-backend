# app/routes/ledger.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, UTC

from app.db.session import get_db
from app.core.security import get_current_user, get_verified_user
from app.schemas.ledger import LedgerEntryCreate, LedgerEntryRead, BalanceRead, TransferCreate
from app.crud.crud_ledger import create_ledger_entry, list_ledger_entries, get_account_balance, create_transfer
from app.crud.crud_account import get_account
from app.services.email import send_ledger_post_email
from app.services.tier import (
    is_premium,
    count_deposits_7d,
    count_expenses_7d,
    count_checks_7d,
    FREE_DEPOSIT_LIMIT_7D,
    FREE_EXPENSE_LIMIT_7D,
    FREE_CHECK_LIMIT_7D,
    TIER_NAME,
)
try:
    from app.services.credit import record_credit_action, ensure_credit_actions
except Exception:
    def ensure_credit_actions(db):  # type: ignore[no-redef]
        return None

    def record_credit_action(db, user_id: int, action: str):  # type: ignore[no-redef]
        return None

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

    if not is_premium(current_user):
        entry_type = (payload.entry_type or "").lower()
        meta = payload.meta or {}
        kind = str(meta.get("kind") or "").lower()
        if kind == "check":
            if count_checks_7d(db, current_user.id) >= FREE_CHECK_LIMIT_7D:
                raise HTTPException(
                    status_code=402,
                    detail=f"Free tier allows 1 check every 7 days. Upgrade to {TIER_NAME} for unlimited checks.",
                )
        elif entry_type == "deposit":
            if count_deposits_7d(db, current_user.id) >= FREE_DEPOSIT_LIMIT_7D:
                raise HTTPException(
                    status_code=402,
                    detail=f"Free tier allows 2 deposits every 7 days. Upgrade to {TIER_NAME} for unlimited deposits.",
                )
        elif entry_type == "withdrawal":
            if count_expenses_7d(db, current_user.id) >= FREE_EXPENSE_LIMIT_7D:
                raise HTTPException(
                    status_code=402,
                    detail=f"Free tier allows 2 expenses every 7 days. Upgrade to {TIER_NAME} for unlimited expenses.",
                )

    entry = create_ledger_entry(db, current_user.id, payload)
    ensure_credit_actions(db)
    entry_type = (payload.entry_type or "").lower()
    meta = payload.meta or {}
    kind = str(meta.get("kind") or "").lower()
    if kind == "check":
        record_credit_action(db, current_user.id, "check_post")
        if current_user.email_verified:
            amount_str = f"{entry.amount:.2f} {entry.currency}"
            send_ledger_post_email(
                current_user.email,
                acct.name,
                entry.direction,
                amount_str,
                "check",
                f"/dashboard/activity/{entry.id}",
            )
    elif entry_type == "deposit":
        record_credit_action(db, current_user.id, "ledger_deposit")
    elif entry_type == "withdrawal":
        record_credit_action(db, current_user.id, "ledger_expense")
    return entry


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
    ensure_credit_actions(db)
    record_credit_action(db, current_user.id, "ledger_transfer")
    return {
        "debit": LedgerEntryRead.model_validate(debit),
        "credit": LedgerEntryRead.model_validate(credit),
    }
