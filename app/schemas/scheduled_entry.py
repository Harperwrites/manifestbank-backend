# app/schemas/scheduled_entry.py

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class ScheduledEntryCreate(BaseModel):
    account_id: int
    direction: str
    amount: Decimal
    currency: str = "USD"
    entry_type: str = "scheduled"
    reference: str | None = None
    memo: str | None = None
    scheduled_for: datetime


class ScheduledEntryRead(BaseModel):
    id: int
    account_id: int
    created_by_user_id: int
    direction: str
    amount: Decimal
    currency: str
    entry_type: str
    status: str
    reference: str | None = None
    memo: str | None = None
    scheduled_for: datetime
    created_at: datetime
    posted_at: datetime | None = None
    posted_entry_id: int | None = None

    class Config:
        from_attributes = True
