import pytest

@pytest.mark.asyncio
async def test_deposit_withdraw_flow(client):
    await client.post("/auth/register", json={"email": "x@test.com", "password": "123"})
    login = await client.post("/auth/login", json={"email": "x@test.com", "password": "123"})
    token = login.json()["access_token"]

    acc = await client.post("/accounts/", json={"type": "checking"}, headers={"Authorization": f"Bearer {token}"})
    acc_id = acc.json()["id"]

    # deposit
    dep = await client.post("/transactions/deposit", json={"account_id": acc_id, "amount": 500}, headers={"Authorization": f"Bearer {token}"})
    assert dep.status_code == 200

    # withdraw
    wd = await client.post("/transactions/withdraw", json={"account_id": acc_id, "amount": 200}, headers={"Authorization": f"Bearer {token}"})
    assert wd.status_code == 200

    # check balance
    acc = await client.get(f"/accounts/{acc_id}", headers={"Authorization": f"Bearer {token}"})
    assert acc.json()["balance"] == 300


@pytest.mark.asyncio
async def test_transfer_flow(client):
    await client.post("/auth/register", json={"email": "c@test.com", "password": "123"})
    login = await client.post("/auth/login", json={"email": "c@test.com", "password": "123"})
    token = login.json()["access_token"]

    a1 = await client.post("/accounts/", json={"type": "checking"}, headers={"Authorization": f"Bearer {token}"})
    a2 = await client.post("/accounts/", json={"type": "savings"}, headers={"Authorization": f"Bearer {token}"})

    id1 = a1.json()["id"]
    id2 = a2.json()["id"]

    await client.post("/transactions/deposit", json={"account_id": id1, "amount": 1000}, headers={"Authorization": f"Bearer {token}"})

    tr = await client.post("/transactions/transfer",
                           json={"from_id": id1, "to_id": id2, "amount": 400},
                           headers={"Authorization": f"Bearer {token}"})

    assert tr.status_code == 200
