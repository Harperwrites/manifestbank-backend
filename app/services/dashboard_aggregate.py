from __future__ import annotations

from datetime import datetime, UTC
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.ledger import LedgerEntry
from app.crud.crud_ledger import get_account_balance, get_latest_posted_balance_timestamp
from app.services.tier import build_preview_access
from app.services.fx import convert_amount_with_rate_snapshot, get_rates_snapshot


BASE_CURRENCY = "USD"
EPSILON = Decimal("0.01")


def _sign(value: Decimal) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _pending_total(
    db: Session,
    accounts: list[Account],
    display_currency: str,
    errors: list[str],
    rates: dict[str, Decimal],
) -> Decimal:
    account_ids = [acct.id for acct in accounts]
    if not account_ids:
        return Decimal("0")
    pending = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.account_id.in_(account_ids), LedgerEntry.status == "pending")
        .all()
    )
    total = Decimal("0")
    for entry in pending:
        amount = Decimal(str(entry.amount or 0))
        converted, missing, rate = convert_amount_with_rate_snapshot(
            amount, entry.currency or BASE_CURRENCY, display_currency, rates
        )
        if rate <= 0:
            errors.append("Invalid FX rate in pending transfer conversion.")
        if missing:
            errors.append(f"Missing FX rates for pending: {', '.join(sorted(set(missing)))}")
        total += converted
    return total


def _pending_total_base(
    db: Session,
    accounts: list[Account],
    errors: list[str],
    rates: dict[str, Decimal],
) -> Decimal:
    account_ids = [acct.id for acct in accounts]
    if not account_ids:
        return Decimal("0")
    pending = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.account_id.in_(account_ids), LedgerEntry.status == "pending")
        .all()
    )
    total = Decimal("0")
    for entry in pending:
        amount = Decimal(str(entry.amount or 0))
        converted, missing, rate = convert_amount_with_rate_snapshot(
            amount, entry.currency or BASE_CURRENCY, BASE_CURRENCY, rates
        )
        if rate <= 0:
            errors.append("Invalid FX rate in pending transfer base conversion.")
        if missing:
            errors.append(f"Missing FX rates for pending base: {', '.join(sorted(set(missing)))}")
        total += converted
    return total


