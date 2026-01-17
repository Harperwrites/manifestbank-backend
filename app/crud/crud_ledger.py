# app/crud/crud_ledger.py

from sqlalchemy.orm import Session
from sqlalchemy import func, case
from decimal import Decimal
from datetime import datetime

from app.models.ledger import LedgerEntry
from app.models.account import Account
from app.schemas.ledger import LedgerEntryCreate


def create_ledger_entry(db: Session, created_by_user_id: int, payload: LedgerEntryCreate) -> LedgerEntry:
    if payload.idempotency_key:
        existing = (
            db.query(LedgerEntry)
            .filter(
                LedgerEntry.account_id == payload.account_id,
                LedgerEntry.idempotency_key == payload.idempotency_key,
            )
            .order_by(LedgerEntry.created_at.desc())
            .first()
        )
        if existing:
            return existing

    entry = LedgerEntry(
        account_id=payload.account_id,
        created_by_user_id=created_by_user_id,
        direction=payload.direction,
        amount=payload.amount,
        currency=payload.currency,
        entry_type=payload.entry_type,
        status=payload.status,
        reference=payload.reference,
        external_ref=payload.external_ref,
        idempotency_key=payload.idempotency_key,
        memo=payload.memo,
        meta=payload.meta,
    )

    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_ledger_entries(db: Session, account_id: int, limit: int = 50, offset: int = 0) -> list[LedgerEntry]:
    return (
        db.query(LedgerEntry)
        .filter(LedgerEntry.account_id == account_id)
        .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_account_balance(db: Session, account_id: int, currency: str = "USD") -> Decimal:
    account_ids = [account_id]
    account = db.query(Account).filter(Account.id == account_id).first()
    if account and account.account_type == "trust":
        child_ids = [
            row.id
            for row in db.query(Account.id)
            .filter(Account.parent_account_id == account_id)
            .all()
        ]
        account_ids.extend(child_ids)

    credit_sum = func.coalesce(
        func.sum(case((LedgerEntry.direction == "credit", LedgerEntry.amount), else_=0)),
        0,
    )
    debit_sum = func.coalesce(
        func.sum(case((LedgerEntry.direction == "debit", LedgerEntry.amount), else_=0)),
        0,
    )

    row = (
        db.query(credit_sum.label("credits"), debit_sum.label("debits"))
        .filter(
            LedgerEntry.account_id.in_(account_ids),
            LedgerEntry.status == "posted",
            LedgerEntry.currency == currency,
        )
        .first()
    )

    credits = Decimal(str(row.credits or 0))
    debits = Decimal(str(row.debits or 0))
    return credits - debits


def create_transfer(
    db: Session,
    created_by_user_id: int,
    from_account_id: int,
    to_account_id: int,
    amount: Decimal,
    currency: str = "USD",
    memo: str | None = None,
    reference: str | None = None,
) -> tuple[LedgerEntry, LedgerEntry]:
    transfer_meta = {"transfer_id": f"{from_account_id}->{to_account_id}:{datetime.utcnow().timestamp()}"}
    debit = LedgerEntry(
        account_id=from_account_id,
        created_by_user_id=created_by_user_id,
        direction="debit",
        amount=amount,
        currency=currency,
        entry_type="transfer",
        status="posted",
        reference=reference,
        memo=memo,
        meta=transfer_meta,
    )
    credit = LedgerEntry(
        account_id=to_account_id,
        created_by_user_id=created_by_user_id,
        direction="credit",
        amount=amount,
        currency=currency,
        entry_type="transfer",
        status="posted",
        reference=reference,
        memo=memo,
        meta=transfer_meta,
    )
    db.add(debit)
    db.add(credit)
    db.commit()
    db.refresh(debit)
    db.refresh(credit)
    return debit, credit
