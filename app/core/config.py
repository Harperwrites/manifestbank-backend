import os
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

# This file is: backend/app/core/config.py
# We want BASE_DIR to be: backend/
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENV_PATH = os.path.join(BASE_DIR, ".env")


class Settings(BaseSettings):
    # ✅ Give DATABASE_URL a safe default so the app can boot even if .env is missing
    # Use Postgres by setting DATABASE_URL in backend/.env
    DATABASE_URL: str = "sqlite:///./app.db"

    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ALGORITHM: str = "HS256"
    CORS_ORIGINS: str = "http://localhost:3000"
    R2_ACCOUNT_ID: str | None = None
    R2_ACCESS_KEY_ID: str | None = None
    R2_SECRET_ACCESS_KEY: str | None = None
    R2_BUCKET: str | None = None
    R2_PUBLIC_BASE_URL: str | None = None
    RESEND_API_KEY: str | None = None
    RESEND_FROM_EMAIL: str | None = None
    SIGNUP_ALERT_EMAIL: str | None = None
    FRONTEND_BASE_URL: str = "http://localhost:3000"
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = 48
    PASSWORD_RESET_EXPIRE_HOURS: int = 2
    DEV_SEED_SECRET: str | None = None
    MODERATION_MODE: str = "lite"

    # ✅ Backwards-compatible alias for code expecting this name
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return self.DATABASE_URL

    model_config = ConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
    )


settings = Settings()
