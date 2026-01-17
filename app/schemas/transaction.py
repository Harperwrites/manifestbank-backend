# app/schemas/transaction.py

from datetime import datetime
from typing import Optional, Any, Dict

from pydantic import BaseModel, ConfigDict, Field


# ---------- Requests ----------

class DepositRequest(BaseModel):
    account_id: int
    amount: float = Field(gt=0)
    description: Optional[str] = None


class WithdrawRequest(BaseModel):
    account_id: int
    amount: float = Field(gt=0)
    description: Optional[str] = None


class TransferRequest(BaseModel):
    # ✅ match tests payload keys:
    # json={"from_id": id1, "to_id": id2, "amount": 400}
    from_id: int
    to_id: int
    amount: float = Field(gt=0)
    description: Optional[str] = None


# ---------- Responses ----------

class TransactionBase(BaseModel):
    account_id: int
    amount: float
    type: str
    timestamp: datetime
    description: Optional[str] = None


class TransactionRead(TransactionBase):
    id: int

    # ✅ Pydantic v2-safe: nested account blob for tests expecting "account" key
    account: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)
