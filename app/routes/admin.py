from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import require_role
from app.db.session import get_db
from app.models.subscriber import EmailSubscriber

router = APIRouter(tags=["admin"])

@router.get("/admin/heartbeat")
def admin_heartbeat(admin=Depends(require_role("admin"))):
    return {"status": "Admin access confirmed"}


@router.get("/admin/email-subscribers")
def list_email_subscribers(
    db: Session = Depends(get_db),
    admin=Depends(require_role("admin")),
):
    rows = (
        db.query(EmailSubscriber)
        .order_by(EmailSubscriber.created_at.desc())
        .all()
    )
    return [
        {
            "email": row.email,
            "source": row.source,
            "created_at": row.created_at,
        }
        for row in rows
    ]
