from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import decode_access_token, get_user_by_id, require_role
from app.db.session import get_db
from app.models.pwa import PwaEvent

router = APIRouter(tags=["pwa"])

oauth2_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


class PwaTrackRequest(BaseModel):
    install_id: str
    event_type: str  # install_prompt_accepted | standalone_launch
    platform: str | None = None
    user_agent: str | None = None


@router.post("/pwa/track")
def track_pwa_event(
    payload: PwaTrackRequest,
    db: Session = Depends(get_db),
    token: str | None = Depends(oauth2_optional),
):
    user_id = None
    if token:
        try:
            payload_data = decode_access_token(token)
            sub = payload_data.get("sub")
            if sub:
                user = get_user_by_id(db, int(sub))
                if user:
                    user_id = user.id
        except Exception:
            user_id = None

    existing = (
        db.query(PwaEvent)
        .filter(PwaEvent.install_id == payload.install_id, PwaEvent.event_type == payload.event_type)
        .first()
    )
    if existing:
        return {"status": "duplicate"}

    event = PwaEvent(
        install_id=payload.install_id,
        event_type=payload.event_type,
        platform=payload.platform,
        user_agent=payload.user_agent,
        user_id=user_id,
    )
    db.add(event)
    db.commit()
    return {"status": "ok"}


@router.get("/admin/pwa/stats")
def pwa_stats(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    total_installs = db.query(PwaEvent).filter(PwaEvent.event_type == "install_prompt_accepted").count()
    total_standalone = db.query(PwaEvent).filter(PwaEvent.event_type == "standalone_launch").count()
    return {
        "install_prompt_accepted": total_installs,
        "standalone_launch": total_standalone,
    }
