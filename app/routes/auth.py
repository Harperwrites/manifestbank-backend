from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from passlib.exc import UnknownHashError
from datetime import datetime, timedelta, UTC
import secrets

from app.schemas.user import (
    UserCreate,
    UserRead,
    ResetPassword,
    UserLogin,
    PasswordResetRequest,
    PasswordResetConfirm,
)
from pydantic import BaseModel
from app.crud.crud_user import (
    create_user,
    get_user_by_email,
    get_user_by_username,
    update_user_password,
)
from app.crud.crud_subscriber import ensure_subscriber
from app.core.security import (
    verify_password,
    create_access_token,
    decode_access_token,
    get_current_user,
)
from app.schemas.account import AccountCreate
from app.schemas.ledger import LedgerEntryCreate
from app.models.account import Account
from app.models.ether import Profile, EtherSyncRequest
from app.models.user import User
from app.crud.crud_account import create_account
from app.crud.crud_ledger import create_ledger_entry
from app.db.session import get_db
from app.core.config import settings
from app.services.email import (
    send_verification_email,
    send_password_reset_email,
    send_signup_alert_email,
)
from app.services.moderation import moderate_text
from jose import JWTError

router = APIRouter(tags=["auth"])  # no prefix

class UsernameUpdate(BaseModel):
    username: str

def _set_verification_token(user: User) -> str:
    token = secrets.token_urlsafe(32)
    user.email_verification_token = token
    user.email_verification_expires_at = datetime.now(UTC) + timedelta(
        hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS
    )
    return token

