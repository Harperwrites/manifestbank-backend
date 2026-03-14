# app/schemas/teller.py

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict


class TellerMessageCreate(BaseModel):
    content: str


class TellerMessageRead(BaseModel):
    id: int
    thread_id: int
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TellerThreadCreate(BaseModel):
    title: str | None = None


class TellerThreadUpdate(BaseModel):
    title: str


class TellerThreadRead(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TellerChatRequest(BaseModel):
    thread_id: int | None = None
    message: str
    short_mode: bool | None = None


class TellerChatResponse(BaseModel):
    thread: TellerThreadRead
    user_message: TellerMessageRead
    assistant_message: TellerMessageRead


class TellerConfirmRequest(BaseModel):
    thread_id: int | None = None
    action_type: str
    action_payload: Any | None = None


class TellerConfirmResponse(BaseModel):
    confirmation_id: int
    status: str


class TellerExecuteRequest(BaseModel):
    confirmation_id: int


class TellerExecuteResponse(BaseModel):
    status: str


class TellerStatusResponse(BaseModel):
    provider: str
    model: str
    mode: str


class TellerAuditLogRead(BaseModel):
    id: int
    user_id: int
    thread_id: int | None
    action_type: str
    status: str
    action_payload: Any | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
