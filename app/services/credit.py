from __future__ import annotations

from datetime import datetime, timedelta, UTC
import random
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.models.credit import CreditAction, CreditActionCompletion, CreditScoreSnapshot, CreditTodo
from app.models.user import User
from app.services.credit_actions import (
    ACTION_LIBRARY,
    IAB_POSITIVE,
    IAB_NEGATIVE,
    ER_POSITIVE,
    ER_NEGATIVE,
    CTB_POSITIVE,
    CTB_NEGATIVE,
)
from app.services.tier import is_premium


DAILY_CAP_FREE = 2
DAILY_CAP_PREMIUM = 5


def daily_cap(premium: bool) -> int:
    return DAILY_CAP_PREMIUM if premium else DAILY_CAP_FREE


def points_for_action_type(action_type: str | None, premium: bool) -> int:
    if action_type == "daily_login":
        return 2 if premium else 1
    return 1


def _today_points(db: Session, user_id: int, premium: bool) -> int:
    now = datetime.now(UTC)
    start_day = datetime(now.year, now.month, now.day, tzinfo=UTC)
    today_rows = (
        db.query(CreditActionCompletion, CreditAction)
        .join(CreditAction)
        .filter(CreditActionCompletion.user_id == user_id, CreditActionCompletion.completed_at >= start_day)
        .all()
    )
    return sum(points_for_action_type(action.action_type, premium) for _, action in today_rows)


def _complete_action_record(db: Session, user_id: int, action: CreditAction) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    premium = is_premium(user) if user else False
    next_points = points_for_action_type(action.action_type, premium)
    if _today_points(db, user_id, premium) + next_points > daily_cap(premium):
        return False

    db.add(CreditActionCompletion(user_id=user_id, action_id=action.id, completed_at=datetime.now(UTC)))
    db.commit()

    action_type = action.action_type or "unknown"
    todos = (
        db.query(CreditTodo)
        .filter(CreditTodo.user_id == user_id, CreditTodo.action_type == action_type, CreditTodo.status == "open")
        .all()
    )
    for todo in todos:
        todo.status = "completed"
        todo.completed_at = datetime.now(UTC)
        db.add(todo)
    if todos:
        db.commit()
    return True


def ensure_credit_actions(db: Session) -> int:
    existing = db.query(func.count(CreditAction.id)).scalar() or 0
    missing_type = db.query(func.count(CreditAction.id)).filter(CreditAction.action_type.is_(None)).scalar() or 0
    if existing > 0 and missing_type > 0:
        db.query(CreditActionCompletion).delete()
        db.query(CreditAction).delete()
        db.commit()
        existing = 0

    if existing == 0:
        for item in ACTION_LIBRARY:
            db.add(
                CreditAction(
                    action_type=item["action_type"],
                    action_route=item.get("action_route"),
                    title=item["title"],
                    description=item["description"],
                    primary_bureau=item["primary_bureau"],
                    secondary_bureau=item.get("secondary_bureau"),
                    confirmation_copy=item["confirmation_copy"],
                    active=True,
                )
            )
        db.commit()
        return len(ACTION_LIBRARY)

    existing_keys = set(db.query(CreditAction.title, CreditAction.action_type).all())
    added = 0
    for item in ACTION_LIBRARY:
        key = (item["title"], item["action_type"])
        if key in existing_keys:
            continue
        db.add(
            CreditAction(
                action_type=item["action_type"],
                action_route=item.get("action_route"),
                title=item["title"],
                description=item["description"],
                primary_bureau=item["primary_bureau"],
                secondary_bureau=item.get("secondary_bureau"),
                confirmation_copy=item["confirmation_copy"],
                active=True,
            )
        )
        added += 1
    if added:
        db.commit()
    return existing + added


def record_credit_action(db: Session, user_id: int, action_type: str) -> bool:
    action = (
        db.query(CreditAction)
        .filter(CreditAction.action_type == action_type, CreditAction.active.is_(True))
        .order_by(func.random())
        .first()
    )
    if not action:
        return False
    return _complete_action_record(db, user_id, action)


