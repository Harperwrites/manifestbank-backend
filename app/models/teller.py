# app/models/teller.py

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, func, JSON
from sqlalchemy.orm import relationship

from app.db.session import Base


class TellerThread(Base):
    __tablename__ = "teller_threads"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False, default="New Teller Session")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")
    messages = relationship(
        "TellerMessage",
        back_populates="thread",
        cascade="all, delete-orphan",
    )


class TellerMessage(Base):
    __tablename__ = "teller_messages"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("teller_threads.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user | assistant | system
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    thread = relationship("TellerThread", back_populates="messages")


class TellerAuditLog(Base):
    __tablename__ = "teller_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    thread_id = Column(Integer, ForeignKey("teller_threads.id"), nullable=True, index=True)
    action_type = Column(String(60), nullable=False)  # propose | confirm | execute | error
    status = Column(String(30), nullable=False, default="recorded")
    action_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")
    thread = relationship("TellerThread")
