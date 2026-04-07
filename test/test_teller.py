import pytest
from uuid import uuid4
from app.models.user import User
from app.services.teller_provider import rate_limiter
from app.routes import teller as teller_route


async def _safe_login(client, db, email_prefix: str):
    normalized = "".join(ch for ch in email_prefix.lower() if ch.isalnum())
    safe_prefix = (normalized[:12] or "tellertest")
    last_error = None
    for _attempt in range(3):
        suffix = str(uuid4().int % 100000000)
        email = f"{safe_prefix}{suffix}@test.com"
        username = f"tellertest{suffix}"
        register = await client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "pass",
                "username": username,
                "accept_terms": True,
            },
        )
        register_body = register.json()
        if register.status_code != 200:
            last_error = {"register_status": register.status_code, "register_body": register_body}
            continue
        user = db.query(User).filter(User.email == email).first()
        if not user:
            last_error = {"register_status": register.status_code, "register_body": register_body, "detail": "user not found after register"}
            continue
        user.email_verified = True
        user.is_premium = True
        db.add(user)
        db.commit()
        login = await client.post("/auth/login", json={"identifier": email, "password": "pass"})
        body = login.json()
        if login.status_code == 200 and "access_token" in body:
            return body["access_token"]
        last_error = {
            "register_status": register.status_code,
            "register_body": register_body,
            "login_status": login.status_code,
            "login_body": body,
            "email": email,
            "username": username,
        }
    raise AssertionError(last_error)


@pytest.mark.asyncio
async def test_teller_create_account_confirmation_flow(client, auth_helper):
    login = await auth_helper(client, "teller1@test.com", "pass", "telleruser1")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "Create account"}, headers=headers)
    assert first.status_code == 200
    thread_id = first.json()["thread"]["id"]

    second = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Teller Primary"}, headers=headers)
    assert second.status_code == 200
    assert "Which account type?" in second.json()["assistant_message"]["content"]

    third = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "personal"}, headers=headers)
    assert third.status_code == 200
    assert "Starting balance?" in third.json()["assistant_message"]["content"]

    fourth = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "no"}, headers=headers)
    assert fourth.status_code == 200
    assert "Confirm create account" in fourth.json()["assistant_message"]["content"]

    fifth = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "yes"}, headers=headers)
    assert fifth.status_code == 200
    assert "Account created:" in fifth.json()["assistant_message"]["content"]


@pytest.mark.asyncio
async def test_teller_transfer_and_rename_confirmation_flows(client, auth_helper):
    login = await auth_helper(client, "teller2@test.com", "pass", "telleruser2")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_a = await client.post(
        "/accounts",
        json={"name": "Origin", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    create_b = await client.post(
        "/accounts",
        json={"name": "Target", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    origin_id = create_a.json()["id"]
    target_id = create_b.json()["id"]

    deposit = await client.post(
        "/ledger/entries",
        json={
            "account_id": origin_id,
            "direction": "credit",
            "amount": "100.00",
            "currency": "USD",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers=headers,
    )
    assert deposit.status_code == 200

    transfer = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": "Transfer $25 from Origin to Target"},
        headers=headers,
    )
    assert transfer.status_code == 200
    transfer_thread = transfer.json()["thread"]["id"]
    confirm_transfer = await client.post(
        "/teller/chat",
        json={"thread_id": transfer_thread, "message": "yes"},
        headers=headers,
    )
    assert confirm_transfer.status_code == 200
    assert "Done. I transferred $25.00 from “Origin” to “Target”." in confirm_transfer.json()["assistant_message"]["content"]

    rename = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": "Rename account Origin to Origin Renamed"},
        headers=headers,
    )
    assert rename.status_code == 200
    rename_thread = rename.json()["thread"]["id"]
    confirm_rename = await client.post(
        "/teller/chat",
        json={"thread_id": rename_thread, "message": "yes"},
        headers=headers,
    )
    assert confirm_rename.status_code == 200
    assert "Done. I renamed" in confirm_rename.json()["assistant_message"]["content"]

    currency = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": "Change currency for Origin Renamed to EUR"},
        headers=headers,
    )
    assert currency.status_code == 200
    currency_thread = currency.json()["thread"]["id"]
    assert "Confirm change currency for “Origin Renamed” to EUR?" in currency.json()["assistant_message"]["content"]

    confirm_currency = await client.post(
        "/teller/chat",
        json={"thread_id": currency_thread, "message": "yes"},
        headers=headers,
    )
    assert confirm_currency.status_code == 200
    assert "Done. I changed “Origin Renamed” to EUR." in confirm_currency.json()["assistant_message"]["content"]


@pytest.mark.asyncio
async def test_teller_transfer_amount_only_followup_stays_in_transfer_flow(client, auth_helper):
    login = await auth_helper(client, "teller_transfer_amount@test.com", "pass", "tellertransferamount")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_a = await client.post(
        "/accounts",
        json={"name": "Origin Flow", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    create_b = await client.post(
        "/accounts",
        json={"name": "Target Flow", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    assert create_a.status_code == 200
    assert create_b.status_code == 200

    first = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": "transfer"},
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["assistant_message"]["content"] == "What amount should I transfer?"
    thread_id = first.json()["thread"]["id"]

    second = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "1300"},
        headers=headers,
    )
    assert second.status_code == 200
    content = second.json()["assistant_message"]["content"]
    assert "Which account should I transfer from?" in content
    assert "Origin Flow" in content
    assert "Target Flow" in content


@pytest.mark.asyncio
async def test_teller_deposit_amount_only_followup_stays_in_deposit_flow(client, auth_helper):
    rate_limiter.buckets.clear()
    login = await auth_helper(client, "teller_deposit_amount@test.com", "pass", "tellerdepositamount")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_account_resp = await client.post(
        "/accounts",
        json={"name": "Miracles", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    assert create_account_resp.status_code == 200

    first = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": "deposit"},
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["assistant_message"]["content"] == "What amount should I deposit?"
    thread_id = first.json()["thread"]["id"]

    second = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "300000"},
        headers=headers,
    )
    assert second.status_code == 200
    content = second.json()["assistant_message"]["content"]
    assert "Which account should I use?" in content
    assert "Miracles" in content


@pytest.mark.asyncio
async def test_teller_transfer_flow_collects_from_then_to_account(client, auth_helper):
    rate_limiter.buckets.clear()
    login = await auth_helper(client, "teller_transfer_stepwise@test.com", "pass", "telltrstep")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_from = await client.post(
        "/accounts",
        json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"},
        headers=headers,
    )
    create_to = await client.post(
        "/accounts",
        json={"name": "Miracles", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    assert create_from.status_code == 200
    assert create_to.status_code == 200

    first = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": "transfer"},
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["assistant_message"]["content"] == "What amount should I transfer?"
    thread_id = first.json()["thread"]["id"]

    second = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "3000"},
        headers=headers,
    )
    assert second.status_code == 200
    assert "Which account should I transfer from?" in second.json()["assistant_message"]["content"]

    third = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "Wealth Builder"},
        headers=headers,
    )
    assert third.status_code == 200
    assert "Which account should I transfer to?" in third.json()["assistant_message"]["content"]
    assert "Miracles" in third.json()["assistant_message"]["content"]

    fourth = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "Miracles"},
        headers=headers,
    )
    assert fourth.status_code == 200
    assert "Confirm transfer $3,000.00 from “Wealth Builder” to “Miracles”?" in fourth.json()["assistant_message"]["content"]


