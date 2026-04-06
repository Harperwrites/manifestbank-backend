from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


class LegalAcceptance(Base):
    __tablename__ = "legal_acceptances"
    __table_args__ = (
        UniqueConstraint("user_id", "document_type", "version", name="uq_legal_acceptance_user_doc_version"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    document_type = Column(String, nullable=False)
    version = Column(String, nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User", back_populates="legal_acceptances")
