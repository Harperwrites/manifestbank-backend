from __future__ import annotations

import argparse
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.user import User
from app.services.email import send_signature_account_fix_email


CONTACT_LINE_HTML = (
    'If you experience anything that seems out of place or have suggestions that could make '
    'ManifestBank™ even better, we always welcome your feedback. Reach out to us through '
    '"My Line" on ManifestBank™ or fill out a contact form at '
    '<a href="https://manifestbank.app/contact" style="color:#b67967; text-decoration: underline;">'
    'https://manifestbank.app/contact</a>'
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the Signature account fix email.")
    parser.add_argument("--send", action="store_true", help="Actually send emails (default: dry-run)")
    parser.add_argument(
        "--include-unverified",
        action="store_true",
        help="Include Signature members who have not verified email",
    )
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        query = db.query(User).filter(User.is_premium.is_(True))
        if not args.include_unverified:
            query = query.filter(User.email_verified.is_(True))
        users = query.order_by(User.id.asc()).all()
        print(f"Signature members matched: {len(users)}")

        if not args.send:
            for u in users[:20]:
                print(f"- {u.id} | {u.email} | verified={u.email_verified}")
            if len(users) > 20:
                print(f"... and {len(users) - 20} more")
            print("Dry-run complete. Re-run with --send to deliver.")
            return

        sent = 0
        failed = 0
        for u in users:
            ok = send_signature_account_fix_email(u.email, CONTACT_LINE_HTML)
            if ok:
                sent += 1
            else:
                failed += 1
        print(f"Done. Sent: {sent}, Failed: {failed}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
