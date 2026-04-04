# app/models/credit.py

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class CreditAction(Base):
    __tablename__ = "credit_actions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(160), nullable=False)
    description = Column(String(400), nullable=False)
    primary_bureau = Column(String(40), nullable=False)
    secondary_bureau = Column(String(40), nullable=True)
    confirmation_copy = Column(String(200), nullable=False)
    action_type = Column(String(80), nullable=True, index=True)
    action_route = Column(String(120), nullable=True)
    active = Column(Boolean, default=True, server_default="true", nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now(), server_default=func.now(), nullable=False)

    completions = relationship("CreditActionCompletion", back_populates="action")


class CreditActionCompletion(Base):
    __tablename__ = "credit_action_completions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action_id = Column(Integer, ForeignKey("credit_actions.id"), nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), default=func.now(), server_default=func.now(), nullable=False)

    action = relationship("CreditAction", back_populates="completions")


class CreditScoreSnapshot(Base):
    __tablename__ = "credit_score_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    bureau = Column(String(40), nullable=False)
    score = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now(), server_default=func.now(), nullable=False)


class CreditTodo(Base):
    __tablename__ = "credit_todos"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action_id = Column(Integer, ForeignKey("credit_actions.id"), nullable=False, index=True)
    action_type = Column(String(80), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="open")
    created_at = Column(DateTime(timezone=True), default=func.now(), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    action = relationship("CreditAction")
