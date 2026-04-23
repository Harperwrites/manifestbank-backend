from datetime import datetime, timezone

import pytest

from app.models.user import User
from app.routes import billing as billing_routes


def _signature_subscription(customer_id: str = "cus_signature") -> dict:
    return {
        "id": "sub_signature",
        "customer": customer_id,
        "status": "active",
        "current_period_end": 1_900_000_000,
        "trial_end": None,
        "cancel_at_period_end": False,
        "metadata": {"tier_name": "signature", "plan": "annual"},
        "items": {"data": [{"price": {"id": "price_annual"}}]},
    }


@pytest.mark.asyncio
async def test_paid_signature_checkout_sends_welcome_once(client, db, monkeypatch):
    user = User(
        email="signature@test.com",
        username="signatureuser",
        hashed_password="not-used",
        email_verified=True,
        stripe_customer_id="cus_signature",
    )
    db.add(user)
    db.commit()

    monkeypatch.setattr(billing_routes.settings, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(billing_routes.settings, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(billing_routes.settings, "STRIPE_PRICE_ANNUAL", "price_annual")

    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": "cus_signature",
                "subscription": "sub_signature",
                "payment_status": "paid",
                "amount_total": 9900,
                "metadata": {"tier_name": "signature", "plan": "annual"},
            }
        },
    }
    monkeypatch.setattr(billing_routes.stripe.Webhook, "construct_event", lambda *args: event)
    monkeypatch.setattr(billing_routes.stripe.Subscription, "retrieve", lambda subscription_id: _signature_subscription())

    welcome_emails: list[tuple[str, str | None]] = []
    admin_alerts: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        billing_routes,
        "send_signature_welcome_email",
        lambda to_email, username: welcome_emails.append((to_email, username)) or True,
    )
    monkeypatch.setattr(
        billing_routes,
        "send_subscription_alert_email",
        lambda to_email, user_email, username, plan: admin_alerts.append((user_email, plan)) or True,
    )

    first = await client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"})
    second = await client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert welcome_emails == [("signature@test.com", "signatureuser")]
    assert admin_alerts == [("signature@test.com", "annual"), ("signature@test.com", "annual")]

    refreshed = db.query(User).filter(User.email == "signature@test.com").first()
    assert refreshed is not None
    assert refreshed.is_premium is True
    assert refreshed.signature_welcome_email_sent_at is not None


@pytest.mark.asyncio
async def test_signature_invoice_paid_sends_welcome_for_initial_payment_only(client, db, monkeypatch):
    user = User(
        email="invoice-signature@test.com",
        username="invoiceuser",
        hashed_password="not-used",
        email_verified=True,
        stripe_customer_id="cus_invoice",
    )
    db.add(user)
    db.commit()

    monkeypatch.setattr(billing_routes.settings, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(billing_routes.settings, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(billing_routes.settings, "STRIPE_PRICE_ANNUAL", "price_annual")
    monkeypatch.setattr(
        billing_routes.stripe.Subscription,
        "retrieve",
        lambda subscription_id: _signature_subscription("cus_invoice"),
    )

    event = {
        "type": "invoice.paid",
        "data": {
            "object": {
                "customer": "cus_invoice",
                "subscription": "sub_signature",
                "billing_reason": "subscription_create",
                "amount_paid": 9900,
                "metadata": {},
            }
        },
    }
    monkeypatch.setattr(billing_routes.stripe.Webhook, "construct_event", lambda *args: event)

    welcome_emails: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        billing_routes,
        "send_signature_welcome_email",
        lambda to_email, username: welcome_emails.append((to_email, username)) or True,
    )

    initial = await client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"})
    event["data"]["object"]["billing_reason"] = "subscription_cycle"
    renewed = await client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"})

    assert initial.status_code == 200
    assert renewed.status_code == 200
    assert welcome_emails == [("invoice-signature@test.com", "invoiceuser")]

    refreshed = db.query(User).filter(User.email == "invoice-signature@test.com").first()
    assert refreshed is not None
    assert refreshed.signature_welcome_email_sent_at is not None


@pytest.mark.asyncio
async def test_signature_welcome_not_sent_for_trial_or_already_marked_user(client, db, monkeypatch):
    user = User(
        email="already-signature@test.com",
        username="alreadyuser",
        hashed_password="not-used",
        email_verified=True,
        stripe_customer_id="cus_already",
        signature_welcome_email_sent_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()

    monkeypatch.setattr(billing_routes.settings, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(billing_routes.settings, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(billing_routes.settings, "STRIPE_PRICE_ANNUAL", "price_annual")
    monkeypatch.setattr(
        billing_routes.stripe.Subscription,
        "retrieve",
        lambda subscription_id: _signature_subscription("cus_already"),
    )
    monkeypatch.setattr(
        billing_routes.stripe.Webhook,
        "construct_event",
        lambda *args: {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_already",
                    "subscription": "sub_signature",
                    "payment_status": "paid",
                    "amount_total": 0,
                    "metadata": {"tier_name": "signature", "plan": "annual"},
                }
            },
        },
    )

    welcome_emails: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        billing_routes,
        "send_signature_welcome_email",
        lambda to_email, username: welcome_emails.append((to_email, username)) or True,
    )
    monkeypatch.setattr(billing_routes, "send_subscription_alert_email", lambda *args, **kwargs: True)

    response = await client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"})

    assert response.status_code == 200
    assert welcome_emails == []
