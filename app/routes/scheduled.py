# app/routes/scheduled.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user, get_verified_user
from app.schemas.scheduled_entry import ScheduledEntryCreate, ScheduledEntryRead
from app.crud.crud_scheduled_entry import create_scheduled_entry, list_scheduled_entries
from app.crud.crud_account import get_account

router = APIRouter(tags=["scheduled"])


def is_admin(user) -> bool:
    return getattr(user, "role", None) == "admin"


def ensure_access(account, current_user):
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if (account.owner_user_id != current_user.id) and (not is_admin(current_user)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")


@router.post("/scheduled-entries", response_model=ScheduledEntryRead)
def create_scheduled(
    payload: ScheduledEntryCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    account = get_account(db, payload.account_id)
    ensure_access(account, current_user)
    return create_scheduled_entry(db, current_user.id, payload)


@router.get("/accounts/{account_id}/scheduled-entries", response_model=list[ScheduledEntryRead])
def list_scheduled(
    account_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    account = get_account(db, account_id)
    ensure_access(account, current_user)
    return list_scheduled_entries(db, account_id)
