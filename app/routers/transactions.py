from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app import schemas, models, crud
from app.auth.deps import get_current_user

router = APIRouter(prefix="/transactions", tags=["transactions"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=schemas.TransactionRead)
def create_transaction(tx: schemas.TransactionCreate, user = Depends(get_current_user), db: Session = Depends(get_db)):
    acct = crud.get_account(db, tx.bank_account_id)
    if not acct or acct.user_id != user.id:
        raise HTTPException(status_code=404, detail="Account not found")
    if tx.type == "deposit":
        acct.balance += tx.amount
    elif tx.type == "withdrawal":
        acct.balance -= tx.amount
        if acct.balance < 0:
            raise HTTPException(status_code=400, detail="Insufficient funds")
    else:
        raise HTTPException(status_code=400, detail="Invalid type")
    transaction = models.Transaction(bank_account_id=tx.bank_account_id, amount=tx.amount, type=tx.type, label=tx.label, description=tx.description)
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    db.refresh(acct)
    return transaction
