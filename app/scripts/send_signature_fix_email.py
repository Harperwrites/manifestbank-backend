from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, UTC
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


def _load_only_emails(path: str) -> set[str]:
    emails: set[str] = set()
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            email = line.strip()
            if email:
                emails.add(email.lower())
    return emails


def _load_failed_from_csv(path: str) -> set[str]:
    emails: set[str] = set()
    with open(path, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") == "failed":
                email = (row.get("email") or "").strip()
                if email:
                    emails.add(email.lower())
    return emails


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the Signature account fix email.")
    parser.add_argument("--send", action="store_true", help="Actually send emails (default: dry-run)")
    parser.add_argument(
        "--include-unverified",
        action="store_true",
        help="Include Signature members who have not verified email",
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        default=0.6,
        help="Seconds to wait between sends (default: 0.6)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=6,
        help="Max retries per email on failure (default: 6)",
    )
    parser.add_argument(
        "--only-emails",
        type=str,
        default="",
        help="Path to a newline-separated email list to send only to those addresses",
    )
    parser.add_argument(
        "--resume-from",
        type=str,
        default="",
        help="Path to a CSV output from a prior run to resend only failures",
    )
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        query = db.query(User).filter(User.is_premium.is_(True))
        if not args.include_unverified:
            query = query.filter(User.email_verified.is_(True))
        users = query.order_by(User.id.asc()).all()

        if args.only_emails:
            only = _load_only_emails(args.only_emails)
            users = [u for u in users if u.email.lower() in only]

        if args.resume_from:
            failed = _load_failed_from_csv(args.resume_from)
            users = [u for u in users if u.email.lower() in failed]

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
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        out_path = f"/tmp/signature_email_results_{timestamp}.csv"
        with open(out_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["email", "user_id", "status", "attempts"],
            )
            writer.writeheader()

            for idx, u in enumerate(users, start=1):
                attempts = 0
                ok = False
                while attempts < max(1, args.max_retries):
                    attempts += 1
                    ok = send_signature_account_fix_email(u.email, CONTACT_LINE_HTML)
                    if ok:
                        break
                    time.sleep(args.min_delay * attempts)

                writer.writerow(
                    {
                        "email": u.email,
                        "user_id": u.id,
                        "status": "sent" if ok else "failed",
                        "attempts": attempts,
                    }
                )

                if ok:
                    sent += 1
                else:
                    failed += 1

                if idx < len(users):
                    time.sleep(args.min_delay)

        print(f"Done. Sent: {sent}, Failed: {failed}")
        print(f"Results saved: {out_path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
