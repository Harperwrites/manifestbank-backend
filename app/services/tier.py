from __future__ import annotations

from datetime import datetime, timedelta, UTC

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.models.ledger import LedgerEntry
from app.models.scheduled_entry import ScheduledEntry
from app.models.affirmation import AffirmationEntry
from app.models.account import Account


TIER_NAME = "ManifestBank™ Signature"
BALANCE_PREVIEW_WINDOW = timedelta(hours=12)

FREE_DEPOSIT_LIMIT_7D = 2
FREE_EXPENSE_LIMIT_7D = 2
FREE_CHECK_LIMIT_7D = 1
FREE_SCHEDULE_LIMIT_7D = 1
FREE_AFFIRMATION_LIMIT = 10
FREE_ACCOUNT_LIMIT = 1

SAVED_AFFIRMATION_TITLE = "Saved affirmation"


def is_premium(user) -> bool:
    if getattr(user, "role", None) == "admin":
        return True
    return bool(getattr(user, "is_premium", False))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _rollout_at() -> datetime:
    raw = settings.BALANCE_PREVIEW_ROLLOUT_AT
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return _as_utc(parsed) or datetime(2026, 5, 25, tzinfo=UTC)


def preview_anchor_at(created_at: datetime | None) -> datetime | None:
    created = _as_utc(created_at)
    if created is None:
        return None
    return max(created, _rollout_at())


def compute_preview_expires_at(created_at: datetime | None) -> datetime | None:
    created = preview_anchor_at(created_at)
    if not created:
        return None
    return created + BALANCE_PREVIEW_WINDOW


def build_preview_access(
    *,
    user,
    created_at: datetime | None,
    now: datetime | None = None,
) -> dict[str, object]:
    current = _as_utc(now) or datetime.now(UTC)
    anchor = preview_anchor_at(created_at)
    expires_at = compute_preview_expires_at(created_at)
    if is_premium(user):
        return {
            "preview_expires_at": expires_at,
            "is_preview_expired": False,
            "visible_to_user": True,
        }
    if not expires_at:
        return {
            "preview_expires_at": None,
            "is_preview_expired": False,
            "visible_to_user": True,
        }
    expired = anchor is not None and anchor <= current - BALANCE_PREVIEW_WINDOW
    return {
        "preview_expires_at": expires_at,
        "is_preview_expired": expired,
        "visible_to_user": not expired,
    }


def _since_7d() -> datetime:
    return datetime.now(UTC) - timedelta(days=7)


def _next_available_at(created_at: datetime | None) -> datetime | None:
    if not created_at:
        return None
    return created_at + timedelta(days=7)


def count_deposits_7d(db: Session, user_id: int) -> int:
    since = _since_7d()
    # counts deposits (excluding checks)
    kind = func.coalesce(LedgerEntry.meta["kind"].as_string(), "")
    return (
        db.query(func.count(LedgerEntry.id))
        .filter(
            LedgerEntry.created_by_user_id == user_id,
            LedgerEntry.entry_type == "deposit",
            LedgerEntry.created_at >= since,
            kind != "check",
        )
        .scalar()
        or 0
    )


def count_expenses_7d(db: Session, user_id: int) -> int:
    since = _since_7d()
    # counts withdrawals (excluding checks)
    kind = func.coalesce(LedgerEntry.meta["kind"].as_string(), "")
    return (
        db.query(func.count(LedgerEntry.id))
        .filter(
            LedgerEntry.created_by_user_id == user_id,
            LedgerEntry.entry_type == "withdrawal",
            LedgerEntry.created_at >= since,
            kind != "check",
        )
        .scalar()
        or 0
    )


def count_checks_7d(db: Session, user_id: int) -> int:
    since = _since_7d()
    kind = func.coalesce(LedgerEntry.meta["kind"].as_string(), "")
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


def next_check_available_at(db: Session, user_id: int) -> datetime | None:
    since = _since_7d()
    kind = func.coalesce(LedgerEntry.meta["kind"].as_string(), "")
    oldest = (
        db.query(LedgerEntry.created_at)
        .filter(
            LedgerEntry.created_by_user_id == user_id,
            LedgerEntry.created_at >= since,
            kind == "check",
        )
        .order_by(LedgerEntry.created_at.asc())
        .offset(FREE_CHECK_LIMIT_7D - 1)
        .first()
    )
    return _next_available_at(oldest[0] if oldest else None)


def next_deposit_available_at(db: Session, user_id: int) -> datetime | None:
    since = _since_7d()
    kind = func.coalesce(LedgerEntry.meta["kind"].as_string(), "")
    oldest = (
        db.query(LedgerEntry.created_at)
        .filter(
            LedgerEntry.created_by_user_id == user_id,
            LedgerEntry.entry_type == "deposit",
            LedgerEntry.created_at >= since,
            kind != "check",
        )
        .order_by(LedgerEntry.created_at.asc())
        .offset(FREE_DEPOSIT_LIMIT_7D - 1)
        .first()
    )
    return _next_available_at(oldest[0] if oldest else None)


def next_expense_available_at(db: Session, user_id: int) -> datetime | None:
    since = _since_7d()
    kind = func.coalesce(LedgerEntry.meta["kind"].as_string(), "")
    oldest = (
        db.query(LedgerEntry.created_at)
        .filter(
            LedgerEntry.created_by_user_id == user_id,
            LedgerEntry.entry_type == "withdrawal",
            LedgerEntry.created_at >= since,
            kind != "check",
        )
        .order_by(LedgerEntry.created_at.asc())
        .offset(FREE_EXPENSE_LIMIT_7D - 1)
        .first()
    )
    return _next_available_at(oldest[0] if oldest else None)


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


def get_free_tier_status(db: Session, user_id: int) -> dict[str, object]:
    checks_used = count_checks_7d(db, user_id)
    deposits_used = count_deposits_7d(db, user_id)
    expenses_used = count_expenses_7d(db, user_id)
    check_next = next_check_available_at(db, user_id) if checks_used >= FREE_CHECK_LIMIT_7D else None
    deposit_next = next_deposit_available_at(db, user_id) if deposits_used >= FREE_DEPOSIT_LIMIT_7D else None
    expense_next = next_expense_available_at(db, user_id) if expenses_used >= FREE_EXPENSE_LIMIT_7D else None
    return {
        "checks": {
            "limit": FREE_CHECK_LIMIT_7D,
            "used": checks_used,
            "remaining": max(0, FREE_CHECK_LIMIT_7D - checks_used),
            "next_available_at": check_next.isoformat() if check_next else None,
        },
        "deposits": {
            "limit": FREE_DEPOSIT_LIMIT_7D,
            "used": deposits_used,
            "remaining": max(0, FREE_DEPOSIT_LIMIT_7D - deposits_used),
            "next_available_at": deposit_next.isoformat() if deposit_next else None,
        },
        "expenses": {
            "limit": FREE_EXPENSE_LIMIT_7D,
            "used": expenses_used,
            "remaining": max(0, FREE_EXPENSE_LIMIT_7D - expenses_used),
            "next_available_at": expense_next.isoformat() if expense_next else None,
        },
    }
