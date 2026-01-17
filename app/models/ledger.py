# app/models/ledger.py

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Boolean,
    Numeric,
    Index,
    func,
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from app.db.session import Base


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True, index=True)

    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    direction = Column(String, nullable=False)  # "credit" | "debit"
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String, nullable=False, default="USD")

    entry_type = Column(String, nullable=False, default="manual")
    status = Column(String, nullable=False, default="posted")

    reference = Column(String, nullable=True)
    external_ref = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=True)

    memo = Column(String, nullable=True)

    # ✅ renamed from "metadata" to "meta" (metadata is reserved by SQLAlchemy)
    meta = Column(JSON, nullable=True)

    is_reversal = Column(Boolean, default=False)
    reversed_entry_id = Column(Integer, ForeignKey("ledger_entries.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    account = relationship("Account", backref="ledger_entries")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    reversal_of = relationship("LedgerEntry", remote_side=[id], uselist=False)

    __table_args__ = (
        Index("ix_ledger_account_created_at", "account_id", "created_at"),
        Index("ix_ledger_account_idempotency", "account_id", "idempotency_key", unique=False),
    )
