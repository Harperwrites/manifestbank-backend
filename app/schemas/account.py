# app/schemas/account.py

from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class AccountBase(BaseModel):
    name: str
    account_type: str = "personal"  # personal | trust | entity | vault
    currency: str = "USD"
    parent_account_id: Optional[int] = None
    legal_name: Optional[str] = None
    jurisdiction: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    currency: Optional[str] = None
    is_active: Optional[bool] = None


class AccountRead(AccountBase):
    id: int
    owner_user_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