@router.post("/register", response_model=UserRead)
def register(user: UserCreate, db: Session = Depends(get_db)):
    ok, reason = moderate_text(user.username)
    if not ok:
        raise HTTPException(status_code=400, detail=reason or "Text rejected.")
    existing = get_user_by_email(db, user.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    existing_username = get_user_by_username(db, user.username)
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already registered")
    created = create_user(db, user.email, user.password, user.username)
    token = _set_verification_token(created)
    db.add(created)
    db.commit()
    db.refresh(created)
    display = user.username or user.email.split("@")[0]
    existing_profile = db.query(Profile).filter(Profile.user_id == created.id).first()
    if not existing_profile:
        profile = Profile(user_id=created.id, display_name=display, is_public=True)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    else:
        profile = existing_profile

    admin_user = db.query(User).filter(func.lower(User.email) == "billionairebrea@wealth.com").first()
    if admin_user:
        admin_profile = db.query(Profile).filter(Profile.user_id == admin_user.id).first()
        if not admin_profile:
            admin_profile = Profile(
                user_id=admin_user.id,
                display_name=admin_user.username or admin_user.email.split("@")[0],
                is_public=True,
            )
            db.add(admin_profile)
            db.commit()
            db.refresh(admin_profile)
        existing_sync = (
            db.query(EtherSyncRequest)
            .filter(
                EtherSyncRequest.requester_profile_id == profile.id,
                EtherSyncRequest.target_profile_id == admin_profile.id,
            )
            .first()
        )
        if not existing_sync:
            sync_request = EtherSyncRequest(
                requester_profile_id=profile.id,
                target_profile_id=admin_profile.id,
                status="approved",
            )
            db.add(sync_request)
            db.commit()
    ensure_subscriber(db, user.email, source="register")
    if settings.SIGNUP_ALERT_EMAIL:
        send_signup_alert_email(settings.SIGNUP_ALERT_EMAIL, created.email, created.username)
    if not send_verification_email(created.email, token):
        raise HTTPException(
            status_code=502,
            detail="Verification email failed to send. Please try again later.",
        )
    return created

@router.post("/login")
def login(payload: UserLogin, db: Session = Depends(get_db)):
    identifier = (payload.identifier or payload.email or "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="Email or username required")
    db_user = get_user_by_email(db, identifier) or get_user_by_username(db, identifier)
    if not db_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    try:
        ok = verify_password(payload.password, db_user.hashed_password)
    except UnknownHashError:
        ok = False

    if not ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token({"sub": str(db_user.id)})
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me", response_model=UserRead)
def read_me(current_user=Depends(get_current_user)):
    return current_user


@router.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email_verification_token == token).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid verification link")
    if user.email_verified:
        return {"status": "already_verified"}
    if user.email_verification_expires_at and user.email_verification_expires_at < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Verification link expired")
    user.email_verified = True
    user.email_verification_token = None
    user.email_verification_expires_at = None
    db.add(user)
    db.commit()
    return {"status": "verified"}


@router.post("/verify-email/resend")
def resend_verification_email(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.email_verified:
        return {"status": "already_verified"}
    token = _set_verification_token(current_user)
    db.add(current_user)
    db.commit()
    if not send_verification_email(current_user.email, token):
        raise HTTPException(
            status_code=502,
            detail="Verification email failed to send. Please try again later.",
        )
    return {"status": "sent"}


@router.get("/username-available")
def username_available(
    username: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cleaned = username.strip()
    if not cleaned:
        return {"available": False}
    if current_user.username and cleaned.lower() == current_user.username.lower():
        return {"available": True}
    existing = (
        db.query(User)
        .filter(func.lower(User.username) == cleaned.lower())
        .first()
    )
    return {"available": False if existing else True}


@router.patch("/username", response_model=UserRead)
def update_username(
    payload: UsernameUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cleaned = payload.username.strip()
    ok, reason = moderate_text(cleaned)
    if not ok:
        raise HTTPException(status_code=400, detail=reason or "Text rejected.")
    if not cleaned:
        raise HTTPException(status_code=400, detail="Username required")
    if current_user.username and cleaned.lower() == current_user.username.lower():
        return current_user
    existing = (
        db.query(User)
        .filter(func.lower(User.username) == cleaned.lower())
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    current_user.username = cleaned
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/reset-password")
def reset_password(payload: ResetPassword, db: Session = Depends(get_db)):
    user = get_user_by_email(db, payload.email)
    if not user:
        raise HTTPException(status_code=404, detail="Email not found")
    update_user_password(db, user, payload.new_password)
    ensure_subscriber(db, payload.email, source="reset-password")
    return {"status": "password updated"}


@router.post("/password-reset/request")
def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db, payload.email)
    if not user:
        return {"status": "sent"}
    token = create_access_token(
        {"sub": str(user.id), "purpose": "password_reset"},
        expires_delta=timedelta(hours=settings.PASSWORD_RESET_EXPIRE_HOURS),
    )
    if not send_password_reset_email(user.email, token):
        raise HTTPException(
            status_code=502,
            detail="Password reset email failed to send. Please try again later.",
        )
    ensure_subscriber(db, user.email, source="password-reset")
    return {"status": "sent"}


@router.post("/password-reset/confirm")
def confirm_password_reset(payload: PasswordResetConfirm, db: Session = Depends(get_db)):
    try:
        claims = decode_access_token(payload.token)
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    if claims.get("purpose") != "password_reset":
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    update_user_password(db, user, payload.new_password)
    ensure_subscriber(db, user.email, source="password-reset")
    return {"status": "password updated"}


@router.post("/claim-welcome")
def claim_welcome_bonus(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if getattr(current_user, "welcome_bonus_claimed", False):
        raise HTTPException(status_code=400, detail="Welcome bonus already claimed")

    account = (
        db.query(Account)
        .filter(
            Account.owner_user_id == current_user.id,
            Account.account_type == "wealth_builder",
        )
        .first()
    )
    if not account:
        account_payload = AccountCreate(
            name="Wealth Builder",
            account_type="wealth_builder",
            is_active=True,
        )
        account = create_account(db, current_user.id, account_payload)
    create_ledger_entry(
        db,
        current_user.id,
        LedgerEntryCreate(
            account_id=account.id,
            direction="credit",
            amount=999,
            currency="USD",
            entry_type="welcome",
            status="posted",
            reference="welcome-bonus",
            idempotency_key=f"welcome:{current_user.id}",
            memo="ManifestBank welcome deposit",
            meta={"source": "welcome"},
        ),
    )

    current_user.welcome_bonus_claimed = True
    db.add(current_user)
    db.commit()
    return {"status": "welcome bonus claimed", "account_id": account.id}
