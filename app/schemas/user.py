# app/schemas/user.py

from pydantic import BaseModel, ConfigDict, EmailStr

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    username: str


class UserLogin(BaseModel):
    identifier: str | None = None
    email: str | None = None
    password: str

class UserRead(BaseModel):
    id: int
    email: str
    username: str | None = None
    role: str | None = None
    is_active: bool | None = True
    welcome_bonus_claimed: bool | None = False
    email_verified: bool | None = False

    model_config = ConfigDict(from_attributes=True)


class ResetPassword(BaseModel):
    email: str
    new_password: str