def record_daily_login(db: Session, user_id: int) -> bool:
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    user = db.query(User).filter(User.id == user_id).first()
    premium = is_premium(user) if user else False
    if _today_points(db, user_id, premium) + points_for_action_type("daily_login", premium) > daily_cap(premium):
        return False
    action = (
        db.query(CreditAction)
        .filter(CreditAction.action_type == "daily_login", CreditAction.active.is_(True))
        .first()
    )
    if not action:
        return False
    exists = (
        db.query(CreditActionCompletion)
        .filter(
            CreditActionCompletion.user_id == user_id,
            CreditActionCompletion.action_id == action.id,
            CreditActionCompletion.completed_at >= since,
        )
        .first()
    )
    if exists:
        return False
    db.add(CreditActionCompletion(user_id=user_id, action_id=action.id, completed_at=datetime.now(UTC)))
    db.commit()
    return True


def complete_credit_action_by_id(db: Session, user_id: int, action_id: int) -> tuple[CreditAction | None, bool]:
    action = db.query(CreditAction).filter(CreditAction.id == action_id, CreditAction.active.is_(True)).first()
    if not action:
        return None, False
    completed = _complete_action_record(db, user_id, action)
    return action, completed


def _score_from_counts(count_7d: int, count_30d: int) -> int:
    # Use a single points window so each action only contributes once.
    # 30-day points are the scoring basis; 7-day points are for drivers only.
    base = 700
    score = base + count_30d
    return max(0, min(999, score))


def _snapshot_columns(db: Session) -> set[str]:
    try:
        rows = db.execute(text("PRAGMA table_info('credit_score_snapshots')")).fetchall()
        return {row[1] for row in rows}
    except Exception:
        db.rollback()
        return set()


def _pick_driver(positive: list[str], negative: list[str], count_7d: int) -> str:
    if count_7d >= 5:
        return random.choice(positive)
    if count_7d == 0:
        return random.choice(negative)
    return "Recent activity maintained a steady signal."


def get_credit_summary(db: Session, user_id: int, days: int) -> dict:
    now = datetime.now(UTC)
    start_7d = now - timedelta(days=7)
    start_30d = now - timedelta(days=30)
    start_day = datetime(now.year, now.month, now.day, tzinfo=UTC)
    user = db.query(User).filter(User.id == user_id).first()
    premium = is_premium(user) if user else False

    base_query = db.query(CreditActionCompletion, CreditAction).join(CreditAction).filter(
        CreditActionCompletion.user_id == user_id
    )
    rows_7d = base_query.filter(CreditActionCompletion.completed_at >= start_7d).all()
    rows_30d = base_query.filter(CreditActionCompletion.completed_at >= start_30d).all()
    total_7d = sum(points_for_action_type(action.action_type, premium) for _, action in rows_7d)
    total_30d = sum(points_for_action_type(action.action_type, premium) for _, action in rows_30d)
    today_rows = (
        db.query(CreditActionCompletion, CreditAction)
        .join(CreditAction)
        .filter(CreditActionCompletion.user_id == user_id, CreditActionCompletion.completed_at >= start_day)
        .all()
    )
    daily_used = sum(points_for_action_type(action.action_type, premium) for _, action in today_rows)

    def count_by_bureau(bureau: str, since: datetime) -> int:
        rows = base_query.filter(
            CreditAction.primary_bureau == bureau,
            CreditActionCompletion.completed_at >= since,
        ).all()
        return sum(points_for_action_type(action.action_type, premium) for _, action in rows)

    iab_7 = count_by_bureau("IAB", start_7d)
    er_7 = count_by_bureau("Emotional Reserve", start_7d)
    ctb_7 = count_by_bureau("CTB", start_7d)

    iab_30 = count_by_bureau("IAB", start_30d)
    er_30 = count_by_bureau("Emotional Reserve", start_30d)
    ctb_30 = count_by_bureau("CTB", start_30d)

    iab_score = _score_from_counts(iab_7, iab_30)
    er_score = _score_from_counts(er_7, er_30)
    ctb_score = _score_from_counts(ctb_7, ctb_30)
    # Composite only changes when it crosses a full point boundary.
    computed_composite = int((iab_score + er_score + ctb_score) / 3)
    snapshot_cols = _snapshot_columns(db)
    if {"bureau", "score"}.issubset(snapshot_cols):
        last_composite = (
            db.query(CreditScoreSnapshot)
            .filter(CreditScoreSnapshot.user_id == user_id, CreditScoreSnapshot.bureau == "composite")
            .order_by(CreditScoreSnapshot.created_at.desc())
            .first()
        )
        if last_composite is None or abs(computed_composite - last_composite.score) >= 1:
            composite = computed_composite
            db.add(CreditScoreSnapshot(user_id=user_id, bureau="composite", score=composite))
            db.commit()
        else:
            composite = last_composite.score
    else:
        # Fallback if the DB schema is missing the bureau column.
        composite = computed_composite

    # streak calculation (consecutive days with >=1 completion)
    streak = 0
    for day_offset in range(0, 30):
        day_start = datetime(now.year, now.month, now.day, tzinfo=UTC) - timedelta(days=day_offset)
        day_end = day_start + timedelta(days=1)
        day_rows = (
            base_query.filter(
                CreditActionCompletion.completed_at >= day_start,
                CreditActionCompletion.completed_at < day_end,
            ).all()
        )
        day_points = sum(points_for_action_type(action.action_type, premium) for _, action in day_rows)
        if day_points > 0:
            streak += 1
        else:
            break

    # trend (points per day)
    trend = []
    for day_offset in range(days - 1, -1, -1):
        day_start = datetime(now.year, now.month, now.day, tzinfo=UTC) - timedelta(days=day_offset)
        day_end = day_start + timedelta(days=1)
        rows = base_query.filter(
            CreditActionCompletion.completed_at >= day_start,
            CreditActionCompletion.completed_at < day_end,
        ).all()
        trend.append(sum(points_for_action_type(action.action_type, premium) for _, action in rows))

    drivers = {
        "iab": _pick_driver(IAB_POSITIVE, IAB_NEGATIVE, iab_7),
        "emotional": _pick_driver(ER_POSITIVE, ER_NEGATIVE, er_7),
        "ctb": _pick_driver(CTB_POSITIVE, CTB_NEGATIVE, ctb_7),
    }

    return {
        "scores": {
            "composite": composite,
            "iab": iab_score,
            "emotional": er_score,
            "ctb": ctb_score,
        },
        "updated_at": now,
        "total_actions_7d": total_7d,
        "total_actions_30d": total_30d,
        "completed_iab_30d": iab_30,
        "completed_emotional_30d": er_30,
        "completed_ctb_30d": ctb_30,
        "streak_days": streak,
        "daily_cap": daily_cap(premium),
        "daily_used": daily_used,
        "trend_7d": trend,
        "drivers": drivers,
    }


