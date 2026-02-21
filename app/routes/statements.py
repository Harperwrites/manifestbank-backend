# app/routes/statements.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from datetime import datetime, timezone
from decimal import Decimal

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.ledger import LedgerEntry
from app.models.account import Account
from app.crud.crud_account import get_account, list_accounts_for_user
from app.services.tier import is_premium, TIER_NAME

router = APIRouter(tags=["statements"])


def is_admin(user) -> bool:
    return getattr(user, "role", None) == "admin"


def ensure_access(account: Account, current_user):
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if (account.owner_user_id != current_user.id) and (not is_admin(current_user)):
        raise HTTPException(status_code=403, detail="Not allowed")


def parse_month(month: str) -> tuple[datetime, datetime, bool]:
    try:
        year_str, month_str = month.split("-")
        year = int(year_str)
        mon = int(month_str)
        if mon < 1 or mon > 12:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="month must be in YYYY-MM format")
    start = datetime(year, mon, 1, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    is_current = now.year == year and now.month == mon
    if is_current:
        end = now
    elif mon == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, mon + 1, 1, tzinfo=timezone.utc)
    return start, end, is_current


def format_money(value: Decimal) -> str:
    return f"${value:,.2f}"


def sum_direction(db: Session, account_ids: list[int], start: datetime | None, end: datetime | None, direction: str):
    credit_sum = func.coalesce(
        func.sum(case((LedgerEntry.direction == direction, LedgerEntry.amount), else_=0)),
        0,
    )
    query = db.query(credit_sum.label("total")).filter(
        LedgerEntry.account_id.in_(account_ids),
        LedgerEntry.status == "posted",
        LedgerEntry.currency == "USD",
    )
    if start is not None:
        query = query.filter(LedgerEntry.created_at >= start)
    if end is not None:
        query = query.filter(LedgerEntry.created_at < end)
    row = query.first()
    return Decimal(str(row.total or 0))


def sum_transfers(db: Session, account_ids: list[int], start: datetime, end: datetime, direction: str | None = None):
    query = db.query(func.coalesce(func.sum(LedgerEntry.amount), 0)).filter(
        LedgerEntry.account_id.in_(account_ids),
        LedgerEntry.status == "posted",
        LedgerEntry.currency == "USD",
        LedgerEntry.entry_type == "transfer",
        LedgerEntry.created_at >= start,
        LedgerEntry.created_at < end,
    )
    if direction:
        query = query.filter(LedgerEntry.direction == direction)
    row = query.first()
    return Decimal(str(row[0] or 0))


def compute_balance(db: Session, account_ids: list[int], end: datetime | None):
    credit_sum = func.coalesce(
        func.sum(case((LedgerEntry.direction == "credit", LedgerEntry.amount), else_=0)),
        0,
    )
    debit_sum = func.coalesce(
        func.sum(case((LedgerEntry.direction == "debit", LedgerEntry.amount), else_=0)),
        0,
    )
    query = db.query(credit_sum.label("credits"), debit_sum.label("debits")).filter(
        LedgerEntry.account_id.in_(account_ids),
        LedgerEntry.status == "posted",
        LedgerEntry.currency == "USD",
    )
    if end is not None:
        query = query.filter(LedgerEntry.created_at < end)
    row = query.first()
    credits = Decimal(str(row.credits or 0))
    debits = Decimal(str(row.debits or 0))
    return credits - debits


@router.get("/statements")
def get_statements(
    month: str = Query(..., description="Month in YYYY-MM format"),
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not is_premium(current_user):
        raise HTTPException(
            status_code=402,
            detail=f"Statements are available on {TIER_NAME}. Upgrade to unlock statements.",
        )
    start, end, is_current = parse_month(month)

    if account_id:
        account = get_account(db, account_id)
        ensure_access(account, current_user)
        accounts = [account]
    else:
        accounts = list_accounts_for_user(db, current_user.id)

    account_ids = [acct.id for acct in accounts]
    if not account_ids:
        return {"summary": {}, "entries": []}

    starting_balance = compute_balance(db, account_ids, start)
    ending_balance = compute_balance(db, account_ids, end)

    deposits = sum_direction(db, account_ids, start, end, "credit")
    withdrawals = sum_direction(db, account_ids, start, end, "debit")
    transfers_in = sum_transfers(db, account_ids, start, end, "credit")
    transfers_out = sum_transfers(db, account_ids, start, end, "debit")
    transfers_total = transfers_in + transfers_out

    entries_query = (
        db.query(LedgerEntry, Account)
        .join(Account, LedgerEntry.account_id == Account.id)
        .filter(
            LedgerEntry.account_id.in_(account_ids),
            LedgerEntry.status == "posted",
            LedgerEntry.currency == "USD",
            LedgerEntry.created_at >= start,
            LedgerEntry.created_at < end,
        )
        .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
        .limit(200)
    )

    entries = []
    for entry, acct in entries_query.all():
        direction = "+" if entry.direction == "credit" else "-"
        category = entry.entry_type or "manual"
        description = entry.memo or entry.reference or f"{acct.name} activity"
        entries.append(
            {
                "id": str(entry.id),
                "date": entry.created_at.date().isoformat(),
                "description": description,
                "amount": f"{direction}{format_money(Decimal(entry.amount))}",
                "category": category,
            }
        )

    response = {
        "summary": {
            "startingBalance": format_money(starting_balance),
            "endingBalance": format_money(ending_balance),
            "deposits": format_money(deposits - transfers_in),
            "withdrawals": format_money(withdrawals - transfers_out),
            "transfers": format_money(transfers_total),
        },
        "entries": entries,
    }
    if is_current:
        response["as_of"] = end.isoformat()
    return response