def build_dashboard_aggregate(
    db: Session,
    user,
    display_currency: str,
    previous_base_total: Decimal | None = None,
) -> dict:
    display_cur = (display_currency or BASE_CURRENCY).upper()
    base_cur = BASE_CURRENCY
    fx_timestamp = datetime.now(UTC).isoformat()
    user_id = user.id

    rates = get_rates_snapshot()
    accounts = (
        db.query(Account)
        .filter(Account.owner_user_id == user_id)
        .order_by(Account.id.asc())
        .all()
    )

    errors: list[str] = []
    missing_rates: set[str] = set()
    items: list[dict] = []

    aggregate_display = Decimal("0")
    aggregate_base = Decimal("0")
    selected_subtotal = Decimal("0")
    operating_base = Decimal("0")
    alts_base = Decimal("0")

    for acct in accounts:
        native_currency = (acct.currency or base_cur).upper()
        native_balance = get_account_balance(db, acct.id, currency=native_currency)
        latest_posted_at = get_latest_posted_balance_timestamp(db, acct.id)
        preview = build_preview_access(user=user, created_at=latest_posted_at)
        visible_to_user = bool(preview.get("visible_to_user", True))
        preview_balance = native_balance if visible_to_user else Decimal("0")
        if native_currency == display_cur:
            selected_subtotal += preview_balance

        converted_display, missing_display, rate_display = convert_amount_with_rate_snapshot(
            preview_balance, native_currency, display_cur, rates
        )
        converted_base, missing_base, rate_base = convert_amount_with_rate_snapshot(
            preview_balance, native_currency, base_cur, rates
        )
        if rate_display <= 0 or rate_base <= 0:
            errors.append(f"Invalid FX rate for {native_currency}.")
        missing_rates.update(missing_display)
        missing_rates.update(missing_base)

        aggregate_display += converted_display
        aggregate_base += converted_base
        if acct.account_type in {"personal", "operating", "family_office", "wealth_builder"}:
            operating_base += converted_base
        if acct.account_type in {"trust", "entity", "foundation", "estate", "holding", "investment"}:
            alts_base += converted_base
        items.append(
            {
                "account_id": acct.id,
                "account_name": acct.name,
                "native_balance": str(preview_balance),
                "stored_native_balance": str(native_balance),
                "native_currency": native_currency,
                "display_currency": display_cur,
                "conversion_rate": str(rate_display),
                "conversion_rate_base": str(rate_base),
                "converted_amount": str(converted_display),
                "converted_base_amount": str(converted_base),
                "fx_timestamp": fx_timestamp,
                "visible_to_user": visible_to_user,
                "preview_expires_at": preview.get("preview_expires_at"),
                "is_preview_expired": bool(preview.get("is_preview_expired")),
            }
        )

    if missing_rates:
        errors.append(f"Missing FX rates for: {', '.join(sorted(missing_rates))}")

    if aggregate_display + EPSILON < selected_subtotal:
        errors.append(
            "Aggregate total is below subtotal of accounts already in the selected currency."
        )

    max_base = max((Decimal(item["converted_base_amount"]) for item in items), default=Decimal("0"))
    if aggregate_base + EPSILON < max_base:
        errors.append("Aggregate base total is below a single account base value.")

    converted_from_base, _, _ = convert_amount_with_rate_snapshot(
        aggregate_base, base_cur, display_cur, rates
    )
    tolerance = max(EPSILON * max(1, len(accounts)), Decimal("1.00"))
    if (converted_from_base - aggregate_display).copy_abs() > tolerance:
        errors.append("Aggregate total does not match sum of converted account balances.")
    # Use base-converted aggregate for display to avoid per-account rounding drift.
    aggregate_display = converted_from_base

    delta_base: Decimal | None = None
    delta_display: Decimal | None = None
    if previous_base_total is not None:
        delta_base = aggregate_base - previous_base_total
        delta_display, _, _ = convert_amount_with_rate_snapshot(delta_base, base_cur, display_cur, rates)
        if _sign(delta_base) != _sign(delta_display):
            errors.append("Momentum direction flips across display currency.")
        for code in {display_cur, "USD", "GBP", "CAD", "JPY"}:
            converted_delta, _, _ = convert_amount_with_rate_snapshot(delta_base, base_cur, code, rates)
            if _sign(delta_base) != _sign(converted_delta):
                errors.append("Momentum direction flips across display currency set.")
                break

    pending_display = _pending_total(db, accounts, display_cur, errors, rates)
    pending_base = _pending_total_base(db, accounts, errors, rates)

    return {
        "display_currency": display_cur,
        "base_currency": base_cur,
        "aggregate_total": str(aggregate_display.quantize(Decimal("0.01"))),
        "aggregate_total_base": str(aggregate_base.quantize(Decimal("0.01"))),
        "operating_cash_base": str(operating_base.quantize(Decimal("0.01"))),
        "alts_base": str(alts_base.quantize(Decimal("0.01"))),
        "pending_transfers_base": str(pending_base.quantize(Decimal("0.01"))),
        "operating_cash": str(
            convert_amount_with_rate_snapshot(operating_base, base_cur, display_cur, rates)[0]
        ),
        "alts": str(convert_amount_with_rate_snapshot(alts_base, base_cur, display_cur, rates)[0]),
        "pending_transfers": str(pending_display.quantize(Decimal("0.01"))),
        "selected_currency_subtotal": str(selected_subtotal.quantize(Decimal("0.01"))),
        "momentum": {
            "delta_base": str(delta_base.quantize(Decimal("0.01"))) if delta_base is not None else None,
            "delta_display": str(delta_display.quantize(Decimal("0.01"))) if delta_display is not None else None,
        },
        "fx_rates": {code: str(rate) for code, rate in rates.items()},
        "accounts": items,
        "included_account_ids": [acct.id for acct in accounts],
        "validation": {"valid": len(errors) == 0, "errors": errors},
    }
