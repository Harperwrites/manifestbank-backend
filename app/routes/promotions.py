from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.core.security import get_current_user
from app.db.session import get_db
from app.services.november_offer import offer_status, opt_out

router = APIRouter(prefix="/promotions", tags=["promotions"])

@router.get("/november")
def november_status(response: Response, db: Session = Depends(get_db), user=Depends(get_current_user)):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return offer_status(db, user)
    except HTTPException:
        raise
    except Exception:
        # Never advertise to a possible subscriber when membership cannot be verified.
        raise HTTPException(503, "Membership eligibility is temporarily unavailable.")

@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_confirmation(token: str):
    from html import escape
    return f'<html lang="en"><meta name="viewport" content="width=device-width, initial-scale=1"><title>ManifestBank email preferences</title><body style="font-family:Arial;padding:40px;max-width:600px;margin:auto;background:#fffaf5;color:#36231c"><h1>Promotional email preferences</h1><p>Stop receiving ManifestBank promotional emails. Account and security messages will continue.</p><form method="post"><input type="hidden" name="token" value="{escape(token, quote=True)}"><button type="submit" style="padding:14px">Unsubscribe from promotional emails</button></form></body></html>'

@router.post("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    opt_out(db, str(form.get("token", "")))
    return '<html lang="en"><title>Unsubscribed</title><body style="font-family:Arial;padding:40px"><h1>You’re unsubscribed.</h1><p>You will no longer receive ManifestBank promotional emails. Account and security messages will continue.</p></body></html>'
