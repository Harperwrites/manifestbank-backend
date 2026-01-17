import pytest

@pytest.mark.asyncio
async def test_transaction_includes_account_in_response(client):
    await client.post("/auth/register", json={"email": "z@test.com", "password": "pass"})
    login = await client.post("/auth/login", json={"email": "z@test.com", "password": "pass"})
    token = login.json()["access_token"]

    acc = await client.post("/accounts/", json={"type": "checking"}, headers={"Authorization": f"Bearer {token}"})
    acc_id = acc.json()["id"]

    tx = await client.post("/transactions/deposit", json={"account_id": acc_id, "amount": 50}, headers={"Authorization": f"Bearer {token}"})
    assert "account" in tx.json()
    assert tx.json()["account"]["id"] == acc_id
