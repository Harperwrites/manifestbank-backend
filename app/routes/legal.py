# app/routes/legal.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, UTC

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.legal_acceptance import LegalAcceptance
from app.legal.content import TERMS_HASH, PRIVACY_HASH, TERMS_TEXT, PRIVACY_TEXT
from app.services.legal_acceptance import record_legal_acceptances

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
    has_prior_acceptance = bool(
        current_user.terms_accepted_at
        or current_user.privacy_accepted_at
        or current_user.terms_version
        or current_user.privacy_version
    )
    return {
        "termsAccepted": bool(current_user.terms_accepted_at) and terms_match,
        "privacyAccepted": bool(current_user.privacy_accepted_at) and privacy_match,
        "termsVersion": current_user.terms_version or TERMS_VERSION,
        "privacyVersion": current_user.privacy_version or PRIVACY_VERSION,
        "termsCurrentVersion": TERMS_VERSION,
        "privacyCurrentVersion": PRIVACY_VERSION,
        "needsReaccept": not (terms_match and privacy_match),
        "hasPriorAcceptance": has_prior_acceptance,
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
    record_legal_acceptances(
        db,
        current_user,
        accepted_at=now,
        terms_version=TERMS_VERSION,
        privacy_version=PRIVACY_VERSION,
    )
    db.commit()
    db.refresh(current_user)
    history_count = (
        db.query(LegalAcceptance)
        .filter(LegalAcceptance.user_id == current_user.id)
        .count()
    )
    return {
        "status": "accepted",
        "termsAccepted": True,
        "privacyAccepted": True,
        "termsVersion": TERMS_VERSION,
        "privacyVersion": PRIVACY_VERSION,
        "historyCount": history_count,
    }
