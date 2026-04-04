import json
from decimal import Decimal, ROUND_HALF_UP

from app.core.config import settings


DEFAULT_RATES = {
    # USD base (1 unit of currency in USD)
    "USD": Decimal("1"),
    "EUR": Decimal("1.08"),
    "GBP": Decimal("1.27"),
    "CAD": Decimal("0.74"),
    "AUD": Decimal("0.66"),
    "NZD": Decimal("0.61"),
    "JPY": Decimal("0.0067"),
    "CNY": Decimal("0.14"),
    "HKD": Decimal("0.128"),
    "SGD": Decimal("0.74"),
    "INR": Decimal("0.012"),
    "KRW": Decimal("0.00075"),
    "CHF": Decimal("1.12"),
    "SEK": Decimal("0.095"),
    "NOK": Decimal("0.093"),
    "DKK": Decimal("0.145"),
    "MXN": Decimal("0.058"),
    "BRL": Decimal("0.20"),
    "ZAR": Decimal("0.054"),
    "AED": Decimal("0.272"),
    "SAR": Decimal("0.267"),
    "QAR": Decimal("0.275"),
    "KWD": Decimal("3.25"),
    "BHD": Decimal("2.65"),
    "OMR": Decimal("2.60"),
    "ILS": Decimal("0.27"),
    "ANG": Decimal("0.56"),
}


def _load_rates() -> dict[str, Decimal]:
    if settings.FX_RATES_JSON:
        try:
            raw = json.loads(settings.FX_RATES_JSON)
            return {k.upper(): Decimal(str(v)) for k, v in raw.items()}
        except Exception:
            return DEFAULT_RATES
    return DEFAULT_RATES


def get_rates_snapshot() -> dict[str, Decimal]:
    rates = _load_rates()
    rates, _missing = _ensure_rates(rates, [])
    return rates


def convert_amount_with_rate_snapshot(
    amount: Decimal, from_currency: str, to_currency: str, rates: dict[str, Decimal]
) -> tuple[Decimal, list[str], Decimal]:
    from_cur = (from_currency or "USD").upper()
    to_cur = (to_currency or "USD").upper()
    rates, missing = _ensure_rates(rates, [from_cur, to_cur])
    if from_cur == to_cur:
        return amount, missing, Decimal("1")
    rate = rates[from_cur] / rates[to_cur]
    converted = amount * rate
    return converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), missing, rate.quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )


def _ensure_rates(rates: dict[str, Decimal], currencies: list[str]) -> tuple[dict[str, Decimal], list[str]]:
    missing: list[str] = []
    for code in currencies:
        if code not in rates:
            rates[code] = Decimal("1")
            missing.append(code)
    return rates, missing


def convert_amount(amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
    from_cur = (from_currency or "USD").upper()
    to_cur = (to_currency or "USD").upper()
    rates = _load_rates()
    rates, _missing = _ensure_rates(rates, [from_cur, to_cur])
    if from_cur == to_cur:
        return amount
    usd_amount = amount * rates[from_cur]
    converted = usd_amount / rates[to_cur]
    return converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def convert_amount_with_missing(
    amount: Decimal, from_currency: str, to_currency: str
) -> tuple[Decimal, list[str]]:
    from_cur = (from_currency or "USD").upper()
    to_cur = (to_currency or "USD").upper()
    rates = _load_rates()
    rates, missing = _ensure_rates(rates, [from_cur, to_cur])
    if from_cur == to_cur:
        return amount, missing
    usd_amount = amount * rates[from_cur]
    converted = usd_amount / rates[to_cur]
    return converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), missing


def get_rate_with_missing(from_currency: str, to_currency: str) -> tuple[Decimal, list[str]]:
    from_cur = (from_currency or "USD").upper()
    to_cur = (to_currency or "USD").upper()
    rates = _load_rates()
    rates, missing = _ensure_rates(rates, [from_cur, to_cur])
    if from_cur == to_cur:
        return Decimal("1"), missing
    rate = rates[from_cur] / rates[to_cur]
    return rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), missing


def convert_amount_with_rate(
    amount: Decimal, from_currency: str, to_currency: str
) -> tuple[Decimal, list[str], Decimal]:
    from_cur = (from_currency or "USD").upper()
    to_cur = (to_currency or "USD").upper()
    rate, missing = get_rate_with_missing(from_cur, to_cur)
    if from_cur == to_cur:
        return amount, missing, rate
    converted = amount * rate
    return converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), missing, rate
