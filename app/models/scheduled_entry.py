# app/models/scheduled_entry.py

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import relationship

from app.db.session import Base


class ScheduledEntry(Base):
    __tablename__ = "scheduled_entries"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    direction = Column(String, nullable=False)  # credit | debit
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String, nullable=False, default="USD")
    entry_type = Column(String, nullable=False, default="scheduled")
    status = Column(String, nullable=False, default="pending")

    reference = Column(String, nullable=True)
    memo = Column(String, nullable=True)

    scheduled_for = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    posted_entry_id = Column(Integer, ForeignKey("ledger_entries.id"), nullable=True)

    account = relationship("Account", foreign_keys=[account_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])
