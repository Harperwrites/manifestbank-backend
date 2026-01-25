# app/routes/journal.py

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import io

from app.core.security import get_verified_user
from app.db.session import get_db
from app.models.journal import JournalEntry
from app.schemas.journal import JournalEntryCreate, JournalEntryRead, JournalEntryUpdate
from app.services.r2 import upload_bytes, build_key


router = APIRouter(tags=["journal"])
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _ensure_owned(entry: JournalEntry, user_id: int) -> None:
    if entry.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed")


@router.get("/journal", response_model=list[JournalEntryRead])
def list_entries(
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    return (
        db.query(JournalEntry)
        .filter(JournalEntry.user_id == current_user.id)
        .order_by(JournalEntry.created_at.desc())
        .all()
    )


@router.post("/journal", response_model=JournalEntryRead)
def create_entry(
    payload: JournalEntryCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    entry = JournalEntry(user_id=current_user.id, **payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/journal/{entry_id}", response_model=JournalEntryRead)
def get_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    entry = db.query(JournalEntry).filter(JournalEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    _ensure_owned(entry, current_user.id)
    return entry


@router.put("/journal/{entry_id}", response_model=JournalEntryRead)
def update_entry(
    entry_id: int,
    payload: JournalEntryUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_verified_user),
):
    entry = db.query(JournalEntry).filter(JournalEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    _ensure_owned(entry, current_user.id)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(entry, key, value)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/journal/upload-image")
def upload_journal_image(
    file: UploadFile = File(...),
    current_user=Depends(get_verified_user),
):
    content_type = file.content_type or "image/jpeg"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are supported.")
    payload = file.file.read()
    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds 5MB limit.")
    key = build_key(f"journals/{current_user.id}", file.filename or "journal.jpg")
    url = upload_bytes(io.BytesIO(payload), key, content_type)
    return {"url": url}
