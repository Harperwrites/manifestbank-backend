from sqlalchemy.orm import Session
from app import models, auth
from typing import Optional

def get_user_by_username(db: Session, username: str) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.username == username).first()

def create_user(db: Session, username: str, password: str) -> models.User:
    hashed = auth.hash_password(password)
    user = models.User(username=username, hashed_password=hashed)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def create_account(db: Session, user_id: int, name: str = "Main"):
    acct = models.BankAccount(user_id=user_id, name=name)
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return acct

def get_account(db: Session, account_id: int):
    return db.query(models.BankAccount).filter(models.BankAccount.id == account_id).first()
