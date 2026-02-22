# app/schemas/user.py

from pydantic import BaseModel, ConfigDict, EmailStr

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    username: str
    accept_terms: bool


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
    wealth_target_usd: float | None = None
    is_premium: bool | None = False
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    stripe_price_id: str | None = None
    stripe_status: str | None = None
    stripe_current_period_end: str | None = None
    stripe_trial_end: str | None = None
    stripe_cancel_at_period_end: bool | None = False

    model_config = ConfigDict(from_attributes=True)


class ResetPassword(BaseModel):
    email: str
    new_password: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


class UserWealthTargetUpdate(BaseModel):
    wealth_target_usd: float | None = None
