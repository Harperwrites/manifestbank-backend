from sqlalchemy import Column, DateTime, Integer, String, ForeignKey, func, UniqueConstraint

from app.db.session import Base


class PwaEvent(Base):
    __tablename__ = "pwa_events"

    id = Column(Integer, primary_key=True, index=True)
    install_id = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    platform = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("install_id", "event_type", name="uq_pwa_event_install_type"),
    )
