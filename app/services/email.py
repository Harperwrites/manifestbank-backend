from __future__ import annotations

from datetime import datetime, UTC
import logging
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_verification_email(to_email: str, token: str) -> bool:
    api_key = settings.RESEND_API_KEY
    sender = settings.RESEND_FROM_EMAIL
    if not api_key or not sender:
        logger.error("Resend credentials missing; verify RESEND_API_KEY and RESEND_FROM_EMAIL.")
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
        logger.exception("Verification email failed for %s", to_email)
        return False


def send_password_reset_email(to_email: str, token: str) -> bool:
    api_key = settings.RESEND_API_KEY
    sender = settings.RESEND_FROM_EMAIL
    if not api_key or not sender:
        logger.error("Resend credentials missing; verify RESEND_API_KEY and RESEND_FROM_EMAIL.")
        return False

    base = settings.FRONTEND_BASE_URL.rstrip("/")
    reset_url = f"{base}/reset-password?token={token}"
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; color: #2b2320;">
      <h2 style="margin: 0 0 10px;">Reset your ManifestBank password</h2>
      <p style="margin: 0 0 12px;">Use the button below to reset your password.</p>
      <p style="margin: 0 0 18px;">
        <a href="{reset_url}" style="display:inline-block;padding:10px 16px;border-radius:999px;text-decoration:none;background:#b67967;color:white;font-weight:600;">
          Reset password
        </a>
      </p>
      <p style="font-size:12px;opacity:0.7;">If the button doesn't work, paste this link into your browser:</p>
      <p style="font-size:12px;word-break:break-all;">{reset_url}</p>
      <p style="font-size:12px;opacity:0.7;margin-top:18px;">
        Sent {datetime.now(UTC).strftime('%b %d, %Y %I:%M %p UTC')}
      </p>
    </div>
    """

    payload = {
        "from": sender,
        "to": [to_email],
        "subject": "Reset your ManifestBank password",
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
        logger.exception("Password reset email failed for %s", to_email)
        return False


def send_signup_alert_email(to_email: str, user_email: str, username: str | None) -> bool:
    api_key = settings.RESEND_API_KEY
    sender = settings.RESEND_FROM_EMAIL
    if not api_key or not sender:
        logger.error("Resend credentials missing; verify RESEND_API_KEY and RESEND_FROM_EMAIL.")
        return False

    display = username or user_email.split("@")[0]
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; color: #2b2320;">
      <h2 style="margin: 0 0 10px;">New ManifestBank signup</h2>
      <p style="margin: 0 0 6px;"><strong>Email:</strong> {user_email}</p>
      <p style="margin: 0 0 6px;"><strong>Username:</strong> {display}</p>
      <p style="font-size:12px;opacity:0.7;margin-top:18px;">
        Sent {datetime.now(UTC).strftime('%b %d, %Y %I:%M %p UTC')}
      </p>
    </div>
    """

    payload = {
        "from": sender,
        "to": [to_email],
        "subject": "New ManifestBank signup",
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
        logger.exception("Signup alert email failed for %s", to_email)
        return False


def send_contact_email(to_email: str, name: str, email: str, subject: str, message: str) -> bool:
    api_key = settings.RESEND_API_KEY
    sender = settings.RESEND_FROM_EMAIL
    if not api_key or not sender:
        logger.error("Resend credentials missing; verify RESEND_API_KEY and RESEND_FROM_EMAIL.")
        return False

    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; color: #2b2320;">
      <h2 style="margin: 0 0 10px;">New ManifestBank contact request</h2>
      <p style="margin: 0 0 6px;"><strong>Name:</strong> {name}</p>
      <p style="margin: 0 0 6px;"><strong>Email:</strong> {email}</p>
      <p style="margin: 0 0 6px;"><strong>Subject:</strong> {subject}</p>
      <p style="margin: 12px 0 6px;"><strong>Message:</strong></p>
      <p style="margin: 0 0 6px; white-space: pre-line;">{message}</p>
      <p style="font-size:12px;opacity:0.7;margin-top:18px;">
        Sent {datetime.now(UTC).strftime('%b %d, %Y %I:%M %p UTC')}
      </p>
    </div>
    """

    payload = {
        "from": sender,
        "to": [to_email],
        "reply_to": email,
        "subject": f"ManifestBank Contact: {subject}",
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
        logger.exception("Contact email failed for %s", email)
        return False


def send_subscription_alert_email(to_email: str, user_email: str, username: str | None, plan: str | None) -> bool:
    api_key = settings.RESEND_API_KEY
    sender = settings.RESEND_FROM_EMAIL
    if not api_key or not sender:
        logger.error("Resend credentials missing; verify RESEND_API_KEY and RESEND_FROM_EMAIL.")
        return False

    display = username or user_email.split("@")[0]
    plan_label = (plan or "annual").strip() or "annual"
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; color: #2b2320;">
      <h2 style="margin: 0 0 10px;">New ManifestBank™ Signature Member</h2>
      <p style="margin: 0 0 6px;"><strong>Email:</strong> {user_email}</p>
      <p style="margin: 0 0 6px;"><strong>Username:</strong> {display}</p>
      <p style="margin: 0 0 6px;"><strong>Plan:</strong> {plan_label.title()}</p>
      <p style="font-size:12px;opacity:0.7;margin-top:18px;">
        Sent {datetime.now(UTC).strftime('%b %d, %Y %I:%M %p UTC')}
      </p>
    </div>
    """

    payload = {
        "from": sender,
        "to": [to_email],
        "subject": "New ManifestBank™ Signature Member",
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
        logger.exception("Subscription alert email failed for %s", to_email)
        return False
