# app/routes/affirmations.py

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import io

from app.core.security import get_verified_user
from app.db.session import get_db
from app.models.affirmation import AffirmationEntry
from app.schemas.affirmation import (
    AffirmationEntryCreate,
    AffirmationEntryRead,
    AffirmationEntryUpdate,
)
from app.services.r2 import upload_bytes, build_key
from app.services.moderation import moderate_image_bytes, moderate_text
from app.services.tier import (
    is_premium,
    count_affirmations,
    FREE_AFFIRMATION_LIMIT,
    TIER_NAME,
    SAVED_AFFIRMATION_TITLE,
)


router = APIRouter(tags=["affirmations"])
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _ensure_owned(entry: AffirmationEntry, user_id: int) -> None:
    if entry.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed")


@router.get("/affirmations", response_model=list[AffirmationEntryRead])
def list_entries(
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    return (
        db.query(AffirmationEntry)
        .filter(AffirmationEntry.user_id == current_user.id)
        .order_by(AffirmationEntry.created_at.desc())
        .all()
    )


@router.post("/affirmations", response_model=AffirmationEntryRead)
def create_entry(
    payload: AffirmationEntryCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    if payload.title == SAVED_AFFIRMATION_TITLE and not is_premium(current_user):
        raise HTTPException(
            status_code=402,
            detail=f"Saved affirmations are available on {TIER_NAME}. Upgrade to save affirmations.",
        )
    if not is_premium(current_user):
        if count_affirmations(db, current_user.id) >= FREE_AFFIRMATION_LIMIT:
            raise HTTPException(
                status_code=402,
                detail=f"Free tier allows 10 affirmation entries. Upgrade to {TIER_NAME} for unlimited entries.",
            )
    ok, reason = moderate_text(payload.title)
    if not ok:
        raise HTTPException(status_code=400, detail=reason or "Text rejected.")
    ok, reason = moderate_text(payload.content)
    if not ok:
        raise HTTPException(status_code=400, detail=reason or "Text rejected.")
    entry = AffirmationEntry(user_id=current_user.id, **payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/affirmations/{entry_id}", response_model=AffirmationEntryRead)
def get_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    entry = db.query(AffirmationEntry).filter(AffirmationEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    _ensure_owned(entry, current_user.id)
    return entry


@router.put("/affirmations/{entry_id}", response_model=AffirmationEntryRead)
def update_entry(
    entry_id: int,
    payload: AffirmationEntryUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    entry = db.query(AffirmationEntry).filter(AffirmationEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    _ensure_owned(entry, current_user.id)
    updates = payload.model_dump(exclude_unset=True)
    if "title" in updates:
        ok, reason = moderate_text(updates.get("title"))
        if not ok:
            raise HTTPException(status_code=400, detail=reason or "Text rejected.")
    if "content" in updates:
        ok, reason = moderate_text(updates.get("content"))
        if not ok:
            raise HTTPException(status_code=400, detail=reason or "Text rejected.")
    for key, value in updates.items():
        setattr(entry, key, value)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/affirmations/{entry_id}")
def delete_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    entry = db.query(AffirmationEntry).filter(AffirmationEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    _ensure_owned(entry, current_user.id)
    db.delete(entry)
    db.commit()
    return {"status": "deleted"}


@router.post("/affirmations/upload-image")
def upload_affirmation_image(
    file: UploadFile = File(...),
    current_user=Depends(get_verified_user),
):
    content_type = file.content_type or "image/jpeg"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are supported.")
    payload = file.file.read()
    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds 5MB limit.")
    ok, reason = moderate_image_bytes(payload)
    if not ok:
        raise HTTPException(status_code=400, detail=reason or "Image rejected.")
    key = build_key(f"affirmations/{current_user.id}", file.filename or "affirmation.jpg")
    url = upload_bytes(io.BytesIO(payload), key, content_type)
    return {"url": url}