@pytest.mark.asyncio
async def test_teller_balance_fast_path_does_not_invoke_provider(client, db, monkeypatch):
    token = await _safe_login(client, db, "teller_balance_fast")
    headers = {"Authorization": f"Bearer {token}"}

    checking = await client.post("/accounts", json={"name": "Checking", "account_type": "personal", "currency": "USD"}, headers=headers)
    savings = await client.post("/accounts", json={"name": "Savings", "account_type": "personal", "currency": "USD"}, headers=headers)
    await client.post("/ledger/entries", json={"account_id": checking.json()["id"], "direction": "credit", "amount": "450.00", "currency": "USD", "entry_type": "deposit", "status": "posted"}, headers=headers)
    await client.post("/ledger/entries", json={"account_id": savings.json()["id"], "direction": "credit", "amount": "1200.00", "currency": "USD", "entry_type": "deposit", "status": "posted"}, headers=headers)

    async def fail_provider(*args, **kwargs):
        raise AssertionError("provider should not be called for balance")

    monkeypatch.setattr(teller_route, "generate_teller_reply", fail_provider)

    response = await client.post("/teller/chat", json={"thread_id": None, "message": "balance"}, headers=headers)

    assert response.status_code == 200
    content = response.json()["assistant_message"]["content"]
    assert "**Your account balances**" in content
    assert "- Checking: $450.00" in content
    assert "- Savings: $1,200.00" in content


@pytest.mark.asyncio
async def test_teller_balance_fast_path_logs_used_llm_false_and_no_provider_timing(client, db, monkeypatch, caplog):
    token = await _safe_login(client, db, "teller_balance_logs")
    headers = {"Authorization": f"Bearer {token}"}

    checking = await client.post("/accounts", json={"name": "Checking", "account_type": "personal", "currency": "USD"}, headers=headers)
    await client.post("/ledger/entries", json={"account_id": checking.json()["id"], "direction": "credit", "amount": "450.00", "currency": "USD", "entry_type": "deposit", "status": "posted"}, headers=headers)

    async def fail_provider(*args, **kwargs):
        raise AssertionError("provider should not be called for balance logging path")

    monkeypatch.setattr(teller_route, "generate_teller_reply", fail_provider)

    with caplog.at_level("INFO", logger="teller"):
        response = await client.post("/teller/chat", json={"thread_id": None, "message": "balance"}, headers=headers)

    assert response.status_code == 200
    log_text = "\n".join(caplog.messages)
    assert "teller_turn_timing" in log_text
    assert "kind=balance" in log_text
    assert "used_llm=false" in log_text
    assert "teller_provider_timing" not in log_text


@pytest.mark.asyncio
@pytest.mark.parametrize("message,expected", [("no thanks", "Okay."), ("cancel", "Okay."), ("stop", "Okay.")])
async def test_teller_no_thanks_fast_path_stays_unformatted(client, db, monkeypatch, message, expected):
    token = await _safe_login(client, db, "teller_nothanks_fast")
    headers = {"Authorization": f"Bearer {token}"}

    async def fail_provider(*args, **kwargs):
        raise AssertionError("provider should not be called for no thanks")

    monkeypatch.setattr(teller_route, "generate_teller_reply", fail_provider)

    response = await client.post("/teller/chat", json={"thread_id": None, "message": message}, headers=headers)

    assert response.status_code == 200
    content = response.json()["assistant_message"]["content"]
    assert content == expected
    assert "## Insight" not in content
    assert "## Key Points" not in content
    assert "## Reflection" not in content


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["thank you", "thanks", "thank ypu"])
async def test_teller_thank_you_fast_path_stays_unformatted(client, db, monkeypatch, message):
    token = await _safe_login(client, db, "teller_thanks_fast")
    headers = {"Authorization": f"Bearer {token}"}

    async def fail_provider(*args, **kwargs):
        raise AssertionError("provider should not be called for thank you")

    monkeypatch.setattr(teller_route, "generate_teller_reply", fail_provider)

    response = await client.post("/teller/chat", json={"thread_id": None, "message": message}, headers=headers)

    assert response.status_code == 200
    content = response.json()["assistant_message"]["content"]
    assert content == "You’re welcome."
    assert "## Insight" not in content
    assert "## Key Points" not in content
    assert "## Reflection" not in content


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["yes", "yes please"])
async def test_teller_pending_transfer_confirmation_bypasses_provider(client, db, monkeypatch, message, caplog):
    token = await _safe_login(client, db, "teller_pending_yes_fast")
    headers = {"Authorization": f"Bearer {token}"}

    miracles = await client.post("/accounts", json={"name": "Miracles", "account_type": "personal", "currency": "USD"}, headers=headers)
    wealth = await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)

    async def fail_provider(*args, **kwargs):
        raise AssertionError("provider should not be called for pending confirmation")

    monkeypatch.setattr(teller_route, "generate_teller_reply", fail_provider)

    first = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": f"transfer 2500 from #{miracles.json()['id']} to #{wealth.json()['id']}"},
        headers=headers,
    )
    thread_id = first.json()["thread"]["id"]

    with caplog.at_level("INFO", logger="teller"):
        confirmed = await client.post("/teller/chat", json={"thread_id": thread_id, "message": message}, headers=headers)

    assert confirmed.status_code == 200
    assert "Done. I transferred $2,500.00" in confirmed.json()["assistant_message"]["content"]
    log_text = "\n".join(caplog.messages)
    assert "used_llm=false" in log_text
    assert "teller_provider_timing" not in log_text


