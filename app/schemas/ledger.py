# app/schemas/ledger.py

from pydantic import BaseModel, Field
from typing import Optional, Literal, Any
from decimal import Decimal
from datetime import datetime


Direction = Literal["credit", "debit"]
Status = Literal["posted", "pending", "void"]


class LedgerEntryCreate(BaseModel):
    account_id: int
    direction: Direction
    amount: Decimal = Field(gt=0)
    currency: str = "USD"

    entry_type: str = "manual"
    status: Status = "posted"

    reference: Optional[str] = None
    external_ref: Optional[str] = None
    idempotency_key: Optional[str] = None

    memo: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


class LedgerEntryRead(BaseModel):
    id: int
    account_id: int
    created_by_user_id: int

    direction: Direction
    amount: Decimal
    currency: str

    entry_type: str
    status: Status

    reference: Optional[str] = None
    external_ref: Optional[str] = None
    idempotency_key: Optional[str] = None

    memo: Optional[str] = None
    meta: Optional[dict[str, Any]] = None

    is_reversal: bool
    reversed_entry_id: Optional[int] = None

    created_at: datetime

    class Config:
        from_attributes = True


class BalanceRead(BaseModel):
    account_id: int
    currency: str = "USD"
    balance: Decimal
    as_of: datetime


class TransferCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: Decimal = Field(gt=0)
    currency: str = "USD"
    memo: Optional[str] = None
    reference: Optional[str] = None
