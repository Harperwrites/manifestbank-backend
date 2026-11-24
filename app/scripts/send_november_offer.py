"""Dry-run by default. Recheck every recipient against local and live Stripe membership."""
import argparse
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


def run(*, send=False, limit=None):
    if not active():
        raise RuntimeError('Campaign is outside November 23–30, 2026 (America/Chicago). Nothing sent.')
    if send and (not settings.STRIPE_SECRET_KEY or not settings.STRIPE_PRICE_ANNUAL or not settings.STRIPE_NOVEMBER_COUPON_ID or not _configured_resend_accounts()):
        raise RuntimeError('Stripe annual price, November coupon, and Resend sender must be configured before sending.')
    if send and (not settings.FRONTEND_BASE_URL.startswith('https://') or not settings.BACKEND_BASE_URL.startswith('https://')):
        raise RuntimeError('Production HTTPS frontend and backend URLs are required before sending.')
    totals = dict(eligible=0, excluded=0, sent=0, failed=0, unknown=0, already_recorded=0)
    with SessionLocal() as db:
        seen = set()
        users = db.query(User).filter(User.email_verified.is_(True), User.is_active.is_(True)).order_by(User.id).all()
        for user in users:
            email = user.email.strip().lower()
            if email in seen:
                continue
            seen.add(email)
            if db.get(PromotionOptOut, email) or not eligible(db, user, live=True):
                totals['excluded'] += 1
                continue
            totals['eligible'] += 1
            if not send:
                continue
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
            status = send_november_offer_email(email, url, delivery.id)
            delivery.status = status
            delivery.updated_at = datetime.now(UTC)
            delivery.sent_at = datetime.now(UTC) if status == 'sent' else None
            db.commit()
            totals[status if status in totals else 'failed'] += 1
            if status in ('unknown', 'unconfigured'):
                # Do not exhaust provider quotas or risk duplicate delivery on fallback accounts.
                break
            if limit and totals['sent'] >= limit:
                break
    return totals


def main():
    parser = argparse.ArgumentParser(description='November $22.22 first-year annual offer; nonmembers only.')
    parser.add_argument('--send', action='store_true', help='Deliver to eligible registered users. Default is a count-only dry run.')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    print(run(send=args.send, limit=args.limit))

if __name__ == '__main__':
    main()
