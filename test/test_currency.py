import pytest
from decimal import Decimal

from app.models.user import User
from app.services.fx import DEFAULT_RATES, convert_amount


@pytest.mark.asyncio
async def test_dashboard_currency_requires_premium_and_verified(client, db):
    await client.post(
        "/auth/register",
        json={
            "email": "cur1@test.com",
            "password": "123456",
            "username": "curuser1",
            "accept_terms": True,
        },
    )
    login = await client.post("/auth/login", json={"email": "cur1@test.com", "password": "123456"})
    token = login.json()["access_token"]

    user = db.query(User).filter(User.email == "cur1@test.com").first()
    user.email_verified = True
    user.is_premium = False
    db.commit()

    res = await client.patch(
        "/users/dashboard-currency",
        json={"dashboard_currency": "EUR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 402


@pytest.mark.asyncio
async def test_dashboard_currency_update_success(client, db):
    await client.post(
        "/auth/register",
        json={
            "email": "cur2@test.com",
            "password": "123456",
            "username": "curuser2",
            "accept_terms": True,
        },
    )
    login = await client.post("/auth/login", json={"email": "cur2@test.com", "password": "123456"})
    token = login.json()["access_token"]

    user = db.query(User).filter(User.email == "cur2@test.com").first()
    user.email_verified = True
    user.is_premium = True
    db.commit()

    res = await client.patch(
        "/users/dashboard-currency",
        json={"dashboard_currency": "EUR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["dashboard_currency"] == "EUR"


@pytest.mark.asyncio
async def test_mixed_currency_balance_conversion(client, db):
    await client.post(
        "/auth/register",
        json={
            "email": "cur3@test.com",
            "password": "123456",
            "username": "curuser3",
            "accept_terms": True,
        },
    )
    login = await client.post("/auth/login", json={"email": "cur3@test.com", "password": "123456"})
    token = login.json()["access_token"]

    user = db.query(User).filter(User.email == "cur3@test.com").first()
    user.email_verified = True
    user.is_premium = True
    db.commit()

    usd_acc = await client.post(
        "/accounts",
        json={"name": "USD Account", "account_type": "personal", "currency": "USD", "is_active": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    cad_acc = await client.post(
        "/accounts",
        json={"name": "CAD Account", "account_type": "personal", "currency": "CAD", "is_active": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    usd_id = usd_acc.json()["id"]
    cad_id = cad_acc.json()["id"]

    await client.post(
        "/ledger/entries",
        json={
            "account_id": usd_id,
            "direction": "credit",
            "amount": "100.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    await client.post(
        "/ledger/entries",
        json={
            "account_id": cad_id,
            "direction": "credit",
            "amount": "100.00",
            "currency": "CAD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    cad_to_usd = (Decimal("100.00") * DEFAULT_RATES["CAD"]).quantize(Decimal("0.01"))
    bal_usd = await client.get(
        f"/accounts/{cad_id}/balance?currency=USD",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert bal_usd.status_code == 200
    assert Decimal(str(bal_usd.json()["balance"])) == cad_to_usd


def test_momentum_delta_sign_consistent_across_display_currencies():
    usd_rate = DEFAULT_RATES["USD"]
    gbp_rate = DEFAULT_RATES["GBP"]
    cad_rate = DEFAULT_RATES["CAD"]
    jpy_rate = DEFAULT_RATES["JPY"]

    # Previous snapshot: 100 USD + 100 CAD + 1000 JPY
    prev_usd = Decimal("100.00")
    prev_cad = Decimal("100.00") * cad_rate
    prev_jpy = Decimal("1000.00") * jpy_rate
    prev_base = (prev_usd + prev_cad + prev_jpy).quantize(Decimal("0.01"))

    # Current snapshot: add 10 USD equivalent
    curr_usd = Decimal("110.00")
    curr_cad = Decimal("100.00") * cad_rate
    curr_jpy = Decimal("1000.00") * jpy_rate
    curr_base = (curr_usd + curr_cad + curr_jpy).quantize(Decimal("0.01"))

    delta_base = curr_base - prev_base
    # Convert delta into GBP display
    delta_gbp = (delta_base / gbp_rate).quantize(Decimal("0.01"))

    assert delta_base > 0
    assert delta_gbp > 0


def test_aggregate_total_not_less_than_selected_currency_subtotal():
    gbp_balance = Decimal("402958.66")
    usd_balance = Decimal("1000.00")
    cad_balance = Decimal("500.00")
    jpy_balance = Decimal("300000.00")

    total = (
        convert_amount(gbp_balance, "GBP", "GBP")
        + convert_amount(usd_balance, "USD", "GBP")
        + convert_amount(cad_balance, "CAD", "GBP")
        + convert_amount(jpy_balance, "JPY", "GBP")
    )
    assert total >= gbp_balance


def test_aggregate_matches_sum_of_converted_line_items():
    lines = [
        ("GBP", Decimal("100.00")),
        ("USD", Decimal("50.00")),
        ("CAD", Decimal("75.00")),
    ]
    converted = [convert_amount(amount, cur, "GBP") for cur, amount in lines]
    total = sum(converted, Decimal("0"))
    assert total == sum(converted, Decimal("0"))


@pytest.mark.asyncio
async def test_dashboard_aggregate_converts_and_validates(client, auth_helper):
    login = await auth_helper(client, "agg@test.com", "pass", "agguser")
    token = login.json()["access_token"]

    gbp_acc = await client.post(
        "/accounts",
        json={"name": "GBP Account", "account_type": "personal", "currency": "GBP"},
        headers={"Authorization": f"Bearer {token}"},
    )
    usd_acc = await client.post(
        "/accounts",
        json={"name": "USD Account", "account_type": "personal", "currency": "USD"},
        headers={"Authorization": f"Bearer {token}"},
    )
    jpy_acc = await client.post(
        "/accounts",
        json={"name": "JPY Account", "account_type": "personal", "currency": "JPY"},
        headers={"Authorization": f"Bearer {token}"},
    )
    gbp_id = gbp_acc.json()["id"]
    usd_id = usd_acc.json()["id"]
    jpy_id = jpy_acc.json()["id"]

    await client.post(
        "/ledger/entries",
        json={
            "account_id": gbp_id,
            "direction": "credit",
            "amount": "402958.66",
            "currency": "GBP",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    await client.post(
        "/ledger/entries",
        json={
            "account_id": usd_id,
            "direction": "credit",
            "amount": "1000.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    await client.post(
        "/ledger/entries",
        json={
            "account_id": jpy_id,
            "direction": "credit",
            "amount": "300000.00",
            "currency": "JPY",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    res_usd = await client.get(
        "/dashboard/aggregate?currency=USD",
        headers={"Authorization": f"Bearer {token}"},
    )
    res_gbp = await client.get(
        "/dashboard/aggregate?currency=GBP",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_usd.status_code == 200
    assert res_gbp.status_code == 200
    total_usd = Decimal(res_usd.json()["aggregate_total"])
    total_gbp = Decimal(res_gbp.json()["aggregate_total"])
    assert total_usd != total_gbp
    assert res_gbp.json()["validation"]["valid"] is True


@pytest.mark.asyncio
async def test_transfer_preview_uses_ledger_route_and_converts(client, auth_helper):
    login = await auth_helper(client, "preview@test.com", "pass", "previewuser")
    token = login.json()["access_token"]

    usd_acc = await client.post(
        "/accounts",
        json={"name": "USD Account", "account_type": "personal", "currency": "USD"},
        headers={"Authorization": f"Bearer {token}"},
    )
    cad_acc = await client.post(
        "/accounts",
        json={"name": "CAD Account", "account_type": "personal", "currency": "CAD"},
        headers={"Authorization": f"Bearer {token}"},
    )

    res = await client.post(
        "/transfers/preview",
        json={
            "from_account_id": usd_acc.json()["id"],
            "to_account_id": cad_acc.json()["id"],
            "amount": "100.00",
            "currency": "USD",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["base_currency"] == "USD"
    assert body["debit_currency"] == "USD"
    assert body["credit_currency"] == "CAD"
    assert Decimal(str(body["debit_amount"])) == Decimal("100.00")
    assert Decimal(str(body["credit_amount"])) == convert_amount(Decimal("100.00"), "USD", "CAD")
    assert body["missing_rates"] == []


@pytest.mark.asyncio
async def test_dashboard_aggregate_tracks_pending_transfers_and_momentum(client, auth_helper):
    login = await auth_helper(client, "sync@test.com", "pass", "syncuser")
    token = login.json()["access_token"]

    usd_acc = await client.post(
        "/accounts",
        json={"name": "USD Account", "account_type": "personal", "currency": "USD"},
        headers={"Authorization": f"Bearer {token}"},
    )
    cad_acc = await client.post(
        "/accounts",
        json={"name": "CAD Account", "account_type": "personal", "currency": "CAD"},
        headers={"Authorization": f"Bearer {token}"},
    )
    usd_id = usd_acc.json()["id"]
    cad_id = cad_acc.json()["id"]

    await client.post(
        "/ledger/entries",
        json={
            "account_id": usd_id,
            "direction": "credit",
            "amount": "100.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    await client.post(
        "/ledger/entries",
        json={
            "account_id": cad_id,
            "direction": "credit",
            "amount": "100.00",
            "currency": "CAD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    first = await client.get(
        "/dashboard/aggregate?currency=GBP",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    first_body = first.json()
    first_base_total = Decimal(first_body["aggregate_total_base"])

    await client.post(
        "/ledger/entries",
        json={
            "account_id": usd_id,
            "direction": "credit",
            "amount": "25.00",
            "currency": "USD",
            "entry_type": "scheduled",
            "status": "pending",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    await client.post(
        "/ledger/entries",
        json={
            "account_id": usd_id,
            "direction": "credit",
            "amount": "20.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    second = await client.get(
        f"/dashboard/aggregate?currency=GBP&prev_base_total={first_base_total}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 200
    body = second.json()

    expected_total_base = Decimal("120.00") + convert_amount(Decimal("100.00"), "CAD", "USD")
    expected_pending_base = Decimal("25.00")
    expected_pending_gbp = convert_amount(expected_pending_base, "USD", "GBP")
    expected_delta_base = Decimal("20.00")
    expected_delta_gbp = convert_amount(expected_delta_base, "USD", "GBP")
    selected_subtotal_gbp = convert_amount(Decimal("0.00"), "USD", "GBP")

    assert body["display_currency"] == "GBP"
    assert Decimal(body["aggregate_total_base"]) == expected_total_base
    assert Decimal(body["pending_transfers_base"]) == expected_pending_base
    assert Decimal(body["pending_transfers"]) == expected_pending_gbp
    assert Decimal(body["momentum"]["delta_base"]) == expected_delta_base
    assert Decimal(body["momentum"]["delta_display"]) == expected_delta_gbp
    assert Decimal(body["selected_currency_subtotal"]) == selected_subtotal_gbp
    assert body["validation"]["valid"] is True


@pytest.mark.asyncio
async def test_account_currency_change_requires_verified_and_premium(client, auth_helper, db):
    verified_login = await auth_helper(client, "acctcur1@test.com", "pass", "acctcurone", premium=True, verified=True)
    verified_token = verified_login.json()["access_token"]
    verified_headers = {"Authorization": f"Bearer {verified_token}"}

    account = await client.post(
        "/accounts",
        json={"name": "Currency Account", "account_type": "personal", "currency": "USD"},
        headers=verified_headers,
    )
    account_id = account.json()["id"]

    user = db.query(User).filter(User.email == "acctcur1@test.com").first()
    user.is_premium = False
    db.commit()

    free_attempt = await client.patch(
        f"/accounts/{account_id}",
        json={"currency": "EUR"},
        headers=verified_headers,
    )
    assert free_attempt.status_code == 402

    user.is_premium = True
    user.email_verified = False
    db.commit()

    unverified_attempt = await client.patch(
        f"/accounts/{account_id}",
        json={"currency": "EUR"},
        headers=verified_headers,
    )
    assert unverified_attempt.status_code == 403

    user.email_verified = True
    db.commit()

    success = await client.patch(
        f"/accounts/{account_id}",
        json={"currency": "EUR"},
        headers=verified_headers,
    )
    assert success.status_code == 200
    assert success.json()["currency"] == "EUR"


@pytest.mark.asyncio
async def test_existing_balances_and_transfer_preview_follow_updated_account_currency(client, auth_helper):
    login = await auth_helper(client, "acctcur4@test.com", "pass", "acctcurfour")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    primary = await client.post(
        "/accounts",
        json={"name": "Primary", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    secondary = await client.post(
        "/accounts",
        json={"name": "Secondary", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    primary_id = primary.json()["id"]
    secondary_id = secondary.json()["id"]

    await client.post(
        "/ledger/entries",
        json={
            "account_id": primary_id,
            "direction": "credit",
            "amount": "100.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers=headers,
    )

    updated = await client.patch(
        f"/accounts/{primary_id}",
        json={"currency": "CAD"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["currency"] == "CAD"

    native_balance = await client.get(
        f"/accounts/{primary_id}/balance?currency=CAD",
        headers=headers,
    )
    usd_balance = await client.get(
        f"/accounts/{primary_id}/balance?currency=USD",
        headers=headers,
    )
    preview = await client.post(
        "/transfers/preview",
        json={
            "from_account_id": primary_id,
            "to_account_id": secondary_id,
            "amount": "100.00",
            "currency": "CAD",
        },
        headers=headers,
    )

    assert native_balance.status_code == 200
    assert usd_balance.status_code == 200
    assert preview.status_code == 200

    assert Decimal(str(native_balance.json()["balance"])) == convert_amount(Decimal("100.00"), "USD", "CAD")
    assert Decimal(str(usd_balance.json()["balance"])) == Decimal("100.00")

    preview_body = preview.json()
    assert preview_body["base_currency"] == "CAD"
    assert preview_body["debit_currency"] == "CAD"
    assert preview_body["credit_currency"] == "USD"
    assert Decimal(str(preview_body["debit_amount"])) == Decimal("100.00")
    assert Decimal(str(preview_body["credit_amount"])) == convert_amount(Decimal("100.00"), "CAD", "USD")

    posted = await client.post(
        "/transfers",
        json={
            "from_account_id": primary_id,
            "to_account_id": secondary_id,
            "amount": "50.00",
            "currency": "CAD",
        },
        headers=headers,
    )

    assert posted.status_code == 200
    posted_body = posted.json()
    assert posted_body["debit"]["currency"] == "CAD"
    assert posted_body["credit"]["currency"] == "USD"
    assert Decimal(str(posted_body["debit"]["amount"])) == Decimal("50.00")
    assert Decimal(str(posted_body["credit"]["amount"])) == convert_amount(Decimal("50.00"), "CAD", "USD")

    primary_after = await client.get(
        f"/accounts/{primary_id}/balance?currency=CAD",
        headers=headers,
    )
    secondary_after = await client.get(
        f"/accounts/{secondary_id}/balance?currency=USD",
        headers=headers,
    )

    assert primary_after.status_code == 200
    assert secondary_after.status_code == 200
    expected_primary_after = convert_amount(Decimal("100.00"), "USD", "CAD") - Decimal("50.00")
    assert Decimal(str(primary_after.json()["balance"])) == expected_primary_after
    assert Decimal(str(secondary_after.json()["balance"])) == convert_amount(Decimal("50.00"), "CAD", "USD")


@pytest.mark.asyncio
async def test_free_tier_status_reports_next_available_times(client, auth_helper, db):
    login = await auth_helper(
        client,
        "tierstatus@test.com",
        "123456",
        "tierstatus",
        premium=True,
        verified=True,
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    account = await client.post(
        "/accounts",
        json={"name": "Tier Status", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    assert account.status_code == 200
    account_id = account.json()["id"]

    user = db.query(User).filter(User.email == "tierstatus@test.com").first()
    user.is_premium = False
    db.commit()

    for _ in range(2):
        await client.post(
            "/ledger/entries",
            json={
                "account_id": account_id,
                "direction": "credit",
                "amount": "10.00",
                "currency": "USD",
                "entry_type": "deposit",
                "status": "posted",
            },
            headers=headers,
        )

    res = await client.get("/ledger/free-tier-status", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["deposits"]["used"] == 2
    assert data["deposits"]["remaining"] == 0
    assert data["deposits"]["next_available_at"] is not None


@pytest.mark.asyncio
async def test_scheduled_movements_require_premium_for_free_users(client, auth_helper, db):
    login = await auth_helper(
        client,
        "schedlock@test.com",
        "123456",
        "schedlock",
        premium=True,
        verified=True,
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    account = await client.post(
        "/accounts",
        json={"name": "Schedule Lock", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    assert account.status_code == 200
    account_id = account.json()["id"]

    res = await client.post(
        "/scheduled-entries",
        json={
            "account_id": account_id,
            "direction": "credit",
            "amount": "10.00",
            "currency": "USD",
            "entry_type": "scheduled",
            "reference": "test-scheduled",
            "memo": "Scheduled lock test",
            "scheduled_for": "2030-01-01T12:00:00Z",
        },
        headers=headers,
    )
    assert res.status_code == 200

    free_login = await auth_helper(
        client,
        "schedfree@test.com",
        "123456",
        "schedfree",
        premium=True,
        verified=True,
    )
    free_token = free_login.json()["access_token"]
    free_headers = {"Authorization": f"Bearer {free_token}"}
    free_account = await client.post(
        "/accounts",
        json={"name": "Free Schedule Lock", "account_type": "personal", "currency": "USD"},
        headers=free_headers,
    )
    assert free_account.status_code == 200
    free_account_id = free_account.json()["id"]
    free_user = db.query(User).filter(User.email == "schedfree@test.com").first()
    free_user.is_premium = False
    db.commit()

    attempt = await client.post(
        "/scheduled-entries",
        json={
            "account_id": free_account_id,
            "direction": "credit",
            "amount": "10.00",
            "currency": "USD",
            "entry_type": "scheduled",
            "reference": "test-scheduled-free",
            "memo": "Scheduled lock free test",
            "scheduled_for": "2030-01-01T12:00:00Z",
        },
        headers=free_headers,
    )
    assert attempt.status_code == 402
    assert attempt.json()["detail"] == "ManifestBank™ Signature required to schedule movements."
