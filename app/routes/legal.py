# app/routes/legal.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, UTC

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.legal.content import TERMS_HASH, PRIVACY_HASH, TERMS_TEXT, PRIVACY_TEXT

router = APIRouter(tags=["legal"])

TERMS_VERSION = TERMS_HASH
PRIVACY_VERSION = PRIVACY_HASH


def ensure_user(user: User):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")


@router.get("/legal/consent")
def get_consent(current_user: User = Depends(get_current_user)):
    ensure_user(current_user)
    terms_match = (current_user.terms_version or "") == TERMS_VERSION
    privacy_match = (current_user.privacy_version or "") == PRIVACY_VERSION
    return {
        "termsAccepted": bool(current_user.terms_accepted_at) and terms_match,
        "privacyAccepted": bool(current_user.privacy_accepted_at) and privacy_match,
        "termsVersion": current_user.terms_version or TERMS_VERSION,
        "privacyVersion": current_user.privacy_version or PRIVACY_VERSION,
        "termsCurrentVersion": TERMS_VERSION,
        "privacyCurrentVersion": PRIVACY_VERSION,
        "needsReaccept": not (terms_match and privacy_match),
    }


@router.get("/legal/content")
def get_legal_content():
    return {
        "termsText": TERMS_TEXT,
        "privacyText": PRIVACY_TEXT,
        "termsHash": TERMS_HASH,
        "privacyHash": PRIVACY_HASH,
    }


@router.post("/legal/accept")
def accept_terms(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_user(current_user)
    now = datetime.now(UTC)
    current_user.terms_accepted_at = now
    current_user.privacy_accepted_at = now
    current_user.terms_version = TERMS_VERSION
    current_user.privacy_version = PRIVACY_VERSION
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return {
        "status": "accepted",
        "termsAccepted": True,
        "privacyAccepted": True,
        "termsVersion": TERMS_VERSION,
        "privacyVersion": PRIVACY_VERSION,
    }
