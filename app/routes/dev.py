from datetime import datetime, UTC
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud.crud_user import create_user, get_user_by_email, get_user_by_username
from app.db.session import get_db
from app.models.ether import EtherSyncRequest, Profile
from app.models.user import User

router = APIRouter(prefix="/dev", tags=["dev"])


class SeedUserRequest(BaseModel):
    email: str | None = None
    username: str | None = None
    password: str | None = None
    verified: bool = False


class SyncAllRequest(BaseModel):
    admin_email: str | None = None


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
    if payload.verified:
        user.email_verified = True
        user.email_verification_token = None
        user.email_verification_expires_at = None
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
            continue
        db.add(
            EtherSyncRequest(
                requester_profile_id=profile.id,
                target_profile_id=admin_profile.id,
                status="approved",
            )
        )
        created += 1

    if created:
        db.commit()

    return {"admin_email": admin_email, "synced": created, "total_profiles": len(profiles)}
