from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app import schemas, crud
from app.auth.deps import get_current_user

router = APIRouter(prefix="/accounts", tags=["accounts"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/", response_model=list[schemas.AccountRead])
def list_accounts(user = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(crud.models.BankAccount).filter(crud.models.BankAccount.user_id == user.id).all()
