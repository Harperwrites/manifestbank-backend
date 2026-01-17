# app/crud/crud_scheduled_entry.py

from datetime import datetime, UTC
from sqlalchemy.orm import Session

from app.models.scheduled_entry import ScheduledEntry
from app.models.ledger import LedgerEntry
from app.schemas.scheduled_entry import ScheduledEntryCreate


def create_scheduled_entry(
    db: Session, created_by_user_id: int, payload: ScheduledEntryCreate
) -> ScheduledEntry:
    entry = ScheduledEntry(
        account_id=payload.account_id,
        created_by_user_id=created_by_user_id,
        direction=payload.direction,
        amount=payload.amount,
        currency=payload.currency,
        entry_type=payload.entry_type,
        status="pending",
        reference=payload.reference,
        memo=payload.memo,
        scheduled_for=payload.scheduled_for,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_scheduled_entries(
    db: Session, account_id: int, include_posted: bool = False
) -> list[ScheduledEntry]:
    query = db.query(ScheduledEntry).filter(ScheduledEntry.account_id == account_id)
    if not include_posted:
        query = query.filter(ScheduledEntry.status == "pending")
    return query.order_by(ScheduledEntry.scheduled_for.asc()).all()


def post_due_entries(db: Session) -> int:
    now = datetime.now(UTC)
    due = (
        db.query(ScheduledEntry)
        .filter(ScheduledEntry.status == "pending", ScheduledEntry.scheduled_for <= now)
        .order_by(ScheduledEntry.scheduled_for.asc())
        .all()
    )
    count = 0
    for entry in due:
        ledger = LedgerEntry(
            account_id=entry.account_id,
            created_by_user_id=entry.created_by_user_id,
            direction=entry.direction,
            amount=entry.amount,
            currency=entry.currency,
            entry_type=entry.entry_type,
            status="posted",
            reference=entry.reference,
            memo=entry.memo,
            meta={"source": "scheduled", "scheduled_entry_id": entry.id},
        )
        db.add(ledger)
        db.flush()
        entry.status = "posted"
        entry.posted_at = now
        entry.posted_entry_id = ledger.id
        count += 1

    if count:
        db.commit()
    return count
