from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    username: str
    password: str

class UserRead(BaseModel):
    id: int
    username: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    class Config:
        orm_mode = True

class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: Optional[str] = None

class TokenPayload(BaseModel):
    sub: Optional[str] = None
    exp: Optional[int] = None
    type: Optional[str] = None

class AccountCreate(BaseModel):
    name: Optional[str] = "Main"

class AccountRead(BaseModel):
    id: int
    user_id: int
    name: str
    balance: float
    class Config:
        orm_mode = True

class TransactionCreate(BaseModel):
    bank_account_id: int
    amount: float
    type: str
    label: Optional[str] = None
    description: Optional[str] = None

class TransactionRead(BaseModel):
    id: int
    bank_account_id: int
    amount: float
    type: str
    label: Optional[str]
    description: Optional[str]
    created_at: datetime
    class Config:
        orm_mode = True
