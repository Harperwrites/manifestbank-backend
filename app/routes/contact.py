from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.core.config import settings
from app.services.email import send_contact_email


router = APIRouter(tags=["contact"])


class ContactPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    subject: str = Field(..., min_length=1, max_length=160)
    message: str = Field(..., min_length=1, max_length=4000)


@router.post("/contact")
def submit_contact(payload: ContactPayload):
    to_email = settings.CONTACT_FORWARD_EMAIL or settings.SIGNUP_ALERT_EMAIL
    if not to_email:
        raise HTTPException(status_code=500, detail="Contact email not configured.")
    ok = send_contact_email(
        to_email=to_email,
        name=payload.name.strip(),
        email=payload.email,
        subject=payload.subject.strip(),
        message=payload.message.strip(),
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Unable to send message. Please try again later.")
    return {"status": "sent"}
