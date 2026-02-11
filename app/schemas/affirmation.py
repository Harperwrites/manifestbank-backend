# app/schemas/affirmation.py

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AffirmationEntryBase(BaseModel):
    title: str
    entry_date: date
    content: str
    image_url: Optional[str] = None


class AffirmationEntryCreate(AffirmationEntryBase):
    pass


class AffirmationEntryUpdate(BaseModel):
    title: Optional[str] = None
    entry_date: Optional[date] = None
    content: Optional[str] = None
    image_url: Optional[str] = None


class AffirmationEntryRead(AffirmationEntryBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
