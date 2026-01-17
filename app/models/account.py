# app/models/account.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)

    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    parent_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)

    name = Column(String, nullable=False)
    account_type = Column(String, nullable=False, default="personal")

    legal_name = Column(String, nullable=True)
    jurisdiction = Column(String, nullable=True)
    notes = Column(String, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ✅ Account.owner <-> User.accounts
    owner = relationship(
        "User",
        back_populates="accounts",
        foreign_keys=[owner_user_id],
    )

    # ✅ Account.transactions <-> Transaction.account
    transactions = relationship(
        "Transaction",
        back_populates="account",
        cascade="all, delete-orphan",
    )

    parent = relationship("Account", remote_side=[id], backref="children")
