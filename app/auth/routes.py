from fastapi import APIRouter, Depends, HTTPException
from app import schemas, crud, auth
from app.auth.jwt_handler import create_access_token, create_refresh_token
from app.auth.deps import get_db
from sqlalchemy.orm import Session

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=schemas.UserRead)
def register(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = crud.get_user_by_username(db, user_in.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already")
    user = crud.create_user(db, user_in.username, user_in.password)
    # create default account
    crud.create_account(db, user.id, name="Main")
    return user

@router.post("/login", response_model=schemas.Token)
def login(data: schemas.UserCreate, db: Session = Depends(get_db)):
    user = crud.get_user_by_username(db, data.username)
    if not user or not auth.verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access = create_access_token(user.username)
    refresh = create_refresh_token(user.username)
    return {"access_token": access, "token_type": "bearer", "refresh_token": refresh}

@router.post("/refresh", response_model=schemas.Token)
def refresh_token(refresh_token: str, db: Session = Depends(get_db)):
    payload = auth.decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token")
    username = payload.get("sub")
    user = crud.get_user_by_username(db, username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    access = create_access_token(username)
    refresh = create_refresh_token(username)
    return {"access_token": access, "token_type": "bearer", "refresh_token": refresh}
