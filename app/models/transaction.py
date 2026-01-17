# app/models/transaction.py

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)

    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)

    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String, nullable=False, default="USD")

    description = Column(String, nullable=True)
    category = Column(String, nullable=True)
    status = Column(String, nullable=False, default="posted")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ✅ Transaction.account <-> Account.transactions
    account = relationship("Account", back_populates="transactions", foreign_keys=[account_id])
