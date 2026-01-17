# app/routes/users.py

from fastapi import APIRouter, Depends
from app.auth.deps import get_current_user
from app.schemas.user import UserRead

router = APIRouter(prefix="/users", tags=["users"])

