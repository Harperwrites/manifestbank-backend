from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.ledger import LedgerEntry
from app.models.user import User
from app.services import tier as tier_service


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_signature_users_always_receive_visible_balance_preview(client, auth_helper, db):
    login = await auth_helper(client, "sigpreview@test.com", "123456", "sigpreview", premium=True, verified=True)
    token = login.json()["access_token"]
    headers = _auth_headers(token)

    account = await client.post(
        "/accounts",
        json={"name": "Signature Preview", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    account_id = account.json()["id"]

    await client.post(
        "/ledger/entries",
        json={
            "account_id": account_id,
            "direction": "credit",
            "amount": "100.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers=headers,
    )

    entry = db.query(LedgerEntry).filter(LedgerEntry.account_id == account_id).first()
    entry.created_at = datetime.now(UTC) - timedelta(hours=13)
    db.add(entry)
    db.commit()

    balance = await client.get(f"/accounts/{account_id}/balance?currency=USD", headers=headers)
    ledger = await client.get(f"/accounts/{account_id}/ledger", headers=headers)

    assert balance.status_code == 200
    assert ledger.status_code == 200
    assert balance.json()["visible_to_user"] is True
    assert balance.json()["is_preview_expired"] is False
    assert ledger.json()[0]["visible_to_user"] is True
    assert ledger.json()[0]["is_preview_expired"] is False


@pytest.mark.asyncio
async def test_free_users_receive_visible_preview_for_recent_balances(client, auth_helper, db):
    login = await auth_helper(client, "freepreviewfresh@test.com", "123456", "freepreviewfresh", premium=True, verified=True)
    token = login.json()["access_token"]
    headers = _auth_headers(token)

    account = await client.post(
        "/accounts",
        json={"name": "Fresh Preview", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    account_id = account.json()["id"]

    await client.post(
        "/ledger/entries",
        json={
            "account_id": account_id,
            "direction": "credit",
            "amount": "88.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers=headers,
    )

    user = db.query(User).filter(User.email == "freepreviewfresh@test.com").first()
    user.is_premium = False
    db.add(user)
    db.commit()

    entry = db.query(LedgerEntry).filter(LedgerEntry.account_id == account_id).first()
    entry.created_at = datetime.now(UTC) - timedelta(hours=2)
    db.add(entry)
    db.commit()

    balance = await client.get(f"/accounts/{account_id}/balance?currency=USD", headers=headers)
    ledger = await client.get(f"/accounts/{account_id}/ledger", headers=headers)

    assert balance.status_code == 200
    assert balance.json()["visible_to_user"] is True
    assert balance.json()["is_preview_expired"] is False
    assert ledger.json()[0]["visible_to_user"] is True
    assert ledger.json()[0]["is_preview_expired"] is False


@pytest.mark.asyncio
async def test_free_users_receive_locked_preview_for_old_balances_without_mutating_data(client, auth_helper, db):
    login = await auth_helper(client, "freepreviewold@test.com", "123456", "freepreviewold", premium=True, verified=True)
    token = login.json()["access_token"]
    headers = _auth_headers(token)

    account = await client.post(
        "/accounts",
        json={"name": "Locked Preview", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    account_id = account.json()["id"]

    await client.post(
        "/ledger/entries",
        json={
            "account_id": account_id,
            "direction": "credit",
            "amount": "250.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers=headers,
    )

    user = db.query(User).filter(User.email == "freepreviewold@test.com").first()
    user.is_premium = False
    db.add(user)
    db.commit()

    entry = db.query(LedgerEntry).filter(LedgerEntry.account_id == account_id).first()
    entry.created_at = datetime.now(UTC) - timedelta(hours=13, minutes=5)
    original_amount = Decimal(str(entry.amount))
    original_id = entry.id
    db.add(entry)
    db.commit()

    balance = await client.get(f"/accounts/{account_id}/balance?currency=USD", headers=headers)
    ledger = await client.get(f"/accounts/{account_id}/ledger", headers=headers)

    assert balance.status_code == 200
    body = balance.json()
    assert body["visible_to_user"] is False
    assert body["is_preview_expired"] is True
    assert Decimal(str(body["balance"])) == Decimal("0.00")

    ledger_body = ledger.json()
    assert ledger_body[0]["visible_to_user"] is False
    assert ledger_body[0]["is_preview_expired"] is True

    persisted = db.query(LedgerEntry).filter(LedgerEntry.id == original_id).first()
    assert persisted is not None
    assert Decimal(str(persisted.amount)) == original_amount
    assert persisted.created_at == entry.created_at


@pytest.mark.asyncio
async def test_balance_preview_expiration_metadata_is_exact(client, auth_helper, db):
    login = await auth_helper(client, "previewexact@test.com", "123456", "previewexact", premium=True, verified=True)
    token = login.json()["access_token"]
    headers = _auth_headers(token)

    account = await client.post(
        "/accounts",
        json={"name": "Exact Preview", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    account_id = account.json()["id"]

    await client.post(
        "/ledger/entries",
        json={
            "account_id": account_id,
            "direction": "credit",
            "amount": "45.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers=headers,
    )

    user = db.query(User).filter(User.email == "previewexact@test.com").first()
    user.is_premium = False
    db.add(user)
    db.commit()

    created_at = datetime(2026, 5, 23, 6, 15, tzinfo=UTC)
    entry = db.query(LedgerEntry).filter(LedgerEntry.account_id == account_id).first()
    entry.created_at = created_at
    db.add(entry)
    db.commit()

    balance = await client.get(f"/accounts/{account_id}/balance?currency=USD", headers=headers)
    ledger = await client.get(f"/accounts/{account_id}/ledger", headers=headers)

    expected_expiry = created_at + timedelta(hours=12)
    assert datetime.fromisoformat(balance.json()["preview_expires_at"]) == expected_expiry
    assert datetime.fromisoformat(ledger.json()[0]["preview_expires_at"]) == expected_expiry


@pytest.mark.asyncio
async def test_existing_free_user_balances_get_preview_window_from_rollout(client, auth_helper, db, monkeypatch):
    monkeypatch.setattr(tier_service.settings, "BALANCE_PREVIEW_ROLLOUT_AT", "2026-05-25T18:00:00Z")
    login = await auth_helper(client, "previewrollout@test.com", "123456", "previewrollout", premium=True, verified=True)
    token = login.json()["access_token"]
    headers = _auth_headers(token)

    account = await client.post(
        "/accounts",
        json={"name": "Rollout Preview", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    account_id = account.json()["id"]

    await client.post(
        "/ledger/entries",
        json={
            "account_id": account_id,
            "direction": "credit",
            "amount": "120.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers=headers,
    )

    user = db.query(User).filter(User.email == "previewrollout@test.com").first()
    user.is_premium = False
    db.add(user)
    db.commit()

    entry = db.query(LedgerEntry).filter(LedgerEntry.account_id == account_id).first()
    entry.created_at = datetime(2026, 5, 20, 10, 0, tzinfo=UTC)
    db.add(entry)
    db.commit()

    preview = tier_service.build_preview_access(
        user=user,
        created_at=entry.created_at,
        now=datetime(2026, 5, 25, 20, 0, tzinfo=UTC),
    )

    assert preview["visible_to_user"] is True
    assert preview["is_preview_expired"] is False
    assert preview["preview_expires_at"] == datetime(2026, 5, 26, 6, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_free_user_balance_only_counts_currently_visible_entries(client, auth_helper, db):
    login = await auth_helper(client, "previewmixed@test.com", "123456", "previewmixed", premium=True, verified=True)
    token = login.json()["access_token"]
    headers = _auth_headers(token)

    account = await client.post(
        "/accounts",
        json={"name": "Mixed Preview", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    account_id = account.json()["id"]

    await client.post(
        "/ledger/entries",
        json={
            "account_id": account_id,
            "direction": "credit",
            "amount": "999.00",
            "currency": "USD",
            "entry_type": "welcome",
            "status": "posted",
        },
        headers=headers,
    )
    await client.post(
        "/ledger/entries",
        json={
            "account_id": account_id,
            "direction": "credit",
            "amount": "100.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers=headers,
    )

    user = db.query(User).filter(User.email == "previewmixed@test.com").first()
    user.is_premium = False
    db.add(user)
    db.commit()

    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.account_id == account_id)
        .order_by(LedgerEntry.id.asc())
        .all()
    )
    entries[0].created_at = datetime.now(UTC) - timedelta(days=1)
    entries[1].created_at = datetime.now(UTC) - timedelta(minutes=30)
    db.add_all(entries)
    db.commit()

    balance = await client.get(f"/accounts/{account_id}/balance?currency=USD", headers=headers)

    assert balance.status_code == 200
    body = balance.json()
    assert body["visible_to_user"] is True
    assert body["is_preview_expired"] is False
    assert Decimal(str(body["balance"])) == Decimal("100.00")


@pytest.mark.asyncio
async def test_dashboard_aggregate_excludes_locked_balances_for_free_users(client, auth_helper, db):
    login = await auth_helper(client, "previewaggregate@test.com", "123456", "previewaggregate", premium=True, verified=True)
    token = login.json()["access_token"]
    headers = _auth_headers(token)

    account = await client.post(
        "/accounts",
        json={"name": "Aggregate Preview", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    account_id = account.json()["id"]

    await client.post(
        "/ledger/entries",
        json={
            "account_id": account_id,
            "direction": "credit",
            "amount": "999.00",
            "currency": "USD",
            "entry_type": "welcome",
            "status": "posted",
        },
        headers=headers,
    )
    await client.post(
        "/ledger/entries",
        json={
            "account_id": account_id,
            "direction": "credit",
            "amount": "100.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers=headers,
    )

    user = db.query(User).filter(User.email == "previewaggregate@test.com").first()
    user.is_premium = False
    db.add(user)
    db.commit()

    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.account_id == account_id)
        .order_by(LedgerEntry.id.asc())
        .all()
    )
    entries[0].created_at = datetime.now(UTC) - timedelta(days=1)
    entries[1].created_at = datetime.now(UTC) - timedelta(minutes=15)
    db.add_all(entries)
    db.commit()

    aggregate = await client.get("/dashboard/aggregate?currency=USD", headers=headers)

    assert aggregate.status_code == 200
    body = aggregate.json()
    assert Decimal(str(body["aggregate_total"])) == Decimal("100.00")
    assert Decimal(str(body["selected_currency_subtotal"])) == Decimal("100.00")