@pytest.mark.asyncio
async def test_teller_transfer_awaiting_account_accepts_numeric_ids_without_reasking_source(client, db):
    token = await _safe_login(client, db, "teller_numeric_ids")
    headers = {"Authorization": f"Bearer {token}"}

    wealth = await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)
    splurge = await client.post("/accounts", json={"name": "Splurge", "account_type": "personal", "currency": "USD"}, headers=headers)
    travel = await client.post("/accounts", json={"name": "Travel", "account_type": "personal", "currency": "USD"}, headers=headers)

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer"}, headers=headers)
    assert first.status_code == 200
    thread_id = first.json()["thread"]["id"]
    assert first.json()["assistant_message"]["content"] == "What amount should I transfer?"

    second = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "1000"}, headers=headers)
    assert second.status_code == 200
    assert "Which account should I transfer from?" in second.json()["assistant_message"]["content"]

    third = await client.post("/teller/chat", json={"thread_id": thread_id, "message": str(splurge.json()["id"])}, headers=headers)
    assert third.status_code == 200
    third_content = third.json()["assistant_message"]["content"]
    assert "Which account should I transfer to?" in third_content
    assert "Which account should I transfer from?" not in third_content

    fourth = await client.post("/teller/chat", json={"thread_id": thread_id, "message": str(wealth.json()["id"])}, headers=headers)
    assert fourth.status_code == 200
    assert f"Confirm transfer $1,000.00 from “Splurge” to “Wealth Builder”?" in fourth.json()["assistant_message"]["content"]


@pytest.mark.asyncio
async def test_teller_transfer_awaiting_account_accepts_account_name_without_reasking_source(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_account_name_fast")
    headers = {"Authorization": f"Bearer {token}"}

    wealth = await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)
    splurge = await client.post("/accounts", json={"name": "Splurge", "account_type": "personal", "currency": "USD"}, headers=headers)

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer"}, headers=headers)
    assert first.status_code == 200
    thread_id = first.json()["thread"]["id"]
    assert first.json()["assistant_message"]["content"] == "What amount should I transfer?"

    second = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "1000"}, headers=headers)
    assert second.status_code == 200
    assert "Which account should I transfer from?" in second.json()["assistant_message"]["content"]

    third = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Splurge"}, headers=headers)
    assert third.status_code == 200
    third_content = third.json()["assistant_message"]["content"]
    assert "Which account should I transfer to?" in third_content
    assert "Which account should I transfer from?" not in third_content

    fourth = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Wealth"}, headers=headers)
    assert fourth.status_code == 200
    assert f"Confirm transfer $1,000.00 from “Splurge” to “Wealth Builder”?" in fourth.json()["assistant_message"]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["no thanks", "no", "nope", "nah", "cancel", "stop"])
async def test_teller_no_thanks_cancels_pending_transfer_immediately(client, db, message):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_no_thanks_pending")
    headers = {"Authorization": f"Bearer {token}"}

    miracles = await client.post("/accounts", json={"name": "Miracles", "account_type": "personal", "currency": "USD"}, headers=headers)
    wealth = await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)

    first = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": f"transfer 2500 from #{miracles.json()['id']} to #{wealth.json()['id']}"},
        headers=headers,
    )
    assert first.status_code == 200
    thread_id = first.json()["thread"]["id"]
    assert "Confirm transfer $2,500.00" in first.json()["assistant_message"]["content"]

    declined = await client.post("/teller/chat", json={"thread_id": thread_id, "message": message}, headers=headers)
    assert declined.status_code == 200
    assert declined.json()["assistant_message"]["content"] == "Got it. I canceled that transfer."


@pytest.mark.asyncio
async def test_teller_affirmations_still_use_provider_path(client, db, monkeypatch):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_affirmations_provider")
    headers = {"Authorization": f"Bearer {token}"}

    async def fake_provider(user_id, message, history=None, short_mode=False):
        assert message == "affirmations"
        return False, "- I trust the pace that lets me stay clear.\n- I let calm support follow-through.\n- I keep my attention where it helps.\n"

    monkeypatch.setattr(teller_route, "generate_teller_reply", fake_provider)

    response = await client.post("/teller/chat", json={"thread_id": None, "message": "affirmations"}, headers=headers)

    assert response.status_code == 200
    content = response.json()["assistant_message"]["content"]
    assert content.lstrip().startswith("- ")
    assert "## Insight" not in content
    assert "## Reflection" not in content


@pytest.mark.asyncio
async def test_teller_transfer_accepts_typoish_account_name_matches(client, auth_helper):
    rate_limiter.buckets.clear()
    suffix = uuid4().hex[:8]
    login = await auth_helper(client, f"teller_transfer_typo_{suffix}@test.com", "pass", f"tttypo{suffix}")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_from = await client.post(
        "/accounts",
        json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"},
        headers=headers,
    )
    create_to = await client.post(
        "/accounts",
        json={"name": "Miracles", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    assert create_from.status_code == 200
    assert create_to.status_code == 200

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    await client.post("/teller/chat", json={"thread_id": thread_id, "message": "3000"}, headers=headers)

    third = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "wealth buidler"},
        headers=headers,
    )
    assert third.status_code == 200
    assert "Which account should I transfer to?" in third.json()["assistant_message"]["content"]

    fourth = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "Miracle"},
        headers=headers,
    )
    assert fourth.status_code == 200
    assert "Confirm transfer $3,000.00 from “Wealth Builder” to “Miracles”?" in fourth.json()["assistant_message"]["content"]


