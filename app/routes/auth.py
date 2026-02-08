from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from passlib.exc import UnknownHashError
from datetime import datetime, timedelta, UTC
import secrets
import re
import httpx

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
from app.legal.content import TERMS_HASH, PRIVACY_HASH
from jose import JWTError, jwt

router = APIRouter(tags=["auth"])  # no prefix

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"

class UsernameUpdate(BaseModel):
    username: str

def _set_verification_token(user: User) -> str:
    token = secrets.token_urlsafe(32)
    user.email_verification_token = token
    user.email_verification_expires_at = datetime.now(UTC) + timedelta(
        hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS
    )
    return token

def _ensure_google_config():
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET or not settings.GOOGLE_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="Google OAuth is not configured.")

def _create_state(next_path: str | None) -> str:
    payload = {
        "next": next_path or "/dashboard",
        "exp": datetime.now(UTC) + timedelta(minutes=10),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def _parse_state(state: str) -> dict:
    return jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

def _normalize_username(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "", text.replace(" ", "_")).lower()
    cleaned = cleaned[:24]
    if len(cleaned) < 3:
        cleaned = (cleaned + "user")[:24]
    return cleaned or "member"

def _unique_username(db: Session, base: str) -> str:
    candidate = base
    counter = 1
    while get_user_by_username(db, candidate):
        candidate = f"{base}{counter}"
        counter += 1
    return candidate

@router.post("/register", response_model=UserRead)
def register(user: UserCreate, db: Session = Depends(get_db)):
    if not user.accept_terms:
        raise HTTPException(status_code=400, detail="You must accept the Terms & Conditions and Privacy Policy.")
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
    created.terms_accepted_at = datetime.now(UTC)
    created.privacy_accepted_at = datetime.now(UTC)
    created.terms_version = TERMS_HASH
    created.privacy_version = PRIVACY_HASH
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

@router.get("/google/start")
def google_start(next: str | None = None):
    _ensure_google_config()
    state = _create_state(next)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "consent",
    }
    url = httpx.URL(GOOGLE_AUTH_URL, params=params)
    return RedirectResponse(str(url))

@router.get("/google/callback")
def google_callback(code: str, state: str, db: Session = Depends(get_db)):
    _ensure_google_config()
    try:
        state_data = _parse_state(state)
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")

    token_res = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if token_res.status_code != 200:
        raise HTTPException(status_code=400, detail="Google token exchange failed.")
    token_data = token_res.json()
    id_token = token_data.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="Missing id_token from Google.")

    info_res = httpx.get(GOOGLE_TOKENINFO_URL, params={"id_token": id_token}, timeout=20)
    if info_res.status_code != 200:
        raise HTTPException(status_code=400, detail="Google token verification failed.")
    info = info_res.json()
    email = info.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email.")

    db_user = get_user_by_email(db, email)
    if not db_user:
        display_name = info.get("name") or email.split("@")[0]
        base_username = _normalize_username(display_name)
        unique_username = _unique_username(db, base_username)
        random_password = secrets.token_urlsafe(32)
        db_user = create_user(db, email=email, password=random_password, username=unique_username)
        db_user.terms_accepted_at = None
        db_user.privacy_accepted_at = None
        db_user.terms_version = None
        db_user.privacy_version = None
        token = _set_verification_token(db_user)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        existing_profile = db.query(Profile).filter(Profile.user_id == db_user.id).first()
        if not existing_profile:
            profile = Profile(user_id=db_user.id, display_name=unique_username, is_public=True)
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

        ensure_subscriber(db, email, source="google_register")
        if settings.SIGNUP_ALERT_EMAIL:
            send_signup_alert_email(settings.SIGNUP_ALERT_EMAIL, db_user.email, db_user.username)
        if not send_verification_email(db_user.email, token):
            raise HTTPException(
                status_code=502,
                detail="Verification email failed to send. Please try again later.",
            )
    else:
        if not db_user.email_verified:
            db_user.email_verified = True
            db_user.email_verification_token = None
            db_user.email_verification_expires_at = None
            db.add(db_user)
            db.commit()

    access_token = create_access_token({"sub": str(db_user.id)})
    next_path = state_data.get("next") or "/dashboard"
    redirect_url = f"{settings.FRONTEND_BASE_URL}/auth/google/callback?token={access_token}&next={next_path}"
    return RedirectResponse(redirect_url)

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
