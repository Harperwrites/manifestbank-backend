"""Durable admin email queue. Existing campaign history stays authoritative."""
from datetime import datetime, UTC
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, UniqueConstraint
from app.db.session import Base

class EmailJob(Base):
    __tablename__ = 'email_center_jobs'
    id = Column(String(36), primary_key=True)
    campaign = Column(String(80), nullable=False)
    sender = Column(String(40), nullable=False)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    requested = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default='preparing')
    note = Column(String(500), nullable=False, default='')
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    approved_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    lease_until = Column(DateTime(timezone=True))
    resume_at = Column(DateTime(timezone=True))

class EmailJobRecipient(Base):
    __tablename__ = 'email_center_recipients'
    __table_args__ = (UniqueConstraint('job_id', 'email'),)
    id = Column(Integer, primary_key=True)
    job_id = Column(String(36), ForeignKey('email_center_jobs.id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    email = Column(String(320), nullable=False)
    status = Column(String(30), nullable=False, default='queued')
    delivery_id = Column(Integer, ForeignKey('promotion_emails.id'))
    detail = Column(String(500), nullable=False, default='')

class EmailSenderDay(Base):
    __tablename__ = 'email_center_sender_days'
    __table_args__ = (UniqueConstraint('sender_key', 'day'),)
    id = Column(Integer, primary_key=True)
    sender_key = Column(String(64), nullable=False)
    day = Column(String(10), nullable=False)
    used = Column(Integer, nullable=False, default=0)
    confirmed = Column(Boolean, nullable=False, default=False)
    source = Column(String(120), nullable=False, default='Not confirmed')

class EmailCenterAudit(Base):
    __tablename__ = 'email_center_audit'
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey('users.id'))
    job_id = Column(String(36))
    action = Column(String(80), nullable=False)
    detail = Column(String(500), nullable=False, default='')
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
