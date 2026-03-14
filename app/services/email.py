from __future__ import annotations

from datetime import datetime, UTC
import logging
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def _send_email(to_email: str, subject: str, html: str, reply_to: str | None = None) -> bool:
    primary_key = settings.RESEND_API_KEY
    primary_sender = settings.RESEND_FROM_EMAIL
    if not primary_key or not primary_sender:
        logger.error("Resend credentials missing; verify RESEND_API_KEY and RESEND_FROM_EMAIL.")
        return False

    payload = {
        "from": primary_sender,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    def _post(api_key: str, body: dict) -> httpx.Response:
        return httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=10,
        )

    try:
        res = _post(primary_key, payload)
        res.raise_for_status()
        return True
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        logger.warning("Primary Resend failed (%s) for %s", status_code, to_email)
        if status_code not in {429, 500, 502, 503, 504}:
            logger.exception("Email failed for %s", to_email)
            return False
    except Exception:
        logger.exception("Primary Resend error for %s", to_email)

    fallback_key = settings.RESEND_FALLBACK_API_KEY
    fallback_sender = settings.RESEND_FALLBACK_FROM_EMAIL
    if not fallback_key or not fallback_sender:
        logger.error("Fallback Resend credentials missing; verify RESEND_FALLBACK_API_KEY and RESEND_FALLBACK_FROM_EMAIL.")
        return False

    payload["from"] = fallback_sender
    try:
        res = _post(fallback_key, payload)
        res.raise_for_status()
        logger.info("Fallback Resend delivered for %s", to_email)
        return True
    except Exception:
        logger.exception("Fallback Resend failed for %s", to_email)
        return False


def send_verification_email(to_email: str, token: str) -> bool:
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

    return _send_email(to_email, "Verify your ManifestBank email", html)


def send_password_reset_email(to_email: str, token: str) -> bool:
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

    return _send_email(to_email, "Reset your ManifestBank password", html)


def send_signup_alert_email(to_email: str, user_email: str, username: str | None) -> bool:
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

    return _send_email(to_email, "New ManifestBank signup", html)


def send_contact_email(to_email: str, name: str, email: str, subject: str, message: str) -> bool:
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

    return _send_email(to_email, f"ManifestBank Contact: {subject}", html, reply_to=email)


def send_subscription_alert_email(to_email: str, user_email: str, username: str | None, plan: str | None) -> bool:
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

    return _send_email(to_email, "New ManifestBank™ Signature Member", html)


def send_trial_grant_email(to_email: str, username: str | None, trial_days: int) -> bool:
    display = username or to_email.split("@")[0]
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; color: #2b2320;">
      <p style="margin: 0 0 12px;">Thank you for being a part of the ManifestBank™ community. Truly. This space exists because of you.</p>
      <p style="margin: 0 0 12px;">We’re excited to let you know that ManifestBank™ now offers subscriptions, and as a thank-you for being an early supporter, we’ve activated something special for you.</p>
      <p style="margin: 0 0 12px;">✨ You’ve been granted a complimentary {trial_days}-day free trial of the ManifestBank™ Signature Membership.<br/>No card required. No action needed.</p>
      <p style="margin: 0 0 12px;">Your trial starts immediately, giving you full access to Signature features designed to deepen your intention practice, clarity, and alignment with abundance as a system, not a wish.</p>
      <p style="margin: 0 0 12px;">This is our way of saying thank you for building with us from the beginning.</p>
      <p style="margin: 0 0 12px;">When your {trial_days} days are complete, you’ll have the option to continue if it feels aligned. Until then, enjoy the full Signature experience on us.</p>
      <p style="margin: 18px 0 0;">With appreciation and momentum,<br/>The ManifestBank™ Team</p>
      <p style="font-size:12px;opacity:0.7;margin-top:18px;">
        ManifestBank™ is a mindset and visualization platform. It is not a financial institution.
      </p>
      <p style="font-size:12px;opacity:0.7;margin-top:12px;">
        Sent {datetime.now(UTC).strftime('%b %d, %Y %I:%M %p UTC')} • {display}
      </p>
    </div>
    """

    return _send_email(to_email, f"ManifestBank™ Signature — {trial_days} days on us", html)


def send_myline_message_email(
    to_email: str,
    sender_name: str,
    thread_id: int,
    preview: str,
) -> bool:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    thread_url = f"{base}/myline/{thread_id}"
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; color: #2b2320;">
      <h2 style="margin: 0 0 10px;">New My Line message</h2>
      <p style="margin: 0 0 12px;"><strong>{sender_name}</strong> sent you a new message.</p>
      <p style="margin: 0 0 16px; padding: 10px 12px; background: #f7f2ef; border-radius: 12px;">{preview}</p>
      <p style="margin: 0 0 18px;">
        <a href="{thread_url}" style="display:inline-block;padding:10px 16px;border-radius:999px;text-decoration:none;background:#b67967;color:white;font-weight:600;">
          Open My Line
        </a>
      </p>
      <p style="font-size:12px;opacity:0.7;">If the button doesn't work, paste this link into your browser:</p>
      <p style="font-size:12px;word-break:break-all;">{thread_url}</p>
      <p style="font-size:12px;opacity:0.7;margin-top:18px;">
        Sent {datetime.now(UTC).strftime('%b %d, %Y %I:%M %p UTC')}
      </p>
    </div>
    """
    return _send_email(to_email, "ManifestBank™ — New My Line message", html)


