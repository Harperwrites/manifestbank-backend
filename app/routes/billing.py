from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import stripe

from app.core.security import get_verified_user
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.services.email import send_signature_welcome_email, send_subscription_alert_email

router = APIRouter(prefix="/billing", tags=["billing"])


def _require_stripe_key() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    stripe.api_key = settings.STRIPE_SECRET_KEY


def _price_for_plan(plan: str | None) -> str:
    if plan == "monthly":
        if not settings.STRIPE_PRICE_MONTHLY:
            raise HTTPException(status_code=500, detail="Stripe monthly price not configured")
        return settings.STRIPE_PRICE_MONTHLY
    if plan == "annual":
        if not settings.STRIPE_PRICE_ANNUAL:
            raise HTTPException(status_code=500, detail="Stripe annual price not configured")
        return settings.STRIPE_PRICE_ANNUAL
    raise HTTPException(status_code=400, detail="Invalid plan. Use 'monthly' or 'annual'.")


def _subscription_price_id(subscription: dict) -> str | None:
    return (
        subscription.get("items", {})
        .get("data", [{}])[0]
        .get("price", {})
        .get("id")
    )


def _is_signature_subscription(subscription: dict | None, metadata: dict | None = None) -> bool:
    metadata = metadata or {}
    subscription_metadata = (subscription or {}).get("metadata") or {}
    tier = metadata.get("tier_name") or subscription_metadata.get("tier_name")
    if tier == "signature":
        return True
    price_id = _subscription_price_id(subscription or {})
    signature_prices = {settings.STRIPE_PRICE_MONTHLY, settings.STRIPE_PRICE_ANNUAL}
    return bool(price_id and price_id in signature_prices)


def _paid_amount_cents(data: dict) -> int:
    for key in ("amount_paid", "amount_total", "amount_due"):
        value = data.get(key)
        if isinstance(value, int):
            return value
    return 0


@router.post("/checkout-session")
def create_checkout_session(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_verified_user),
):
    _require_stripe_key()

    plan = payload.get("plan") if isinstance(payload, dict) else None
    price_id = payload.get("price_id") if isinstance(payload, dict) else None
    if not price_id:
        price_id = _price_for_plan(plan)

    if not user.stripe_customer_id:
        display_name = user.username or user.email
        customer = stripe.Customer.create(
            email=user.email,
            name=display_name,
            metadata={
                "user_id": str(user.id),
                "username": user.username or "",
                "app_name": "manifestbank",
            },
        )
        user.stripe_customer_id = customer.id
        db.add(user)
        db.commit()
        db.refresh(user)

    success_url = settings.STRIPE_SUCCESS_URL or f"{settings.FRONTEND_BASE_URL}/success"
    cancel_url = settings.STRIPE_CANCEL_URL or f"{settings.FRONTEND_BASE_URL}/cancel"

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=user.stripe_customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(user.id),
        metadata={
            "user_id": str(user.id),
            "username": user.username or "",
            "tier_name": "signature",
            "plan": plan or "",
            "app_name": "manifestbank",
        },
        subscription_data={
            "metadata": {
                "user_id": str(user.id),
                "username": user.username or "",
                "tier_name": "signature",
                "plan": plan or "",
                "app_name": "manifestbank",
            }
        },
    )

    return {"url": session.url}


@router.post("/portal-session")
def create_portal_session(
    db: Session = Depends(get_db),
    user: User = Depends(get_verified_user),
):
    _require_stripe_key()
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer found")
    return_url = settings.STRIPE_PORTAL_RETURN_URL or f"{settings.FRONTEND_BASE_URL}/dashboard"
    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=return_url,
    )
    return {"url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    if not settings.STRIPE_WEBHOOK_SECRET or not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe webhook not configured")
    stripe.api_key = settings.STRIPE_SECRET_KEY

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})

    def update_user_from_subscription(subscription: dict) -> User | None:
        customer_id = subscription.get("customer")
        if not customer_id:
            return None
        user_obj = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if not user_obj:
            return None
        user_obj.stripe_subscription_id = subscription.get("id")
        user_obj.stripe_status = subscription.get("status")
        user_obj.stripe_price_id = _subscription_price_id(subscription)
        current_period_end = subscription.get("current_period_end")
        trial_end = subscription.get("trial_end")
        user_obj.stripe_current_period_end = (
            datetime.fromtimestamp(current_period_end, tz=timezone.utc) if current_period_end else None
        )
        user_obj.stripe_trial_end = (
            datetime.fromtimestamp(trial_end, tz=timezone.utc) if trial_end else None
        )
        user_obj.stripe_cancel_at_period_end = bool(subscription.get("cancel_at_period_end"))
        user_obj.is_premium = subscription.get("status") in {"active", "trialing"}
        db.add(user_obj)
        db.commit()
        db.refresh(user_obj)
        return user_obj

    def send_signature_welcome_once(user_obj: User | None, subscription: dict, metadata: dict | None = None) -> None:
        if not user_obj or user_obj.signature_welcome_email_sent_at:
            return
        if not _is_signature_subscription(subscription, metadata):
            return
        if send_signature_welcome_email(user_obj.email, user_obj.username):
            user_obj.signature_welcome_email_sent_at = datetime.now(timezone.utc)
            db.add(user_obj)
            db.commit()

    if event_type == "checkout.session.completed":
        subscription_id = data.get("subscription")
        customer_id = data.get("customer")
        payment_status = data.get("payment_status")
        metadata = data.get("metadata") or {}
        plan = metadata.get("plan")
        if subscription_id and customer_id:
            subscription = stripe.Subscription.retrieve(subscription_id)
            user_obj = update_user_from_subscription(subscription)
            if payment_status == "paid" and _paid_amount_cents(data) > 0:
                send_signature_welcome_once(user_obj, subscription, metadata)
                if user_obj:
                    to_email = settings.SUBSCRIPTION_ALERT_EMAIL or "blharper95@gmail.com"
                    send_subscription_alert_email(to_email, user_obj.email, user_obj.username, plan)
    elif event_type in {"customer.subscription.updated", "customer.subscription.deleted"}:
        update_user_from_subscription(data)
    elif event_type in {"invoice.paid", "invoice.payment_failed"}:
        subscription_id = data.get("subscription")
        if subscription_id:
            subscription = stripe.Subscription.retrieve(subscription_id)
            user_obj = update_user_from_subscription(subscription)
            if (
                event_type == "invoice.paid"
                and data.get("billing_reason") == "subscription_create"
                and _paid_amount_cents(data) > 0
            ):
                send_signature_welcome_once(user_obj, subscription, data.get("metadata") or {})

    return {"status": "ok"}
