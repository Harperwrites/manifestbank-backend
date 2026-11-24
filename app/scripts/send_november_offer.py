"""Dry-run by default. Recheck every recipient against local and live Stripe membership."""
import argparse
import json
import time
from pathlib import Path
from datetime import datetime, UTC
from urllib.parse import urlencode
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.models.promotion import PromotionEmail, PromotionOptOut
from app.services.november_offer import CAMPAIGN, active, eligible, unsubscribe_token, checkout_discount
from app.services.email import send_november_offer_email, _configured_resend_accounts


def run(*, send=False, limit=None, user_ids=None, progress=None):
    if limit is not None and limit < 1:
        raise ValueError("Recipient limit must be positive.")
    if not active():
        raise RuntimeError('Campaign is outside November 23–30, 2026 (America/Chicago). Nothing sent.')
    if send and (not settings.STRIPE_SECRET_KEY or not settings.STRIPE_PRICE_ANNUAL or not settings.STRIPE_NOVEMBER_COUPON_ID or not _configured_resend_accounts()):
        raise RuntimeError('Stripe annual price, November coupon, and Resend sender must be configured before sending.')
    if send and (not settings.FRONTEND_BASE_URL.startswith('https://') or not settings.BACKEND_BASE_URL.startswith('https://')):
        raise RuntimeError('Production HTTPS frontend and backend URLs are required before sending.')
    totals = dict(eligible=0, excluded=0, sent=0, failed=0, unknown=0, already_recorded=0, attempted=0)
    with SessionLocal() as db:
        seen = set()
        query = db.query(User).filter(User.email_verified.is_(True), User.is_active.is_(True))
        if user_ids is not None:
            query = query.filter(User.id.in_(user_ids))
        users = query.order_by(User.id).all()
        selected = []
        for user in users:
            email = user.email.strip().lower()
            if email in seen:
                continue
            seen.add(email)
            if db.get(PromotionOptOut, email) or not eligible(db, user, live=True):
                totals['excluded'] += 1
                continue
            selected.append(user)
            if limit and len(selected) >= limit:
                break
        totals['eligible'] = len(selected)
        totals['selected_user_ids'] = [user.id for user in selected]
        if progress:
            progress(totals.copy())
        if not send:
            return totals
        # Freeze the selected group before sending. Failures never pull in later accounts.
        for user in selected:
            email = user.email.strip().lower()
            # Re-read membership immediately before dispatch, including duplicate-email accounts.
            db.refresh(user)
            if not eligible(db, user, live=True) or db.get(PromotionOptOut, email):
                totals['excluded'] += 1
                continue
            checkout_discount(db, user)  # verify the real $72 annual price and once-only $49.78 coupon
            if db.query(PromotionEmail).filter_by(campaign=CAMPAIGN, email=email).first():
                totals['already_recorded'] += 1
                continue
            delivery = PromotionEmail(campaign=CAMPAIGN, email=email, status='pending')
            db.add(delivery)
            try:
                db.commit()  # unique key claims this recipient across processes
            except IntegrityError:
                db.rollback()
                totals['already_recorded'] += 1
                continue
            url = settings.BACKEND_BASE_URL.rstrip('/') + '/promotions/unsubscribe?' + urlencode({'token':unsubscribe_token(email)})
            totals['attempted'] += 1
            status = send_november_offer_email(email, url, delivery.id)
            delivery.status = status
            delivery.updated_at = datetime.now(UTC)
            delivery.sent_at = datetime.now(UTC) if status == 'sent' else None
            db.commit()
            totals[status if status in totals else 'failed'] += 1
            if progress:
                progress(totals.copy())
            if status in ('unknown', 'unconfigured'):
                # Do not exhaust provider quotas or risk duplicate delivery on fallback accounts.
                break
            time.sleep(0.65)  # Pace requests without changing provider/account limits.
    return totals


def main():
    parser = argparse.ArgumentParser(description='November $22.22 first-year annual offer; nonmembers only.')
    parser.add_argument('--send', action='store_true', help='Deliver to eligible registered users. Default is a count-only dry run.')
    parser.add_argument('--limit', type=int, default=75, help='Oldest eligible unique accounts to select; defaults to 75.')
    parser.add_argument('--recipient-file', help='A previously reviewed dry-run JSON report containing selected_user_ids.')
    parser.add_argument('--report-file', help='Write counts and selected user IDs, without email addresses, after each send.')
    args = parser.parse_args()
    ids = None
    if args.recipient_file:
        ids = json.loads(Path(args.recipient_file).read_text())["selected_user_ids"]
        if not isinstance(ids, list) or not ids or any(not isinstance(value, int) for value in ids):
            raise RuntimeError("Recipient file must contain a nonempty list of account IDs.")
        if len(ids) > args.limit:
            raise RuntimeError("Recipient snapshot exceeds the authorized limit.")
    def report(totals):
        if args.report_file:
            path = Path(args.report_file)
            temporary = path.with_suffix(path.suffix + '.tmp')
            temporary.write_text(json.dumps(totals, indent=2))
            temporary.replace(path)
        print(json.dumps(totals), flush=True)
    result = run(send=args.send, limit=args.limit, user_ids=ids, progress=report)
    report(result)

if __name__ == '__main__':
    main()
