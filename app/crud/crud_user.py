# app/crud/crud_user.py

from sqlalchemy.orm import Session
from app.models.user import User
from app.core.security import get_password_hash


def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()


def get_user_by_username(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()


def create_user(db: Session, email: str, password: str, username: str | None = None):
    if not password:
        raise ValueError("Password must not be empty")

    hashed_password = get_password_hash(password)

    user = User(
        email=email,
        username=username,
        hashed_password=hashed_password,
        is_active=True,
        role="user",
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_password(db: Session, user: User, password: str) -> User:
    if not password:
        raise ValueError("Password must not be empty")
    user.hashed_password = get_password_hash(password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
