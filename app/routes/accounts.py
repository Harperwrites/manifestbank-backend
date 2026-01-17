# app/routes/accounts.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user, get_verified_user
from app.schemas.account import AccountCreate, AccountRead, AccountUpdate
from app.crud.crud_account import (
    create_account,
    list_accounts_for_user,
    get_account,
    update_account_name,
    delete_account,
)

router = APIRouter(tags=["accounts"])


def is_admin(user) -> bool:
    return getattr(user, "role", None) == "admin"


def ensure_access(account, current_user):
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if (account.owner_user_id != current_user.id) and (not is_admin(current_user)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")


@router.get("/accounts", response_model=list[AccountRead])
def get_my_accounts(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return list_accounts_for_user(db, current_user.id)


@router.post("/accounts", response_model=AccountRead)
def create_my_account(
    payload: AccountCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    if payload.parent_account_id:
        parent = get_account(db, payload.parent_account_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent account not found")
        ensure_access(parent, current_user)
        if parent.account_type != "trust":
            raise HTTPException(status_code=400, detail="Parent must be a trust account")
    return create_account(db, current_user.id, payload)


@router.patch("/accounts/{account_id}", response_model=AccountRead)
def update_account(
    account_id: int,
    payload: AccountUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    account = get_account(db, account_id)
    ensure_access(account, current_user)
    name = payload.name.strip() if payload.name else ""
    if not name:
        raise HTTPException(status_code=400, detail="Account name required")
    return update_account_name(db, account, name)


@router.delete("/accounts/{account_id}")
def remove_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    account = get_account(db, account_id)
    ensure_access(account, current_user)
    delete_account(db, account)
    return {"status": "deleted"}
