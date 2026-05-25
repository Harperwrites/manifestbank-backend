# app/routes/ledger.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, UTC

from app.db.session import get_db
from app.core.security import get_current_user, get_verified_user
from app.schemas.ledger import LedgerEntryCreate, LedgerEntryRead, BalanceRead, TransferCreate
from app.crud.crud_ledger import (
    create_ledger_entry,
    list_ledger_entries,
    get_account_balance,
    get_latest_posted_balance_timestamp,
    create_transfer,
)
from app.services.fx import convert_amount_with_rate
from app.crud.crud_account import get_account
from app.services.email import send_ledger_post_email
from app.services.tier import (
    is_premium,
    count_deposits_7d,
    count_expenses_7d,
    count_checks_7d,
    get_free_tier_status,
    FREE_DEPOSIT_LIMIT_7D,
    FREE_EXPENSE_LIMIT_7D,
    FREE_CHECK_LIMIT_7D,
    TIER_NAME,
    build_preview_access,
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


def _serialize_ledger_entry(entry, current_user) -> LedgerEntryRead:
    preview = build_preview_access(user=current_user, created_at=entry.created_at)
    payload = LedgerEntryRead.model_validate(entry).model_dump()
    payload.update(preview)
    return LedgerEntryRead(**payload)


@router.get("/ledger/free-tier-status")
def free_tier_status(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return get_free_tier_status(db, current_user.id)


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

    entries = list_ledger_entries(db, account_id, limit=limit, offset=offset)
    return [_serialize_ledger_entry(entry, current_user) for entry in entries]


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
    latest_posted_at = get_latest_posted_balance_timestamp(db, account_id)
    preview = build_preview_access(user=current_user, created_at=latest_posted_at)
    return BalanceRead(
        account_id=account_id,
        currency=currency,
        balance=bal,
        as_of=datetime.now(UTC),
        **preview,
    )


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

    base_currency = (payload.currency or from_acct.currency or "USD").upper()
    debit_currency = (from_acct.currency or base_currency).upper()
    credit_currency = (to_acct.currency or base_currency).upper()
    debit_amount, missing_debit, debit_rate = convert_amount_with_rate(
        payload.amount, base_currency, debit_currency
    )
    credit_amount, missing_credit, credit_rate = convert_amount_with_rate(
        payload.amount, base_currency, credit_currency
    )

    fx_meta = {
        "fx_base_currency": base_currency,
        "fx_debit_currency": debit_currency,
        "fx_credit_currency": credit_currency,
        "fx_debit_rate": str(debit_rate),
        "fx_credit_rate": str(credit_rate),
        "fx_timestamp": datetime.now(UTC).isoformat(),
        "fx_missing_rates": list({*missing_debit, *missing_credit}),
    }

    debit, credit = create_transfer(
        db,
        current_user.id,
        payload.from_account_id,
        payload.to_account_id,
        debit_amount,
        debit_currency,
        credit_amount,
        credit_currency,
        memo=payload.memo,
        reference=payload.reference,
        meta=fx_meta,
    )
    ensure_credit_actions(db)
    record_credit_action(db, current_user.id, "ledger_transfer")
    return {
        "debit": LedgerEntryRead.model_validate(debit),
        "credit": LedgerEntryRead.model_validate(credit),
    }


@router.post("/transfers/preview")
def preview_transfer(
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

    base_currency = (payload.currency or from_acct.currency or "USD").upper()
    debit_currency = (from_acct.currency or base_currency).upper()
    credit_currency = (to_acct.currency or base_currency).upper()

    debit_amount, missing_debit, debit_rate = convert_amount_with_rate(
        payload.amount, base_currency, debit_currency
    )
    credit_amount, missing_credit, credit_rate = convert_amount_with_rate(
        payload.amount, base_currency, credit_currency
    )

    return {
        "base_currency": base_currency,
        "debit_currency": debit_currency,
        "credit_currency": credit_currency,
        "debit_amount": debit_amount,
        "credit_amount": credit_amount,
        "debit_rate": str(debit_rate),
        "credit_rate": str(credit_rate),
        "fx_timestamp": datetime.now(UTC).isoformat(),
        "missing_rates": list({*missing_debit, *missing_credit}),
    }