def get_bureau_detail(db: Session, user_id: int, bureau: str, days: int) -> dict:
    now = datetime.now(UTC)
    start_7d = now - timedelta(days=days)
    user = db.query(User).filter(User.id == user_id).first()
    premium = is_premium(user) if user else False

    base_query = db.query(CreditActionCompletion, CreditAction).join(CreditAction).filter(
        CreditActionCompletion.user_id == user_id
    )

    def count_by_bureau_since(since: datetime) -> int:
        rows = base_query.filter(
            CreditAction.primary_bureau == bureau,
            CreditActionCompletion.completed_at >= since,
        ).all()
        return sum(points_for_action_type(action.action_type, premium) for _, action in rows)

    count_7d = count_by_bureau_since(start_7d)
    count_30d = count_by_bureau_since(now - timedelta(days=30))
    score = _score_from_counts(count_7d, count_30d)

    trend = []
    for day_offset in range(days - 1, -1, -1):
        day_start = datetime(now.year, now.month, now.day, tzinfo=UTC) - timedelta(days=day_offset)
        day_end = day_start + timedelta(days=1)
        rows = base_query.filter(
            CreditAction.primary_bureau == bureau,
            CreditActionCompletion.completed_at >= day_start,
            CreditActionCompletion.completed_at < day_end,
        ).all()
        day_points = sum(points_for_action_type(action.action_type, premium) for _, action in rows)
        trend.append(day_points)

    if bureau == "IAB":
        drivers = random.sample(IAB_POSITIVE, 2)
    elif bureau == "Emotional Reserve":
        drivers = random.sample(ER_POSITIVE, 2)
    else:
        drivers = random.sample(CTB_POSITIVE, 2)

    return {"bureau": bureau, "score": score, "trend": trend, "days": days, "drivers": drivers}