@pytest.mark.asyncio
async def test_teller_transfer_thread_is_not_hijacked_by_unrelated_pending_create_account(client, auth_helper):
    rate_limiter.buckets.clear()
    suffix = uuid4().hex[:8]
    login = await auth_helper(client, f"teller_transfer_isolated_{suffix}@test.com", "pass", f"ttiso{suffix}")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    stale = await client.post("/teller/chat", json={"thread_id": None, "message": "open new account"}, headers=headers)
    stale_thread_id = stale.json()["thread"]["id"]
    await client.post("/teller/chat", json={"thread_id": stale_thread_id, "message": "check ur histiry, weve talked about it"}, headers=headers)
    await client.post("/teller/chat", json={"thread_id": stale_thread_id, "message": "Trust"}, headers=headers)

    create_a = await client.post(
        "/accounts",
        json={"name": "Origin Iso", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    create_b = await client.post(
        "/accounts",
        json={"name": "Target Iso", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    assert create_a.status_code == 200
    assert create_b.status_code == 200

    transfer = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer"}, headers=headers)
    assert transfer.status_code == 200
    assert transfer.json()["assistant_message"]["content"] == "What amount should I transfer?"
    transfer_thread_id = transfer.json()["thread"]["id"]

    amount_reply = await client.post(
        "/teller/chat",
        json={"thread_id": transfer_thread_id, "message": "1300"},
        headers=headers,
    )
    assert amount_reply.status_code == 200
    content = amount_reply.json()["assistant_message"]["content"]
    assert "Which account should I transfer from?" in content
    assert "Confirm create account" not in content


@pytest.mark.asyncio
async def test_teller_transfer_typo_intent_stays_in_transfer_flow(client, auth_helper):
    rate_limiter.buckets.clear()
    suffix = uuid4().hex[:8]
    login = await auth_helper(client, f"teller_transfer_intent_{suffix}@test.com", "pass", f"ttintent{suffix}")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_a = await client.post(
        "/accounts",
        json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"},
        headers=headers,
    )
    create_b = await client.post(
        "/accounts",
        json={"name": "Miracles", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    assert create_a.status_code == 200
    assert create_b.status_code == 200

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "tranfer 5000"}, headers=headers)
    assert first.status_code == 200
    content = first.json()["assistant_message"]["content"]
    assert "Which account should I transfer from?" in content
    assert "Wealth Builder" in content
    assert "Miracles" in content


@pytest.mark.asyncio
async def test_teller_transfer_accepts_numeric_from_to_shorthand(client, auth_helper):
    rate_limiter.buckets.clear()
    suffix = uuid4().hex[:8]
    login = await auth_helper(client, f"teller_transfer_shorthand_{suffix}@test.com", "pass", f"ttshort{suffix}")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_a = await client.post(
        "/accounts",
        json={"name": "Origin Short", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    create_b = await client.post(
        "/accounts",
        json={"name": "Target Short", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    origin_id = create_a.json()["id"]
    target_id = create_b.json()["id"]

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    await client.post("/teller/chat", json={"thread_id": thread_id, "message": "1300"}, headers=headers)

    shorthand = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": f"{origin_id} to {target_id}"},
        headers=headers,
    )
    assert shorthand.status_code == 200
    content = shorthand.json()["assistant_message"]["content"]
    assert "Confirm transfer $1,300.00" in content
    assert "Origin Short" in content
    assert "Target Short" in content


@pytest.mark.asyncio
async def test_teller_thanks_reply_uses_clean_grammar(client, auth_helper):
    login = await auth_helper(client, "teller3@test.com", "pass", "telleruser3")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "Open new account"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Miracles"}, headers=headers)
    await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Personal"}, headers=headers)
    await client.post("/teller/chat", json={"thread_id": thread_id, "message": "75000"}, headers=headers)
    await client.post("/teller/chat", json={"thread_id": thread_id, "message": "yes please"}, headers=headers)

    thanks = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "thank you"}, headers=headers)
    assert thanks.status_code == 200
    assert thanks.json()["assistant_message"]["content"] == "You’re welcome."


@pytest.mark.asyncio
async def test_teller_keeps_gbp_create_account_flow_sticky(client, auth_helper):
    rate_limiter.buckets.clear()
    login = await auth_helper(client, "teller4@test.com", "pass", "telleruser4")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": "I'd like another account open in GBP currency"},
        headers=headers,
    )
    assert first.status_code == 200
    assert "What should the account be named?" in first.json()["assistant_message"]["content"]
    assert "GBP" in first.json()["assistant_message"]["content"]
    thread_id = first.json()["thread"]["id"]

    second = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "UK Money should be the name and personal"},
        headers=headers,
    )
    assert second.status_code == 200
    assert "Starting balance?" in second.json()["assistant_message"]["content"]

    third = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "150,000 pounds"},
        headers=headers,
    )
    assert third.status_code == 200
    assert "Confirm create account “UK Money” (personal, GBP)" in third.json()["assistant_message"]["content"]
    assert "£150,000.00" in third.json()["assistant_message"]["content"]

    fourth = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "yes please"}, headers=headers)
    assert fourth.status_code == 200
    assert "Account created:" in fourth.json()["assistant_message"]["content"]
    assert "UK Money" in fourth.json()["assistant_message"]["content"]


@pytest.mark.asyncio
async def test_teller_keeps_pending_create_account_context_when_user_references_history(client, auth_helper):
    rate_limiter.buckets.clear()
    login = await auth_helper(client, "teller5@test.com", "pass", "telleruser5")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": "Open new account in GBP"},
        headers=headers,
    )
    assert first.status_code == 200
    thread_id = first.json()["thread"]["id"]

    second = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "check ur histiry, weve talked about it"},
        headers=headers,
    )
    assert second.status_code == 200
    assert "What name should I use?" in second.json()["assistant_message"]["content"]
    assert "GBP" in second.json()["assistant_message"]["content"]

    rate_limiter.buckets.clear()
    third = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "UK Money"},
        headers=headers,
    )
    assert third.status_code == 200
    assert "Which account type?" in third.json()["assistant_message"]["content"]


