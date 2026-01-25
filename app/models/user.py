# app/models/user.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float
from sqlalchemy.orm import relationship

from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    welcome_bonus_claimed = Column(Boolean, default=False, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    role = Column(String, default="user", nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)
    email_verification_token = Column(String, nullable=True)
    email_verification_expires_at = Column(DateTime(timezone=True), nullable=True)
    wealth_target_usd = Column(Float, nullable=True)

    # ✅ User.accounts <-> Account.owner
    accounts = relationship(
        "Account",
        back_populates="owner",
        cascade="all, delete-orphan",
    )

    journals = relationship(
        "JournalEntry",
        back_populates="owner",
        cascade="all, delete-orphan",
    )
