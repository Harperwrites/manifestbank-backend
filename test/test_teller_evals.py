from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.user import User
from app.services import teller_provider
from app.services.teller_provider import rate_limiter, stream_teller_reply
from test.teller_eval_dataset import FORTUNE_ACTION_EVAL_CASES, FORTUNE_PROVIDER_EVAL_CASES
from test.teller_eval_helpers import (
    assert_action_mode_only,
    assert_banned_patterns_absent,
    assert_expected_phrases,
    assert_final_sentence_complete,
    assert_repair_response,
    assert_transfer_direction,
    count_bulletish_lines,
    normalize_eval_text,
)


async def _force_local_teller(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream_response(*args, **kwargs):
        return "Stay with me. still working."

    async def fake_standard_response(*args, **kwargs):
        return "Give it a moment."

    async def passthrough_copyedit(text, short_mode=False):
        return text

    monkeypatch.setattr(teller_provider, "_openai_response_stream", fake_stream_response)
    monkeypatch.setattr(teller_provider, "_openai_response", fake_standard_response)
    monkeypatch.setattr(teller_provider, "_copyedit_reply", passthrough_copyedit)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", FORTUNE_PROVIDER_EVAL_CASES, ids=lambda case: case.id)
async def test_fortune_provider_eval_cases(case, monkeypatch):
    await _force_local_teller(monkeypatch)

    history = [{"role": role, "content": content} for role, content in case.seed_history]
    final_reply = ""
    for message in case.conversation:
        _cached, final_reply = await stream_teller_reply(700000 + abs(hash(case.id)) % 100000, message, history=history)
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": final_reply})

    normalized = normalize_eval_text(final_reply)
    assert_expected_phrases(normalized, case.expects_all, case.expects_any)
    assert_banned_patterns_absent(normalized, case.banned_patterns)
    if case.min_bullet_lines:
        assert count_bulletish_lines(final_reply) >= case.min_bullet_lines, final_reply
    if case.repair_expected:
        assert_repair_response(normalized)
    if case.final_sentence_complete:
        assert_final_sentence_complete(normalized)


async def _login_and_headers(client, db, email_prefix: str):
    normalized = "".join(ch for ch in email_prefix.lower() if ch.isalnum())
    safe_prefix = (normalized[:12] or "tellereval")
    last_error = None
    for _attempt in range(3):
        suffix = str(uuid4().int % 100000000)
        email = f"{safe_prefix}{suffix}@test.com"
        username = f"tellereval{suffix}"
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
            return {"Authorization": f"Bearer {body['access_token']}"}
        last_error = {
            "register_status": register.status_code,
            "register_body": register_body,
            "login_status": login.status_code,
            "login_body": body,
            "email": email,
            "username": username,
        }
    raise AssertionError(last_error)


async def _create_account_map(client, headers, setup_accounts):
    accounts_by_name = {}
    for name, account_type, currency in setup_accounts:
        response = await client.post(
            "/accounts",
            json={"name": name, "account_type": account_type, "currency": currency},
            headers=headers,
        )
        assert response.status_code == 200
        accounts_by_name[name] = response.json()
    return accounts_by_name


async def _seed_initial_deposits(client, headers, accounts_by_name, deposits):
    for account_name, amount in deposits:
        response = await client.post(
            "/ledger/entries",
            json={
                "account_id": accounts_by_name[account_name]["id"],
                "direction": "credit",
                "amount": amount,
                "currency": accounts_by_name[account_name]["currency"],
                "entry_type": "deposit",
                "status": "posted",
            },
            headers=headers,
        )
        assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("case", FORTUNE_ACTION_EVAL_CASES, ids=lambda case: case.id)
async def test_fortune_action_eval_cases(case, client, db):
    rate_limiter.buckets.clear()
    headers = await _login_and_headers(client, db, f"teller_eval_{case.id}")
    accounts_by_name = await _create_account_map(client, headers, case.setup_accounts)
    await _seed_initial_deposits(client, headers, accounts_by_name, case.initial_deposits)

    thread_id = None
    last_reply = ""
    for turn in case.turns:
        response = await client.post(
            "/teller/chat",
            json={"thread_id": thread_id, "message": turn.message},
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        thread_id = body["thread"]["id"]
        last_reply = normalize_eval_text(body["assistant_message"]["content"])
        assert_expected_phrases(last_reply, turn.expects_all, turn.expects_any)
        assert_banned_patterns_absent(last_reply, turn.banned_patterns)
        assert_action_mode_only(last_reply)
        if turn.direction_expected:
            assert_transfer_direction(last_reply, *turn.direction_expected)

    if case.confirmation_variants:
        for variant in case.confirmation_variants:
            rate_limiter.buckets.clear()
            fresh_headers = await _login_and_headers(client, db, f"teller_eval_{case.id}_{variant}")
            fresh_accounts = await _create_account_map(client, fresh_headers, case.setup_accounts)
            await _seed_initial_deposits(client, fresh_headers, fresh_accounts, case.initial_deposits)
            variant_thread_id = None
            for turn in case.turns:
                response = await client.post(
                    "/teller/chat",
                    json={"thread_id": variant_thread_id, "message": turn.message},
                    headers=fresh_headers,
                )
                assert response.status_code == 200
                variant_thread_id = response.json()["thread"]["id"]
            confirmation = await client.post(
                "/teller/chat",
                json={"thread_id": variant_thread_id, "message": variant},
                headers=fresh_headers,
            )
            assert confirmation.status_code == 200
            confirmation_text = normalize_eval_text(confirmation.json()["assistant_message"]["content"])
            assert "done." in confirmation_text.lower(), confirmation_text
            assert_action_mode_only(confirmation_text)