@pytest.mark.asyncio
async def test_teller_create_account_accepts_confirmed_variants(client, auth_helper):
    rate_limiter.buckets.clear()
    login = await auth_helper(client, "teller6@test.com", "pass", "telleruser6")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": "create new account with gbp currency"},
        headers=headers,
    )
    thread_id = first.json()["thread"]["id"]
    await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Uk Motion"}, headers=headers)
    await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Operating"}, headers=headers)
    fourth = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "150,000 pounds"}, headers=headers)
    assert "£150,000.00" in fourth.json()["assistant_message"]["content"]

    confirmed = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "confirmed"}, headers=headers)
    assert confirmed.status_code == 200
    assert "Account created:" in confirmed.json()["assistant_message"]["content"]
    assert "Uk Motion" in confirmed.json()["assistant_message"]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("approval", ["perfect", "sounds good", "looks good", "go ahead", "do it", "proceed", "absolutely", "okay", "yesss"])
async def test_teller_semantic_confirmation_executes_pending_transfer(client, db, approval):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_semantic_confirm")
    headers = {"Authorization": f"Bearer {token}"}

    create_from = await client.post(
        "/accounts",
        json={"name": "Miracles", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    create_to = await client.post(
        "/accounts",
        json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"},
        headers=headers,
    )
    from_id = create_from.json()["id"]

    await client.post(
        "/ledger/entries",
        json={"account_id": from_id, "direction": "credit", "amount": "6000.00", "currency": "USD", "entry_type": "deposit", "status": "posted"},
        headers=headers,
    )

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    await client.post("/teller/chat", json={"thread_id": thread_id, "message": "2500"}, headers=headers)
    await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Miracles"}, headers=headers)
    confirm = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Wealth Builder"}, headers=headers)
    assert "Confirm transfer $2,500.00 from “Miracles” to “Wealth Builder”?" in confirm.json()["assistant_message"]["content"]

    approved = await client.post("/teller/chat", json={"thread_id": thread_id, "message": approval}, headers=headers)
    assert approved.status_code == 200
    content = approved.json()["assistant_message"]["content"]
    assert "Done. I transferred $2,500.00 from “Miracles” to “Wealth Builder”." in content
    assert "Let your shoulders drop" not in content


@pytest.mark.asyncio
async def test_teller_confirmation_typo_executes_only_when_confirmation_is_pending(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_semantic_typo")
    headers = {"Authorization": f"Bearer {token}"}

    create_from = await client.post("/accounts", json={"name": "Miracles", "account_type": "personal", "currency": "USD"}, headers=headers)
    await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)
    await client.post(
        "/ledger/entries",
        json={"account_id": create_from.json()["id"], "direction": "credit", "amount": "6000.00", "currency": "USD", "entry_type": "deposit", "status": "posted"},
        headers=headers,
    )

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    second = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "ci=onfirmed"}, headers=headers)
    assert second.status_code == 200
    assert second.json()["assistant_message"]["content"] == "What amount should I transfer?"

    await client.post("/teller/chat", json={"thread_id": thread_id, "message": "2500"}, headers=headers)
    await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Miracles"}, headers=headers)
    confirm = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Wealth Builder"}, headers=headers)
    assert "Confirm transfer $2,500.00 from “Miracles” to “Wealth Builder”?" in confirm.json()["assistant_message"]["content"]

    approved = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "ci=onfirmed"}, headers=headers)
    assert approved.status_code == 200
    assert "Done. I transferred $2,500.00 from “Miracles” to “Wealth Builder”." in approved.json()["assistant_message"]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("rejection", ["no", "cancel", "wait", "never mind", "wrong"])
async def test_teller_semantic_confirmation_rejects_pending_transfer_without_execution(client, db, rejection):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_semantic_reject")
    headers = {"Authorization": f"Bearer {token}"}

    create_from = await client.post("/accounts", json={"name": "Miracles", "account_type": "personal", "currency": "USD"}, headers=headers)
    create_to = await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)
    await client.post(
        "/ledger/entries",
        json={"account_id": create_from.json()["id"], "direction": "credit", "amount": "6000.00", "currency": "USD", "entry_type": "deposit", "status": "posted"},
        headers=headers,
    )

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer 2500 from miracles to wealth builder"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    assert "Confirm transfer $2,500.00 from “Miracles” to “Wealth Builder”?" in first.json()["assistant_message"]["content"]

    rejected = await client.post("/teller/chat", json={"thread_id": thread_id, "message": rejection}, headers=headers)
    assert rejected.status_code == 200
    assert rejected.json()["assistant_message"]["content"] == "Got it. I canceled that transfer."


@pytest.mark.asyncio
@pytest.mark.parametrize("edit_message, expected", [
    ("change the amount", "What amount should I use instead?"),
    ("make it 1500", "Confirm transfer $1,500.00 from “Miracles” to “Wealth Builder”?"),
    ("from miracles instead", "Confirm transfer $2,500.00 from “Miracles” to “Wealth Builder”?"),
    ("use a different account", "Which account should I transfer from?"),
])
async def test_teller_semantic_confirmation_edit_intent_updates_or_requests_only_changed_field(client, db, edit_message, expected):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_semantic_edit")
    headers = {"Authorization": f"Bearer {token}"}

    create_from = await client.post("/accounts", json={"name": "Miracles", "account_type": "personal", "currency": "USD"}, headers=headers)
    create_to = await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)
    await client.post(
        "/ledger/entries",
        json={"account_id": create_from.json()["id"], "direction": "credit", "amount": "6000.00", "currency": "USD", "entry_type": "deposit", "status": "posted"},
        headers=headers,
    )

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer 2500 from miracles to wealth builder"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    assert "Confirm transfer $2,500.00 from “Miracles” to “Wealth Builder”?" in first.json()["assistant_message"]["content"]

    edited = await client.post("/teller/chat", json={"thread_id": thread_id, "message": edit_message}, headers=headers)
    assert edited.status_code == 200
    content = edited.json()["assistant_message"]["content"]
    assert expected in content
    assert "Done. I transferred" not in content


@pytest.mark.asyncio
async def test_confirmation_words_do_not_execute_actions_when_confirmation_is_not_pending(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_nonpending_confirm")
    headers = {"Authorization": f"Bearer {token}"}

    create_from = await client.post("/accounts", json={"name": "Miracles", "account_type": "personal", "currency": "USD"}, headers=headers)
    await client.post(
        "/ledger/entries",
        json={"account_id": create_from.json()["id"], "direction": "credit", "amount": "6000.00", "currency": "USD", "entry_type": "deposit", "status": "posted"},
        headers=headers,
    )

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    assert first.json()["assistant_message"]["content"] == "What amount should I transfer?"

    second = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "perfect"}, headers=headers)
    assert second.status_code == 200
    assert second.json()["assistant_message"]["content"] == "What amount should I transfer?"


