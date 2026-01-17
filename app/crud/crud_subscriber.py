# app/crud/crud_subscriber.py

from sqlalchemy.orm import Session

from app.models.subscriber import EmailSubscriber


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def ensure_subscriber(db: Session, email: str, source: str | None = None) -> EmailSubscriber:
    normalized = normalize_email(email)
    existing = db.query(EmailSubscriber).filter(EmailSubscriber.email == normalized).first()
    if existing:
        return existing

    subscriber = EmailSubscriber(email=normalized, source=source)
    db.add(subscriber)
    db.commit()
    db.refresh(subscriber)
    return subscriber