def send_post_comment_email(
    to_email: str,
    commenter_name: str,
    post_id: int,
    comment_id: int,
    preview: str,
) -> bool:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    post_url = f"{base}/ether?post_id={post_id}&comment_id={comment_id}"
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; color: #2b2320;">
      <h2 style="margin: 0 0 10px;">New comment on your post</h2>
      <p style="margin: 0 0 12px;"><strong>{commenter_name}</strong> commented on your post.</p>
      <p style="margin: 0 0 16px; padding: 10px 12px; background: #f7f2ef; border-radius: 12px;">{preview}</p>
      <p style="margin: 0 0 18px;">
        <a href="{post_url}" style="display:inline-block;padding:10px 16px;border-radius:999px;text-decoration:none;background:#b67967;color:white;font-weight:600;">
          View comment
        </a>
      </p>
      <p style="font-size:12px;opacity:0.7;">If the button doesn't work, paste this link into your browser:</p>
      <p style="font-size:12px;word-break:break-all;">{post_url}</p>
      <p style="font-size:12px;opacity:0.7;margin-top:18px;">
        Sent {datetime.now(UTC).strftime('%b %d, %Y %I:%M %p UTC')}
      </p>
    </div>
    """
    return _send_email(to_email, "ManifestBank™ — New comment", html)


def send_ledger_post_email(
    to_email: str,
    account_name: str,
    direction: str,
    amount: str,
    entry_type: str,
    link_path: str,
) -> bool:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    link = f"{base}{link_path}"
    verb = "credited" if direction == "credit" else "debited"
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; color: #2b2320;">
      <h2 style="margin: 0 0 10px;">Account update</h2>
      <p style="margin: 0 0 12px;">A {entry_type} was {verb} to <strong>{account_name}</strong>.</p>
      <p style="margin: 0 0 16px; padding: 10px 12px; background: #f7f2ef; border-radius: 12px;">
        Amount: <strong>{amount}</strong>
      </p>
      <p style="margin: 0 0 18px;">
        <a href="{link}" style="display:inline-block;padding:10px 16px;border-radius:999px;text-decoration:none;background:#b67967;color:white;font-weight:600;">
          View details
        </a>
      </p>
      <p style="font-size:12px;opacity:0.7;">If the button doesn't work, paste this link into your browser:</p>
      <p style="font-size:12px;word-break:break-all;">{link}</p>
      <p style="font-size:12px;opacity:0.7;margin-top:18px;">
        Sent {datetime.now(UTC).strftime('%b %d, %Y %I:%M %p UTC')}
      </p>
    </div>
    """
    return _send_email(to_email, "ManifestBank™ — Account update", html)


def send_signature_account_fix_email(
    to_email: str,
    contact_line_html: str,
) -> bool:
    html = f"""
    <div style="font-family: 'Helvetica Neue', Arial, sans-serif; color: #2b2320;">
      <p style="margin: 0 0 12px;">Dear ManifestBank™ Signature Member,</p>
      <p style="margin: 0 0 12px;">Thank you for being a valued part of the ManifestBank™ community.</p>
      <p style="margin: 0 0 12px;">We recently identified an issue that affected the creation of multiple accounts within some user dashboards. We sincerely apologize for any confusion or inconvenience this may have caused.</p>
      <p style="margin: 0 0 12px;"><strong>The issue has now been fully resolved.</strong></p>
      <p style="margin: 0 0 12px;">As a <strong>ManifestBank™ Signature Member</strong>, you can create <strong>unlimited accounts</strong> within your ManifestBank™ dashboard to organize your intentions, financial visualizations, and personal goals exactly the way you choose.</p>
      <p style="margin: 0 0 12px;">Your continued support means a great deal to us, and we’re grateful to have you building this experience alongside us. ManifestBank™ is growing every day because of members like you who believe in the vision and actively use the platform.</p>
      <p style="margin: 0 0 12px;">{contact_line_html}</p>
      <p style="margin: 0 0 12px;">Thank you again for being part of ManifestBank™ and for being a Signature Member.</p>
      <p style="margin: 18px 0 0;">Warm regards,<br/>The ManifestBank™ Team</p>
    </div>
    """
    subject = "ManifestBank™ Update — Issue Resolved & Thank You for Your Support"
    return _send_email(to_email, subject, html)
