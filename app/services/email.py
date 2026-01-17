from __future__ import annotations

from datetime import datetime, UTC
import httpx

from app.core.config import settings


def send_verification_email(to_email: str, token: str) -> bool:
    api_key = settings.RESEND_API_KEY
    sender = settings.RESEND_FROM_EMAIL
    if not api_key or not sender:
        return False

    base = settings.FRONTEND_BASE_URL.rstrip("/")
    verify_url = f"{base}/verify-email?token={token}"
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; color: #2b2320;">
      <h2 style="margin: 0 0 10px;">Verify your ManifestBank email</h2>
      <p style="margin: 0 0 12px;">Confirm your email to unlock full access to ManifestBank.</p>
      <p style="margin: 0 0 18px;">
        <a href="{verify_url}" style="display:inline-block;padding:10px 16px;border-radius:999px;text-decoration:none;background:#b67967;color:white;font-weight:600;">
          Verify email
        </a>
      </p>
      <p style="font-size:12px;opacity:0.7;">If the button doesn't work, paste this link into your browser:</p>
      <p style="font-size:12px;word-break:break-all;">{verify_url}</p>
      <p style="font-size:12px;opacity:0.7;margin-top:18px;">
        Sent {datetime.now(UTC).strftime('%b %d, %Y %I:%M %p UTC')}
      </p>
    </div>
    """

    payload = {
        "from": sender,
        "to": [to_email],
        "subject": "Verify your ManifestBank email",
        "html": html,
    }

    try:
        res = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        res.raise_for_status()
        return True
    except Exception:
        return False
