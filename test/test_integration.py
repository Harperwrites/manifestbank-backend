import pytest

@pytest.mark.asyncio
async def test_full_flow(client, auth_helper):
    login = await auth_helper(client, "i@test.com", "pass", "itest")
    token = login.json()["access_token"]

    acc = await client.post(
        "/accounts",
        json={"name": "Integration", "account_type": "personal"},
        headers={"Authorization": f"Bearer {token}"},
    )
    acc_id = acc.json()["id"]

    # deposit
    await client.post("/transactions/deposit", json={"account_id": acc_id, "amount": 200}, headers={"Authorization": f"Bearer {token}"})

    # check summary
    dash = await client.get("/summary", headers={"Authorization": f"Bearer {token}"})
    assert dash.status_code == 200


@pytest.mark.asyncio
async def test_myline_message_align_flow(client, auth_helper):
    login_a = await auth_helper(client, "linea@test.com", "pass", "linea")
    token_a = login_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    login_b = await auth_helper(client, "lineb@test.com", "pass", "lineb")
    token_b = login_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    profile_a = await client.get("/ether/me-profile", headers=headers_a)
    profile_b = await client.get("/ether/me-profile", headers=headers_b)
    profile_b_id = profile_b.json()["id"]

    thread = await client.post(
        "/ether/threads",
        json={"participant_profile_ids": [profile_b_id]},
        headers=headers_a,
    )
    assert thread.status_code == 200
    thread_id = thread.json()["id"]

    sent = await client.post(
        f"/ether/threads/{thread_id}/messages",
        json={"content": "Aligned message test"},
        headers=headers_a,
    )
    assert sent.status_code == 200
    message_id = sent.json()["id"]

    aligned = await client.post(f"/ether/messages/{message_id}/align", headers=headers_b)
    assert aligned.status_code == 200
    assert aligned.json()["status"] == "aligned"
    assert aligned.json()["align_count"] == 1

    listed = await client.get(f"/ether/threads/{thread_id}/messages", headers=headers_b)
    assert listed.status_code == 200
    assert listed.json()[0]["aligned_by_me"] is True
    assert listed.json()[0]["align_count"] == 1
