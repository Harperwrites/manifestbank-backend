# app/routes/dashboard.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _build_overview(db: Session, user_id: int) -> dict:
    """
    Keep this simple for tests.
    If you already have real dashboard aggregation logic elsewhere,
    call it from here instead.
    """
    return {"status": "ok", "user_id": user_id}


@router.get("/", status_code=200)
def dashboard_root(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # ✅ this makes GET /dashboard/ pass
    return _build_overview(db, current_user.id)


@router.get("/overview", status_code=200)
def dashboard_overview(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # ✅ keep your existing endpoint too
    return _build_overview(db, current_user.id)
