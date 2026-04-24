from __future__ import annotations

from datetime import datetime, UTC
from html import escape
import logging
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)
_primary_daily_date = None
_primary_daily_count = 0


def _stamp() -> str:
    return datetime.now(UTC).strftime('%b %d, %Y %I:%M %p UTC')


def _button(url: str, label: str) -> str:
    return f"""
    <a
      href="{escape(url, quote=True)}"
      style="display:inline-block;padding:12px 20px;border-radius:999px;text-decoration:none;background:#a75f52;color:#ffffff;font-weight:700;letter-spacing:0.01em;"
    >
      {escape(label)}
    </a>
    """


def _info_card(content: str) -> str:
    return f"""
    <div style="margin:0 0 18px;padding:14px 16px;border-radius:18px;background:#f4ebe4;color:#261b16;border:1px solid #e2cfc4;">
      {content}
    </div>
    """


def _email_shell(
    *,
    eyebrow: str,
    heading: str,
    body_html: str,
    cta_html: str | None = None,
    utility_html: str | None = None,
    footer_note: str | None = None,
) -> str:
    footer = footer_note or "ManifestBank™ is a digital reflection and wealth visualization platform. It is not a financial institution."
    base_url = settings.FRONTEND_BASE_URL.rstrip("/")
    logo_url = f"{base_url}/manifestbank-glow-edge-logo.png"
    logo_href = f"{base_url}/auth"
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="color-scheme" content="light only" />
        <meta name="supported-color-schemes" content="light" />
        <title>{escape(heading)}</title>
        <style>
          :root {{ color-scheme: light only; supported-color-schemes: light; }}
          body, table, td, div, p, span, li {{ color-scheme: light only; }}
          a {{ color:#1f65b7; }}
        </style>
      </head>
      <body bgcolor="#eee2dc" style="margin:0;padding:0;background:#eee2dc;color:#261b16;">
        <div style="margin:0;padding:14px 12px;background:#eee2dc;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
            <tr>
              <td align="center">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;border-collapse:collapse;">
                  <tr>
                    <td
                      bgcolor="#fffaf5"
                      style="border-radius:28px;background-color:#fffaf5;border:1px solid #d9c5ba;box-shadow:0 14px 34px rgba(77,49,40,0.12);font-family:'Helvetica Neue',Arial,sans-serif;color:#261b16;overflow:hidden;"
                    >
                      <div style="height:54px;background-color:#f5eee8;background-image:url('https://manifestbank.app/marble-veins.png');background-size:cover;background-position:center;border-radius:28px 28px 0 0;"></div>
                      <div style="padding:28px 32px 32px;background:#fffaf5;color:#261b16;">
                        <div style="text-align:center;margin:-6px 0 18px;">
                          <a href="{escape(logo_href, quote=True)}" style="display:inline-block;text-decoration:none;border:0;outline:none;">
                            <img
                              src="{escape(logo_url, quote=True)}"
                              alt="ManifestBank™"
                              width="126"
                              height="126"
                              style="display:inline-block;width:126px;height:126px;max-width:100%;border:0;outline:none;text-decoration:none;"
                            />
                          </a>
                        </div>
                        <div style="font-size:11px;letter-spacing:0.22em;text-transform:uppercase;color:#8b5147;margin:0 0 14px;">{escape(eyebrow)}</div>
                        <div style="font-family:Georgia,'Times New Roman',serif;font-size:32px;line-height:1.12;color:#241814;margin:0 0 16px;">{escape(heading)}</div>
                        <div style="font-size:16px;line-height:1.72;color:#261b16;">{body_html}</div>
                        {f'<div style="margin:24px 0 0;">{cta_html}</div>' if cta_html else ''}
                        {utility_html or ''}
                        <div style="margin-top:26px;padding-top:18px;border-top:1px solid #dfccc1;font-size:12px;line-height:1.6;color:#5d4840;">
                          <div>{escape(footer)}</div>
                          <div style="margin-top:8px;">Sent {_stamp()}</div>
                        </div>
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </div>
      </body>
    </html>
    """


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

    # If a primary daily cap is configured, route to fallback before we hit the limit.
    global _primary_daily_date, _primary_daily_count
    if settings.RESEND_PRIMARY_DAILY_LIMIT:
        today = datetime.now(UTC).date().isoformat()
        if _primary_daily_date != today:
            _primary_daily_date = today
            _primary_daily_count = 0
        buffer = max(0, settings.RESEND_PRIMARY_DAILY_BUFFER)
        if _primary_daily_count >= max(0, settings.RESEND_PRIMARY_DAILY_LIMIT - buffer):
            primary_key = None  # skip primary
            logger.info(
                "Primary Resend skipped due to daily cap guard (%s/%s, buffer=%s)",
                _primary_daily_count,
                settings.RESEND_PRIMARY_DAILY_LIMIT,
                buffer,
            )

    try:
        if primary_key:
            res = _post(primary_key, payload)
            res.raise_for_status()
            _primary_daily_count += 1
            logger.info("Primary Resend delivered for %s", to_email)
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
    utility_html = f"""
    <div style="margin-top:18px;font-size:12px;line-height:1.6;color:#7a675d;">
      <div>If the button does not work, paste this link into your browser:</div>
      <div style="margin-top:6px;word-break:break-all;color:#6f4a3a;">{escape(verify_url)}</div>
    </div>
    """
    html = _email_shell(
        eyebrow="Email Verification",
        heading="Verify your ManifestBank email",
        body_html="""
        <p style="margin:0 0 12px;">Confirm your email to unlock full access to ManifestBank™ and secure your account.</p>
        <p style="margin:0;">Once verified, you can continue into the platform with the full experience available to your membership.</p>
        """,
        cta_html=_button(verify_url, "Verify email"),
        utility_html=utility_html,
    )

    return _send_email(to_email, "Verify your ManifestBank email", html)


def send_password_reset_email(to_email: str, token: str) -> bool:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    reset_url = f"{base}/reset-password?token={token}"
    utility_html = f"""
    <div style="margin-top:18px;font-size:12px;line-height:1.6;color:#7a675d;">
      <div>If the button does not work, paste this link into your browser:</div>
      <div style="margin-top:6px;word-break:break-all;color:#6f4a3a;">{escape(reset_url)}</div>
    </div>
    """
    html = _email_shell(
        eyebrow="Security",
        heading="Reset your ManifestBank password",
        body_html="""
        <p style="margin:0 0 12px;">Use the button below to reset your password and return to your account.</p>
        <p style="margin:0;">If you did not request this reset, you can ignore this email and no changes will be made.</p>
        """,
        cta_html=_button(reset_url, "Reset password"),
        utility_html=utility_html,
    )

    return _send_email(to_email, "Reset your ManifestBank password", html)


def send_signup_alert_email(to_email: str, user_email: str, username: str | None) -> bool:
    display = username or user_email.split("@")[0]
    html = _email_shell(
        eyebrow="Admin Alert",
        heading="New ManifestBank signup",
        body_html=_info_card(
            f"""
            <div style="margin:0 0 8px;"><strong>Email:</strong> {escape(user_email)}</div>
            <div><strong>Username:</strong> {escape(display)}</div>
            """
        ),
    )

    return _send_email(to_email, "New ManifestBank signup", html)


def send_contact_email(to_email: str, name: str, email: str, subject: str, message: str) -> bool:
    html = _email_shell(
        eyebrow="Contact",
        heading="New ManifestBank contact request",
        body_html="""
        <p style="margin:0 0 14px;">A new contact request was submitted through the public site.</p>
        """
        + _info_card(
            f"""
            <div style="margin:0 0 8px;"><strong>Name:</strong> {escape(name)}</div>
            <div style="margin:0 0 8px;"><strong>Email:</strong> {escape(email)}</div>
            <div style="margin:0 0 8px;"><strong>Subject:</strong> {escape(subject)}</div>
            <div style="margin:14px 0 6px;"><strong>Message:</strong></div>
            <div style="white-space:pre-line;">{escape(message)}</div>
            """
        ),
    )

    return _send_email(to_email, f"ManifestBank Contact: {subject}", html, reply_to=email)


def send_subscription_alert_email(to_email: str, user_email: str, username: str | None, plan: str | None) -> bool:
    display = username or user_email.split("@")[0]
    plan_label = (plan or "annual").strip() or "annual"
    html = _email_shell(
        eyebrow="Membership Alert",
        heading="New ManifestBank™ Signature Member",
        body_html=_info_card(
            f"""
            <div style="margin:0 0 8px;"><strong>Email:</strong> {escape(user_email)}</div>
            <div style="margin:0 0 8px;"><strong>Username:</strong> {escape(display)}</div>
            <div><strong>Plan:</strong> {escape(plan_label.title())}</div>
            """
        ),
    )

    return _send_email(to_email, "New ManifestBank™ Signature Member", html)


def send_signature_welcome_email(to_email: str, username: str | None) -> bool:
    display = username or to_email.split("@")[0]
    body_html = f"""
    <p style="margin:0 0 12px;">Welcome to <strong>ManifestBank™ Signature</strong>, {escape(display)}.</p>
    <p style="margin:0 0 12px;">You didn’t just upgrade. You elevated.</p>
    <p style="margin:0 0 12px;">Signature is where intention becomes structured, where clarity compounds, and where your relationship with wealth moves with precision instead of chance. You now have access to a deeper layer of ManifestBank™: one designed for those who move differently.</p>
    <p style="margin:0 0 12px;">Inside Signature, you’ll notice:</p>
    <ul style="margin:0 0 18px 20px;padding:0;">
      <li style="margin:0 0 8px;">A more refined financial view: clean, expanded, and aligned with your vision.</li>
      <li style="margin:0 0 8px;">Advanced tools that respond to your decisions, not just your deposits.</li>
      <li style="margin:0;">A space where your mindset and your money finally speak the same language.</li>
    </ul>
    {_info_card("<strong>This is your environment now.</strong><br/>Use it intentionally. Move with certainty.")}
    <p style="margin:0 0 12px;">And remember: this isn’t about watching numbers. It’s about becoming the version of you those numbers naturally follow.</p>
    <p style="margin:0 0 12px;">If you ever want to go further, refine faster, or unlock more precision within your system, it’s all here waiting for you.</p>
    <p style="margin:0 0 12px;">Let’s build something inevitable.</p>
    <p style="margin:0;">— ManifestBank™</p>
    """
    utility_html = """
    <div style="margin-top:20px;padding:12px 14px;border-radius:16px;background:rgba(45,33,28,0.06);font-size:13px;line-height:1.55;color:#6f5a51;">
      Fortune is evolving in real time. Early access: continuously improving intelligence.
    </div>
    """
    html = _email_shell(
        eyebrow="Signature Welcome",
        heading="Welcome to ManifestBank™ Signature",
        body_html=body_html,
        cta_html=_button(f"{settings.FRONTEND_BASE_URL.rstrip('/')}/dashboard", "Enter Signature"),
        utility_html=utility_html,
        footer_note="ManifestBank™ is a wealth visualization and reflection platform. It is not a financial institution.",
    )

    return _send_email(to_email, "Welcome to ManifestBank™ Signature ✨", html)


def send_trial_grant_email(to_email: str, username: str | None, trial_days: int) -> bool:
    display = username or to_email.split("@")[0]
    body_html = f"""
    <p style="margin:0 0 12px;">Thank you for being part of the ManifestBank™ community. This space exists because of early members like you who chose to build with intention.</p>
    <p style="margin:0 0 12px;">We’ve activated a complimentary <strong>{trial_days}-day free trial</strong> of ManifestBank™ Signature for your account.</p>
    {_info_card(f"<div><strong>No card required.</strong> No action needed. Your trial starts immediately.</div>")}
    <p style="margin:0 0 12px;">You now have full access to the Signature experience while you explore the platform more deeply.</p>
    <p style="margin:0;">With appreciation and momentum,<br/>The ManifestBank™ Team</p>
    """
    html = _email_shell(
        eyebrow="Signature Access",
        heading="Your Signature trial is live",
        body_html=body_html,
        footer_note=f"ManifestBank™ is a mindset and visualization platform. It is not a financial institution. Recipient: {display}",
    )

    return _send_email(to_email, f"ManifestBank™ Signature — {trial_days} days on us", html)


def send_myline_message_email(
    to_email: str,
    sender_name: str,
    thread_id: int,
    preview: str,
) -> bool:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    thread_url = f"{base}/myline/{thread_id}"
    utility_html = f"""
    <div style="margin-top:18px;font-size:12px;line-height:1.6;color:#7a675d;">
      <div>If the button does not work, paste this link into your browser:</div>
      <div style="margin-top:6px;word-break:break-all;color:#6f4a3a;">{escape(thread_url)}</div>
    </div>
    """
    html = _email_shell(
        eyebrow="My Line",
        heading="New My Line message",
        body_html=f"""
        <p style="margin:0 0 12px;"><strong>{escape(sender_name)}</strong> sent you a new message.</p>
        {_info_card(escape(preview))}
        """,
        cta_html=_button(thread_url, "Open My Line"),
        utility_html=utility_html,
    )
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
    utility_html = f"""
    <div style="margin-top:18px;font-size:12px;line-height:1.6;color:#7a675d;">
      <div>If the button does not work, paste this link into your browser:</div>
      <div style="margin-top:6px;word-break:break-all;color:#6f4a3a;">{escape(post_url)}</div>
    </div>
    """
    html = _email_shell(
        eyebrow="The Ether™",
        heading="New comment on your post",
        body_html=f"""
        <p style="margin:0 0 12px;"><strong>{escape(commenter_name)}</strong> commented on your post.</p>
        {_info_card(escape(preview))}
        """,
        cta_html=_button(post_url, "View comment"),
        utility_html=utility_html,
    )
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
    utility_html = f"""
    <div style="margin-top:18px;font-size:12px;line-height:1.6;color:#7a675d;">
      <div>If the button does not work, paste this link into your browser:</div>
      <div style="margin-top:6px;word-break:break-all;color:#6f4a3a;">{escape(link)}</div>
    </div>
    """
    html = _email_shell(
        eyebrow="Account Update",
        heading="Your account was updated",
        body_html=f"""
        <p style="margin:0 0 12px;">A {escape(entry_type)} was {escape(verb)} to <strong>{escape(account_name)}</strong>.</p>
        {_info_card(f"Amount: <strong>{escape(amount)}</strong>")}
        """,
        cta_html=_button(link, "View details"),
        utility_html=utility_html,
    )
    return _send_email(to_email, "ManifestBank™ — Account update", html)


def send_signature_account_fix_email(
    to_email: str,
    contact_line_html: str,
) -> bool:
    html = _email_shell(
        eyebrow="Platform Update",
        heading="Issue resolved for Signature Members",
        body_html=f"""
        <p style="margin:0 0 12px;">Thank you for being a valued part of the ManifestBank™ community.</p>
        <p style="margin:0 0 12px;">We recently identified an issue affecting the creation of multiple accounts in some dashboards. That issue has now been fully resolved.</p>
        {_info_card("As a <strong>ManifestBank™ Signature Member</strong>, you can create <strong>unlimited accounts</strong> within your dashboard.")}
        <p style="margin:0 0 12px;">Your continued support means a great deal to us, and we are grateful to have you building this experience alongside us.</p>
        <p style="margin:0 0 12px;">{contact_line_html}</p>
        <p style="margin:0;">Warm regards,<br/>The ManifestBank™ Team</p>
        """,
    )
    subject = "ManifestBank™ Update — Issue Resolved & Thank You for Your Support"
    return _send_email(to_email, subject, html)
