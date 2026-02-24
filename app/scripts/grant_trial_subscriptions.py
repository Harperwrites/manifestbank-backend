from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta, timezone

import stripe

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.services.email import send_trial_grant_email, send_subscription_alert_email


TRIAL_DAYS = 92


def main() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise SystemExit("Missing STRIPE_SECRET_KEY")
    if not settings.STRIPE_PRICE_ANNUAL:
        raise SystemExit("Missing STRIPE_PRICE_ANNUAL")

    stripe.api_key = settings.STRIPE_SECRET_KEY
    trial_end = int((datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)).timestamp())
    dry_run = os.getenv("MB_TRIAL_DRY_RUN", "1") != "0"

    db = SessionLocal()
    try:
        users = (
            db.query(User)
            .filter(User.is_active.is_(True))
            .filter(User.role != "admin")
            .all()
        )
        eligible = [u for u in users if not (u.is_premium or u.stripe_subscription_id)]
        csv_path = os.path.abspath("eligible_trial_users.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "email", "username"])
            for u in eligible:
                writer.writerow([u.id, u.email, u.username or ""])

        print("Eligible users:")
        for u in eligible:
            print(f"- {u.id} | {u.email} | {u.username or ''}")
        print(f"Total eligible: {len(eligible)}")
        print(f"CSV exported: {csv_path}")
        if dry_run:
            print("Dry run only. Set MB_TRIAL_DRY_RUN=0 to execute.")
            return

        created = 0
        skipped = 0
        for user in users:
            if user.is_premium or user.stripe_subscription_id:
                skipped += 1
                continue

            if not user.stripe_customer_id:
                customer = stripe.Customer.create(
                    email=user.email,
                    name=user.username or user.email,
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

            subscription = stripe.Subscription.create(
                customer=user.stripe_customer_id,
                items=[{"price": settings.STRIPE_PRICE_ANNUAL}],
                trial_end=trial_end,
                metadata={
                    "user_id": str(user.id),
                    "username": user.username or "",
                    "tier_name": "signature",
                    "plan": "annual",
                    "app_name": "manifestbank",
                },
                trial_settings={
                    "end_behavior": {"missing_payment_method": "cancel"},
                },
            )

            user.stripe_subscription_id = subscription.id
            user.stripe_price_id = settings.STRIPE_PRICE_ANNUAL
            user.stripe_status = subscription.status
            user.stripe_cancel_at_period_end = bool(subscription.get("cancel_at_period_end"))
            user.stripe_current_period_end = datetime.fromtimestamp(
                subscription.current_period_end, tz=timezone.utc
            )
            user.stripe_trial_end = datetime.fromtimestamp(trial_end, tz=timezone.utc)
            user.is_premium = True
            db.add(user)
            db.commit()
            created += 1
            send_trial_grant_email(user.email, user.username, TRIAL_DAYS)

        print(f"Done. Created: {created}, Skipped: {skipped}")
        admin_email = settings.SUBSCRIPTION_ALERT_EMAIL or "blharper95@gmail.com"
        send_subscription_alert_email(
            admin_email,
            user_email=admin_email,
            username="ManifestBank Admin",
            plan=f"Trial grants complete: created {created}, skipped {skipped}",
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
