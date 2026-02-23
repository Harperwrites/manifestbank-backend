from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
import stripe

from app.auth.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.services.email import send_subscription_alert_email

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


@router.post("/checkout-session")
def create_checkout_session(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
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

    def update_user_from_subscription(subscription: dict):
        customer_id = subscription.get("customer")
        if not customer_id:
            return
        user_obj = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if not user_obj:
            return
        user_obj.stripe_subscription_id = subscription.get("id")
        user_obj.stripe_status = subscription.get("status")
        user_obj.stripe_price_id = (
            subscription.get("items", {})
            .get("data", [{}])[0]
            .get("price", {})
            .get("id")
        )
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

    if event_type == "checkout.session.completed":
        subscription_id = data.get("subscription")
        customer_id = data.get("customer")
        payment_status = data.get("payment_status")
        plan = (data.get("metadata") or {}).get("plan")
        if subscription_id and customer_id:
            subscription = stripe.Subscription.retrieve(subscription_id)
            update_user_from_subscription(subscription)
            if payment_status == "paid":
                user_obj = db.query(User).filter(User.stripe_customer_id == customer_id).first()
                if user_obj:
                    to_email = settings.SUBSCRIPTION_ALERT_EMAIL or "blharper95@gmail.com"
                    send_subscription_alert_email(to_email, user_obj.email, user_obj.username, plan)
    elif event_type in {"customer.subscription.updated", "customer.subscription.deleted"}:
        update_user_from_subscription(data)
    elif event_type in {"invoice.paid", "invoice.payment_failed"}:
        subscription_id = data.get("subscription")
        if subscription_id:
            subscription = stripe.Subscription.retrieve(subscription_id)
            update_user_from_subscription(subscription)

    return {"status": "ok"}
