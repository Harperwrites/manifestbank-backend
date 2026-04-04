# app/routes/users.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.security import get_verified_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserRead, UserWealthTargetUpdate, UserDashboardCurrencyUpdate
from app.services.tier import is_premium, TIER_NAME
try:
    from app.services.credit import record_credit_action, ensure_credit_actions
except Exception:
    def ensure_credit_actions(db):  # type: ignore[no-redef]
        return None

    def record_credit_action(db, user_id: int, action: str):  # type: ignore[no-redef]
        return None

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/wealth-target", response_model=UserRead)
def update_wealth_target(
    payload: UserWealthTargetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.wealth_target_usd = payload.wealth_target_usd
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    ensure_credit_actions(db)
    record_credit_action(db, current_user.id, "wealth_target_update")
    return current_user


@router.patch("/dashboard-currency", response_model=UserRead)
def update_dashboard_currency(
    payload: UserDashboardCurrencyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user),
):
    if not is_premium(current_user):
        raise HTTPException(
            status_code=402,
            detail=f"{TIER_NAME} required to change dashboard currency.",
        )
    currency = payload.dashboard_currency.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise HTTPException(status_code=400, detail="Currency must be a 3-letter code")
    current_user.dashboard_currency = currency
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user
