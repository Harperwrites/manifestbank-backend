"""Additive campaign records; no edits to existing membership data."""
from datetime import datetime, UTC
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from app.db.session import Base

class PromotionLogin(Base):
    __tablename__ = "promotion_logins"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    is_new_signup = Column(Boolean, nullable=False, default=False)
    login_count = Column(Integer, nullable=False, default=0)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

class PromotionEmail(Base):
    __tablename__ = "promotion_emails"
    __table_args__ = (UniqueConstraint("campaign", "email"),)
    id = Column(Integer, primary_key=True)
    campaign = Column(String(80), nullable=False)
    email = Column(String(320), nullable=False)
    status = Column(String(30), nullable=False, default="pending")
    sent_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

class PromotionOptOut(Base):
    __tablename__ = "promotion_opt_outs"
    email = Column(String(320), primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
