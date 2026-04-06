from datetime import datetime, UTC
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud.crud_user import create_user, get_user_by_email, get_user_by_username
from app.db.session import get_db
from app.legal.content import TERMS_HASH, PRIVACY_HASH
from app.models.ether import EtherSyncRequest, Profile
from app.models.legal_acceptance import LegalAcceptance
from app.models.user import User
from app.services.legal_acceptance import record_legal_acceptances

router = APIRouter(prefix="/dev", tags=["dev"])


class SeedUserRequest(BaseModel):
    email: str | None = None
    username: str | None = None
    password: str | None = None
    verified: bool = False
    premium: bool = False


class SyncAllRequest(BaseModel):
    admin_email: str | None = None


class LegalHistoryQuery(BaseModel):
    email: str | None = None
    user_id: int | None = None


@router.post("/seed-user")
def seed_user(
    payload: SeedUserRequest,
    db: Session = Depends(get_db),
    x_dev_seed: str | None = Header(default=None),
):
    if not settings.DEV_SEED_SECRET:
        raise HTTPException(status_code=404, detail="Not found")
    if x_dev_seed != settings.DEV_SEED_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dev seed secret")

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    random_suffix = secrets.token_hex(3)
    email = payload.email or f"test+{stamp}-{random_suffix}@wealth.dev"
    username = payload.username or f"test_{stamp}_{random_suffix}"
    password = payload.password or "Test*1234"

    if get_user_by_email(db, email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if get_user_by_username(db, username):
        raise HTTPException(status_code=400, detail="Username already registered")

    user = create_user(db, email, password, username)
    now = datetime.now(UTC)
    user.terms_accepted_at = now
    user.privacy_accepted_at = now
    user.terms_version = TERMS_HASH
    user.privacy_version = PRIVACY_HASH
    record_legal_acceptances(
        db,
        user,
        accepted_at=now,
        terms_version=TERMS_HASH,
        privacy_version=PRIVACY_HASH,
    )
    if payload.verified:
        user.email_verified = True
        user.email_verification_token = None
        user.email_verification_expires_at = None
    if payload.premium:
        user.is_premium = True
    if payload.verified or payload.premium:
        db.add(user)
        db.commit()
        db.refresh(user)

    display = username or email.split("@")[0]
    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    if not profile:
        profile = Profile(user_id=user.id, display_name=display, is_public=True)
        db.add(profile)
        db.commit()
        db.refresh(profile)

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

    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "password": password,
        "email_verified": user.email_verified,
        "is_premium": user.is_premium,
        "profile_id": profile.id,
    }


@router.post("/sync-all")
def sync_all_profiles(
    payload: SyncAllRequest,
    db: Session = Depends(get_db),
    x_dev_seed: str | None = Header(default=None),
):
    if not settings.DEV_SEED_SECRET:
        raise HTTPException(status_code=404, detail="Not found")
    if x_dev_seed != settings.DEV_SEED_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dev seed secret")

    admin_email = (payload.admin_email or "billionairebrea@wealth.com").strip().lower()
    admin_user = db.query(User).filter(func.lower(User.email) == admin_email).first()
    if not admin_user:
        raise HTTPException(status_code=404, detail="Admin user not found")

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

    profiles = db.query(Profile).filter(Profile.id != admin_profile.id).all()
    created = 0
    updated = 0
    for profile in profiles:
        existing_sync = (
            db.query(EtherSyncRequest)
            .filter(
                or_(
                    (EtherSyncRequest.requester_profile_id == profile.id)
                    & (EtherSyncRequest.target_profile_id == admin_profile.id),
                    (EtherSyncRequest.requester_profile_id == admin_profile.id)
                    & (EtherSyncRequest.target_profile_id == profile.id),
                )
            )
            .first()
        )
        if existing_sync:
            if existing_sync.status != "approved":
                existing_sync.status = "approved"
                updated += 1
            continue
        db.add(
            EtherSyncRequest(
                requester_profile_id=profile.id,
                target_profile_id=admin_profile.id,
                status="approved",
            )
        )
        created += 1

    if created or updated:
        db.commit()

    return {
        "admin_email": admin_email,
        "synced": created,
        "updated": updated,
        "total_profiles": len(profiles),
    }


@router.post("/legal-history")
def legal_history(
    payload: LegalHistoryQuery,
    db: Session = Depends(get_db),
    x_dev_seed: str | None = Header(default=None),
):
    if not settings.DEV_SEED_SECRET:
        raise HTTPException(status_code=404, detail="Not found")
    if x_dev_seed != settings.DEV_SEED_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dev seed secret")

    user = None
    if payload.user_id is not None:
        user = db.query(User).filter(User.id == payload.user_id).first()
    elif payload.email:
        user = db.query(User).filter(func.lower(User.email) == payload.email.strip().lower()).first()
    else:
        raise HTTPException(status_code=400, detail="Provide email or user_id")

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    history = (
        db.query(LegalAcceptance)
        .filter(LegalAcceptance.user_id == user.id)
        .order_by(LegalAcceptance.accepted_at.asc(), LegalAcceptance.document_type.asc())
        .all()
    )

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "terms_accepted_at": user.terms_accepted_at.isoformat() if user.terms_accepted_at else None,
            "privacy_accepted_at": user.privacy_accepted_at.isoformat() if user.privacy_accepted_at else None,
            "terms_version": user.terms_version,
            "privacy_version": user.privacy_version,
        },
        "history": [
            {
                "id": row.id,
                "document_type": row.document_type,
                "version": row.version,
                "accepted_at": row.accepted_at.isoformat(),
            }
            for row in history
        ],
    }
