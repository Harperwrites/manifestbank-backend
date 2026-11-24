"""Single source of truth for the November 2026 annual offer."""
from datetime import datetime, UTC
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import func, update
from sqlalchemy.orm import Session
import stripe
from jose import jwt, JWTError
from app.core.config import settings
from app.models.user import User
from app.models.promotion import PromotionLogin, PromotionOptOut

CAMPAIGN = "november1111-2026"  # Stable identity; retain delivery deduplication after price revision.
START = datetime(2026, 11, 23, tzinfo=ZoneInfo("America/Chicago"))
END = datetime(2026, 12, 1, tzinfo=ZoneInfo("America/Chicago"))  # exclusive
PROMO_CODE = "1111"
REGULAR_CENTS = 7200
FIRST_YEAR_CENTS = 2222
DISCOUNT_CENTS = REGULAR_CENTS - FIRST_YEAR_CENTS
END_LABEL = "November 30, 2026 at 11:59 p.m. Central Time"
RENEWAL_COPY = "$22.22 for your first year; then $72/year, renewing automatically unless you cancel."


def active(now=None):
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return START <= current < END


def local_nonmember(user):
    # Fail closed for incomplete/stale membership flags and all recorded subscribers.
    return bool(user and user.is_active and user.role != "admin" and not user.is_premium
                and not user.stripe_subscription_id and not user.stripe_price_id
                and (user.stripe_status or "").lower() not in {"active", "trialing", "past_due", "unpaid", "incomplete", "paused"})


def eligible(db: Session, user, *, live=False):
    if not local_nonmember(user):
        return False
    same_email = db.query(User).filter(func.lower(User.email) == user.email.strip().lower()).all()
    if any(not local_nonmember(other) for other in same_email):
        return False
    if live:
        if not settings.STRIPE_SECRET_KEY:
            # Without Stripe access a known customer cannot safely be called a nonmember.
            return not any(other.stripe_customer_id for other in same_email)
        stripe.api_key = settings.STRIPE_SECRET_KEY
        # Find customers by email as well, catching missing local customer/subscription IDs.
        customers = {other.stripe_customer_id for other in same_email if other.stripe_customer_id}
        for address in {user.email.strip(), user.email.strip().lower()}:
            for customer in stripe.Customer.list(email=address, limit=100).auto_paging_iter():
                customers.add(customer.id)
        for customer_id in customers:
            for subscription in stripe.Subscription.list(customer=customer_id, status="all", limit=100).auto_paging_iter():
                if subscription.get("status") not in {"canceled", "incomplete_expired"}:
                    return False
    return True


def record_signup(db, user_id):
    row = db.get(PromotionLogin, user_id)
    if not row:
        db.add(PromotionLogin(user_id=user_id, is_new_signup=True, login_count=0))
        db.flush()


def record_login(db, user_id):
    # Lock the existing user before creating/updating a counter (works across workers).
    db.query(User).filter_by(id=user_id).with_for_update().first()
    row = db.get(PromotionLogin, user_id)
    if row is None:
        row = PromotionLogin(user_id=user_id, is_new_signup=False, login_count=0)
        db.add(row)
        db.flush()
    db.execute(update(PromotionLogin).where(PromotionLogin.user_id == user_id).values(login_count=PromotionLogin.login_count + 1, last_login_at=datetime.now(UTC)))
    db.commit()


def offer_status(db, user):
    state = db.get(PromotionLogin, user.id)
    allowed = active() and eligible(db, user, live=True)
    second_login = not state or not state.is_new_signup or state.login_count >= 2
    return {"campaign": CAMPAIGN, "active": active(), "eligible": allowed,
            "show_alert": allowed and second_login,
            "login_number": state.login_count if state else 0,
            "login_at": state.last_login_at.isoformat() if state and state.last_login_at else None,
            "delay_ms": 4000, "first_year_cents": FIRST_YEAR_CENTS, "promo_code": PROMO_CODE,
            "regular_annual_cents": REGULAR_CENTS, "ends_at": END.isoformat(),
            "end_label": END_LABEL, "renewal_copy": RENEWAL_COPY,
            "checkout_ready": bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_PRICE_ANNUAL and settings.STRIPE_NOVEMBER_COUPON_ID)}


def checkout_discount(db, user):
    if not active():
        raise HTTPException(410, "This November offer has ended.")
    if not eligible(db, user, live=True):
        raise HTTPException(403, "This offer is only for nonmembers. Existing subscribers are excluded.")
    if not settings.STRIPE_NOVEMBER_COUPON_ID or not settings.STRIPE_PRICE_ANNUAL:
        raise HTTPException(503, "The November offer checkout is not configured yet. Please try again later.")
    price = stripe.Price.retrieve(settings.STRIPE_PRICE_ANNUAL)
    recurring = price.get("recurring") or {}
    if not price.get("active") or price.get("currency") != "usd" or price.get("unit_amount") != REGULAR_CENTS or recurring.get("interval") != "year" or recurring.get("interval_count", 1) != 1:
        raise HTTPException(503, "The annual offer price configuration needs review.")
    coupon = stripe.Coupon.retrieve(settings.STRIPE_NOVEMBER_COUPON_ID)
    products = (coupon.get("applies_to") or {}).get("products")
    if not coupon.get("valid") or coupon.get("duration") != "once" or coupon.get("amount_off") != DISCOUNT_CENTS or coupon.get("currency") != "usd" or coupon.get("percent_off") is not None or (products and price.get("product") not in products):
        raise HTTPException(503, "The first-year offer discount configuration needs review.")
    # Apply the customer-facing code itself so Stripe records redemptions of 1111.
    codes = stripe.PromotionCode.list(code=PROMO_CODE, active=True, limit=100)
    for code in codes.auto_paging_iter():
        linked = code.get("coupon") or (code.get("promotion") or {}).get("coupon")
        linked_id = linked.get("id") if isinstance(linked, dict) else linked
        restrictions = code.get("restrictions") or {}
        expiration = code.get("expires_at") or coupon.get("redeem_by")
        if (code.get("code") == PROMO_CODE and code.get("active")
                and linked_id == settings.STRIPE_NOVEMBER_COUPON_ID
                and not code.get("customer") and not code.get("customer_account")
                and restrictions.get("minimum_amount") == REGULAR_CENTS
                and restrictions.get("minimum_amount_currency") == "usd"
                and expiration and datetime.now(UTC).timestamp() < expiration <= END.timestamp()):
            return {"promotion_code": code["id"]}
    raise HTTPException(503, "The November promotion code configuration needs review.")


def unsubscribe_token(email):
    return jwt.encode({"purpose":"marketing-opt-out", "email":email.strip().lower()}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def opt_out(db, token):
    try:
        data = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if data.get("purpose") != "marketing-opt-out" or not data.get("email"):
            raise ValueError()
    except (JWTError, ValueError):
        raise HTTPException(400, "Invalid unsubscribe link")
    email = data["email"]
    if not db.get(PromotionOptOut, email):
        db.add(PromotionOptOut(email=email))
        db.commit()