@pytest.mark.asyncio
async def test_teller_transfer_parses_shorthand_amounts_and_gbp_preference(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_shorthand")
    headers = {"Authorization": f"Bearer {token}"}

    uk = await client.post("/accounts", json={"name": "Uk Motion", "account_type": "operating", "currency": "GBP"}, headers=headers)
    wealth = await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)
    await client.post(
        "/ledger/entries",
        json={"account_id": uk.json()["id"], "direction": "credit", "amount": "10000.00", "currency": "GBP", "entry_type": "deposit", "status": "posted"},
        headers=headers,
    )

    response = await client.post("/teller/chat", json={"thread_id": None, "message": "tranfer 3k to wealth builder pounds"}, headers=headers)
    assert response.status_code == 200
    content = response.json()["assistant_message"]["content"]
    assert "Confirm transfer £3,000.00 from “Uk Motion” to “Wealth Builder”?" in content


@pytest.mark.asyncio
async def test_teller_can_pause_action_for_script_request_without_continue_cancel_loop(client, db, monkeypatch):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_pause")
    headers = {"Authorization": f"Bearer {token}"}

    await client.post("/accounts", json={"name": "Miracles", "account_type": "personal", "currency": "USD"}, headers=headers)

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer 1000"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    assert "Which account should I transfer from?" in first.json()["assistant_message"]["content"]

    async def fake_provider(user_id, message, history=None, short_mode=False):
        return False, "Script:\n\nDaily:\n- What paid move matters most today?\n- What needs a direct answer?\n- What would make today cleaner by tonight?\n\nSpeak-Aloud Anchor:\n- I move the next paid step clearly.\n\nNext Step:\n- Block ten focused minutes for the one money move that matters."

    monkeypatch.setattr(teller_route, "generate_teller_reply", fake_provider)

    second = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "actually wait give me a script first"}, headers=headers)
    assert second.status_code == 200
    content = second.json()["assistant_message"]["content"]
    assert "Script" in content or "script" in content.lower()
    assert "Do you want to continue that request" not in content


@pytest.mark.asyncio
async def test_teller_switch_tasks_cleans_exit_from_active_action(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_switch")
    headers = {"Authorization": f"Bearer {token}"}

    await client.post("/accounts", json={"name": "Miracles", "account_type": "personal", "currency": "USD"}, headers=headers)
    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer 1000"}, headers=headers)
    thread_id = first.json()["thread"]["id"]

    switched = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "switch tasks"}, headers=headers)
    assert switched.status_code == 200
    assert switched.json()["assistant_message"]["content"] == "Okay. I exited that action. What would you like to do instead?"


@pytest.mark.asyncio
async def test_teller_typo_confirmation_approves_pending_transfer(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_typos_confirm")
    headers = {"Authorization": f"Bearer {token}"}

    await client.post("/accounts", json={"name": "Miracles", "account_type": "personal", "currency": "USD"}, headers=headers)
    await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer 3000 from miracles to wealth builder"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    assert "Confirm transfer $3,000.00 from “Miracles” to “Wealth Builder”?" in first.json()["assistant_message"]["content"]

    approved = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "yese"}, headers=headers)
    assert approved.status_code == 200
    assert "Done. I transferred $3,000.00 from “Miracles” to “Wealth Builder”." in approved.json()["assistant_message"]["content"]


@pytest.mark.asyncio
async def test_teller_transfer_correction_updates_instead_of_cancelling(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_transfer_fix")
    headers = {"Authorization": f"Bearer {token}"}

    await client.post("/accounts", json={"name": "Miracles", "account_type": "personal", "currency": "USD"}, headers=headers)
    await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)
    await client.post("/accounts", json={"name": "Uk Motion", "account_type": "operating", "currency": "GBP"}, headers=headers)

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer 2000"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    assert "Which account should I transfer from?" in first.json()["assistant_message"]["content"]

    second = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "miracles"}, headers=headers)
    assert "Which account should I transfer to?" in second.json()["assistant_message"]["content"]

    corrected = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "no wait not that one wealth builder to uk motion"},
        headers=headers,
    )
    content = corrected.json()["assistant_message"]["content"]
    assert "Confirm transfer" in content
    assert "from “Wealth Builder” to “Uk Motion”" in content
    assert "canceled" not in content.lower()


@pytest.mark.asyncio
async def test_teller_cross_currency_transfer_preserves_explicit_amount_and_currency(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_currency_integrity")
    headers = {"Authorization": f"Bearer {token}"}

    await client.post("/accounts", json={"name": "Uk Motion", "account_type": "operating", "currency": "GBP"}, headers=headers)
    await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer 2000 pounds to wealth builder"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    first_content = first.json()["assistant_message"]["content"]
    if "Confirm transfer £2,000.00 from “Uk Motion” to “Wealth Builder”?" in first_content:
        content = first_content
    else:
        assert "Which account should I transfer from?" in first_content
        second = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "uk account"}, headers=headers)
        content = second.json()["assistant_message"]["content"]
    assert "Confirm transfer £2,000.00 from “Uk Motion” to “Wealth Builder”?" in content
    assert "$1,000.00" not in content


@pytest.mark.asyncio
async def test_teller_do_that_again_after_completed_transfer_confirms_repeat(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_repeat_transfer")
    headers = {"Authorization": f"Bearer {token}"}

    from_acct = await client.post("/accounts", json={"name": "Miracles", "account_type": "personal", "currency": "USD"}, headers=headers)
    await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)
    await client.post(
        "/ledger/entries",
        json={"account_id": from_acct.json()["id"], "direction": "credit", "amount": "8000.00", "currency": "USD", "entry_type": "deposit", "status": "posted"},
        headers=headers,
    )

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer 1200 from miracles to wealth builder"}, headers=headers)
    thread_id = first.json()["thread"]["id"]
    assert "Confirm transfer $1,200.00 from “Miracles” to “Wealth Builder”?" in first.json()["assistant_message"]["content"]
    done = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "confirmed"}, headers=headers)
    assert "Done. I transferred $1,200.00 from “Miracles” to “Wealth Builder”." in done.json()["assistant_message"]["content"]

    repeated = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "do that again please"}, headers=headers)
    assert repeated.status_code == 200
    assert "Confirm transfer $1,200.00 from “Miracles” to “Wealth Builder”?" in repeated.json()["assistant_message"]["content"]
    assert "short script, a few affirmations, or a 2-minute reset" not in repeated.json()["assistant_message"]["content"]


