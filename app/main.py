# main.py
from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.orm import Session
from backend.app.database import SessionLocal, engine, Base
from backend.app.models import User, BankAccount, Transaction, ManifestGoal, LedgerEntry
from pydantic import BaseModel

# Initialize DB
Base.metadata.create_all(bind=engine)

# FastAPI app
app = FastAPI(title="Manifest Bank API")

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Schemas ---
class UserCreate(BaseModel):
    name: str

class UserRead(BaseModel):
    id: int
    name: str

    class Config:
        orm_mode = True

# --- Routes ---
@app.post("/users/", response_model=UserRead)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = User(name=user.name)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.get("/users/", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).all()

@app.get("/")
def home():
    return {"message": "Welcome to Manifest Bank API!"}
