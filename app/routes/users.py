# app/routes/users.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserRead, UserWealthTargetUpdate

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
    return current_user