@pytest.mark.asyncio
async def test_teller_account_lists_use_native_currency_balances(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_native_balances")
    headers = {"Authorization": f"Bearer {token}"}

    uk = await client.post("/accounts", json={"name": "Uk Motion", "account_type": "operating", "currency": "GBP"}, headers=headers)
    await client.post(
        "/ledger/entries",
        json={
            "account_id": uk.json()["id"],
            "direction": "credit",
            "amount": "190500.00",
            "currency": "GBP",
            "entry_type": "deposit",
            "status": "posted",
        },
        headers=headers,
    )

    response = await client.post("/teller/chat", json={"thread_id": None, "message": "transfer"}, headers=headers)
    assert response.status_code == 200
    thread_id = response.json()["thread"]["id"]

    second = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "1300 pounds"}, headers=headers)
    assert second.status_code == 200
    content = second.json()["assistant_message"]["content"]
    assert "£190,500.00" in content
    assert "$190,500.00" not in content


@pytest.mark.asyncio
async def test_teller_thread_delete_removes_associated_audit_rows(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_delete_thread")
    headers = {"Authorization": f"Bearer {token}"}

    create_account_resp = await client.post(
        "/accounts",
        json={"name": "Miracles", "account_type": "personal", "currency": "USD"},
        headers=headers,
    )
    assert create_account_resp.status_code == 200

    first = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": "deposit 300 miracles"},
        headers=headers,
    )
    assert first.status_code == 200
    thread_id = first.json()["thread"]["id"]
    assert "Confirm deposit $300.00 into “Miracles”?" in first.json()["assistant_message"]["content"]

    second = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "yes"},
        headers=headers,
    )
    assert second.status_code == 200
    assert "Done. I deposited $300.00 into “Miracles”." in second.json()["assistant_message"]["content"]

    deleted = await client.delete(f"/teller/threads/{thread_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"

    messages = await client.get(f"/teller/threads/{thread_id}/messages", headers=headers)
    assert messages.status_code == 404


@pytest.mark.asyncio
async def test_teller_deposit_with_specified_account_only_asks_for_confirmation(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "tellerdepositone")
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)
    assert created.status_code == 200

    response = await client.post("/teller/chat", json={"thread_id": None, "message": "I'd like to deposit $15,000 into Wealth Builder"}, headers=headers)
    assert response.status_code == 200
    content = response.json()["assistant_message"]["content"]
    assert "Confirm deposit $15,000.00 into “Wealth Builder”?" in content
    assert "Which account" not in content


@pytest.mark.asyncio
async def test_teller_deposit_without_account_then_account_followup_then_yes(client, db, monkeypatch):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "tellerdeposittwo")
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)
    assert created.status_code == 200

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "I'd like to deposit $15,000"}, headers=headers)
    assert first.status_code == 200
    thread_id = first.json()["thread"]["id"]
    assert "Which account should I use?" in first.json()["assistant_message"]["content"]

    second = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Wealth builder please"}, headers=headers)
    assert second.status_code == 200
    assert "Confirm deposit $15,000.00 into “Wealth Builder”?" in second.json()["assistant_message"]["content"]

    third = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Yes"}, headers=headers)
    assert third.status_code == 200
    assert "Done. I deposited $15,000.00 into “Wealth Builder”." in third.json()["assistant_message"]["content"]

    async def fake_provider(user_id, message, history=None, short_mode=False):
        return False, "What would you like to do next?"

    monkeypatch.setattr(teller_route, "generate_teller_reply", fake_provider)

    fourth = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "Yes"}, headers=headers)
    assert fourth.status_code == 200
    assert "Confirm deposit" not in fourth.json()["assistant_message"]["content"]
    assert "Done. I deposited $15,000.00" not in fourth.json()["assistant_message"]["content"]


