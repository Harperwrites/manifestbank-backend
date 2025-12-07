from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.session import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(150), unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    accounts = relationship("BankAccount", back_populates="user")
    goals = relationship("ManifestGoal", back_populates="user")

class BankAccount(Base):
    __tablename__ = "bank_accounts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(200), default="Main")
    balance = Column(Float, default=0.0)

    user = relationship("User", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="bank_account")

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=False)
    amount = Column(Float, nullable=False)
    type = Column(String(50), nullable=False)  # deposit | withdrawal
    label = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    bank_account = relationship("BankAccount", back_populates="transactions")

class ManifestGoal(Base):
    __tablename__ = "manifest_goals"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(String(500), nullable=False)
    target_amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="goals")
    ledger_entries = relationship("LedgerEntry", back_populates="goal")

class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("manifest_goals.id"), nullable=False)
    description = Column(String(500))
    value = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    goal = relationship("ManifestGoal", back_populates="ledger_entries")
