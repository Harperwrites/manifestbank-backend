from __future__ import annotations

from datetime import datetime, timedelta, UTC

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.ledger import LedgerEntry
from app.models.scheduled_entry import ScheduledEntry
from app.models.affirmation import AffirmationEntry
from app.models.account import Account


TIER_NAME = "ManifestBank™ Signature"

FREE_TXN_LIMIT_7D = 5
FREE_CHECK_LIMIT_7D = 1
FREE_SCHEDULE_LIMIT_7D = 3
FREE_AFFIRMATION_LIMIT = 10
FREE_ACCOUNT_LIMIT = 1

SAVED_AFFIRMATION_TITLE = "Saved affirmation"


def is_premium(user) -> bool:
    if getattr(user, "role", None) == "admin":
        return True
    return bool(getattr(user, "is_premium", False))


def _since_7d() -> datetime:
    return datetime.now(UTC) - timedelta(days=7)


def count_free_transactions(db: Session, user_id: int) -> int:
    since = _since_7d()
    # counts deposits + withdrawals (excluding checks)
    kind = func.coalesce(LedgerEntry.meta["kind"].astext, "")
    return (
        db.query(func.count(LedgerEntry.id))
        .filter(
            LedgerEntry.created_by_user_id == user_id,
            LedgerEntry.entry_type.in_(["deposit", "withdrawal"]),
            LedgerEntry.created_at >= since,
            kind != "check",
        )
        .scalar()
        or 0
    )


def count_checks_7d(db: Session, user_id: int) -> int:
    since = _since_7d()
    kind = func.coalesce(LedgerEntry.meta["kind"].astext, "")
    return (
        db.query(func.count(LedgerEntry.id))
        .filter(
            LedgerEntry.created_by_user_id == user_id,
            LedgerEntry.created_at >= since,
            kind == "check",
        )
        .scalar()
        or 0
    )


def count_scheduled_7d(db: Session, user_id: int) -> int:
    since = _since_7d()
    return (
        db.query(func.count(ScheduledEntry.id))
        .filter(
            ScheduledEntry.created_by_user_id == user_id,
            ScheduledEntry.created_at >= since,
        )
        .scalar()
        or 0
    )


def count_affirmations(db: Session, user_id: int) -> int:
    return (
        db.query(func.count(AffirmationEntry.id))
        .filter(
            AffirmationEntry.user_id == user_id,
            AffirmationEntry.title != SAVED_AFFIRMATION_TITLE,
        )
        .scalar()
        or 0
    )


def count_accounts(db: Session, user_id: int) -> int:
    return (
        db.query(func.count(Account.id))
        .filter(Account.owner_user_id == user_id)
        .scalar()
        or 0
    )