@pytest.mark.asyncio
async def test_teller_general_balance_shows_all_balances_for_balance_keyword(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_balance_keyword")
    headers = {"Authorization": f"Bearer {token}"}

    checking = await client.post("/accounts", json={"name": "Checking", "account_type": "personal", "currency": "USD"}, headers=headers)
    savings = await client.post("/accounts", json={"name": "Savings", "account_type": "personal", "currency": "USD"}, headers=headers)
    await client.post("/ledger/entries", json={"account_id": checking.json()["id"], "direction": "credit", "amount": "450.00", "currency": "USD", "entry_type": "deposit", "status": "posted"}, headers=headers)
    await client.post("/ledger/entries", json={"account_id": savings.json()["id"], "direction": "credit", "amount": "1200.00", "currency": "USD", "entry_type": "deposit", "status": "posted"}, headers=headers)

    response = await client.post("/teller/chat", json={"thread_id": None, "message": "balance"}, headers=headers)
    assert response.status_code == 200
    content = response.json()["assistant_message"]["content"]
    assert "**Your account balances**" in content
    assert "- Checking: $450.00" in content
    assert "- Savings: $1,200.00" in content
    assert "**Total:** $1,650.00" in content
    assert "Which account" not in content


@pytest.mark.asyncio
async def test_teller_general_balance_handles_common_broad_utterances(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_balance_broad")
    headers = {"Authorization": f"Bearer {token}"}

    travel = await client.post("/accounts", json={"name": "Travel", "account_type": "personal", "currency": "USD"}, headers=headers)
    await client.post("/ledger/entries", json={"account_id": travel.json()["id"], "direction": "credit", "amount": "300.00", "currency": "USD", "entry_type": "deposit", "status": "posted"}, headers=headers)

    for prompt in ["what's my balance?", "show my balances", "how much do I have?", "show everything", "check balances", "check my balances", "Hi. Check balances please"]:
        response = await client.post("/teller/chat", json={"thread_id": None, "message": prompt}, headers=headers)
        assert response.status_code == 200
        content = response.json()["assistant_message"]["content"]
        assert "**Your account balances**" in content
        assert "- Travel: $300.00" in content
        assert "Which account" not in content
        assert content.count("Hi.") <= 1


@pytest.mark.asyncio
async def test_teller_specific_account_balance_shows_only_named_account(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_balance_single")
    headers = {"Authorization": f"Bearer {token}"}

    checking = await client.post("/accounts", json={"name": "Checking", "account_type": "personal", "currency": "USD"}, headers=headers)
    travel = await client.post("/accounts", json={"name": "Travel", "account_type": "personal", "currency": "USD"}, headers=headers)
    await client.post("/ledger/entries", json={"account_id": checking.json()["id"], "direction": "credit", "amount": "900.00", "currency": "USD", "entry_type": "deposit", "status": "posted"}, headers=headers)
    await client.post("/ledger/entries", json={"account_id": travel.json()["id"], "direction": "credit", "amount": "300.00", "currency": "USD", "entry_type": "deposit", "status": "posted"}, headers=headers)

    for prompt in ["what's in travel", "checking balance", "how much is in travel", "show travel account balance"]:
        response = await client.post("/teller/chat", json={"thread_id": None, "message": prompt}, headers=headers)
        assert response.status_code == 200
        content = response.json()["assistant_message"]["content"]
        if "travel" in prompt:
            assert "**Travel balance**" in content
            assert "- Travel: $300.00" in content
            assert "Checking" not in content
        else:
            assert "**Checking balance**" in content
            assert "- Checking: $900.00" in content
            assert "Travel" not in content


@pytest.mark.asyncio
async def test_teller_balance_after_deposit_reflects_updated_number(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "tellerbalfresh")
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.post("/accounts", json={"name": "Savings", "account_type": "personal", "currency": "USD"}, headers=headers)
    assert created.status_code == 200

    first = await client.post("/teller/chat", json={"thread_id": None, "message": "deposit 300 savings"}, headers=headers)
    assert first.status_code == 200
    thread_id = first.json()["thread"]["id"]
    assert "Confirm deposit $300.00 into “Savings”?" in first.json()["assistant_message"]["content"]

    second = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "yes"}, headers=headers)
    assert second.status_code == 200
    assert "New balance: $300.00." in second.json()["assistant_message"]["content"]

    third = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "what's my balance?"}, headers=headers)
    assert third.status_code == 200
    content = third.json()["assistant_message"]["content"]
    assert "**Your account balances**" in content
    assert "- Savings: $300.00" in content
    assert "**Total:** $300.00" in content


@pytest.mark.asyncio
async def test_teller_balance_no_accounts_state_is_graceful(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_balance_empty")
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post("/teller/chat", json={"thread_id": None, "message": "show my balances"}, headers=headers)
    assert response.status_code == 200
    content = response.json()["assistant_message"]["content"]
    assert "**Your account balances**" in content
    assert "You don’t have any active accounts yet." in content
    assert "Create a new account" in content


@pytest.mark.asyncio
async def test_teller_balance_multi_currency_groups_without_combined_total(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_balance_multi")
    headers = {"Authorization": f"Bearer {token}"}

    usd = await client.post("/accounts", json={"name": "Checking", "account_type": "personal", "currency": "USD"}, headers=headers)
    gbp = await client.post("/accounts", json={"name": "Uk Motion", "account_type": "operating", "currency": "GBP"}, headers=headers)
    await client.post("/ledger/entries", json={"account_id": usd.json()["id"], "direction": "credit", "amount": "450.00", "currency": "USD", "entry_type": "deposit", "status": "posted"}, headers=headers)
    await client.post("/ledger/entries", json={"account_id": gbp.json()["id"], "direction": "credit", "amount": "190500.00", "currency": "GBP", "entry_type": "deposit", "status": "posted"}, headers=headers)

    response = await client.post("/teller/chat", json={"thread_id": None, "message": "what are my balances?"}, headers=headers)
    assert response.status_code == 200
    content = response.json()["assistant_message"]["content"]
    assert "**Your account balances**" in content
    assert "**USD accounts**" in content
    assert "- Checking: $450.00" in content
    assert "**USD subtotal:** $450.00" in content
    assert "**GBP accounts**" in content
    assert "- Uk Motion: £190,500.00" in content
    assert "**GBP subtotal:** £190,500.00" in content
    assert "**Total:**" not in content


@pytest.mark.asyncio
async def test_teller_handles_deposit_then_transfer_as_sequential_intents(client, db):
    rate_limiter.buckets.clear()
    token = await _safe_login(client, db, "teller_multi")
    headers = {"Authorization": f"Bearer {token}"}

    miracles = await client.post("/accounts", json={"name": "Miracles", "account_type": "personal", "currency": "USD"}, headers=headers)
    await client.post("/accounts", json={"name": "Wealth Builder", "account_type": "wealth_builder", "currency": "USD"}, headers=headers)

    first = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": "deposit 2000 miracles then transfer 500 to wealth builder actually make it 700"},
        headers=headers,
    )
    thread_id = first.json()["thread"]["id"]
    assert "Confirm deposit $2,000.00 into “Miracles”?" in first.json()["assistant_message"]["content"]

    second = await client.post("/teller/chat", json={"thread_id": thread_id, "message": "yes"}, headers=headers)
    assert second.status_code == 200
    content = second.json()["assistant_message"]["content"]
    assert "Done. I deposited $2,000.00 into “Miracles”." in content
    assert "Next:" in content
    assert "$700.00" in content


@pytest.mark.asyncio
async def test_teller_create_account_name_with_digits_does_not_become_starting_balance(client, auth_helper):
    rate_limiter.buckets.clear()
    login = await auth_helper(client, "teller7@test.com", "pass", "telleruser7")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post(
        "/teller/chat",
        json={"thread_id": None, "message": "create new account with gbp currency"},
        headers=headers,
    )
    thread_id = first.json()["thread"]["id"]

    second = await client.post(
        "/teller/chat",
        json={"thread_id": thread_id, "message": "UK Motion 1774988629462 should be the name and operating"},
        headers=headers,
    )
    assert second.status_code == 200
    assert "Starting balance?" in second.json()["assistant_message"]["content"]
