from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.services.email import (
    render_annual_membership_reply_email,
    send_annual_membership_reply_email,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview or send the annual membership support reply email."
    )
    parser.add_argument("--email", required=True, help="Recipient email address")
    parser.add_argument(
        "--recipient-name",
        default="Annie",
        help="Recipient first name used in the greeting",
    )
    parser.add_argument(
        "--reply-to",
        default=settings.CONTACT_FORWARD_EMAIL or settings.SIGNUP_ALERT_EMAIL or "",
        help="Reply-to email address",
    )
    parser.add_argument(
        "--preview-path",
        default="tmp/email-previews/annual-membership-reply.html",
        help="Where to write the HTML preview in dry-run mode",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send the email instead of only writing a preview",
    )
    parser.add_argument(
        "--require-db-user",
        action="store_true",
        help="Verify the email exists in the current database before sending",
    )
    args = parser.parse_args()

    subject, html = render_annual_membership_reply_email(
        recipient_name=args.recipient_name,
    )

    if not args.send:
        preview_path = Path(args.preview_path)
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_text(html, encoding="utf-8")
        print(f"Preview subject: {subject}")
        print(f"Preview written to: {preview_path.resolve()}")
        if args.reply_to:
            print(f"Reply-To: {args.reply_to}")
        print("Dry-run only. Re-run with --send to deliver.")
        return

    if args.require_db_user:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email.ilike(args.email)).first()
            if user is None:
                print(f"User not found in current database: {args.email}")
                raise SystemExit(1)
            print(
                "Matched DB user:"
                f" id={user.id}"
                f" email={user.email}"
                f" username={user.username or ''}"
                f" premium={user.is_premium}"
                f" verified={user.email_verified}"
            )
        finally:
            db.close()

    ok = send_annual_membership_reply_email(
        args.email,
        recipient_name=args.recipient_name,
        reply_to=args.reply_to or None,
    )
    print("Sent." if ok else "Failed.")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
