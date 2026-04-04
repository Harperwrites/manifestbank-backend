import pytest

@pytest.mark.asyncio
async def test_deposit_withdraw_flow(client, auth_helper):
    login = await auth_helper(client, "x@test.com", "123", "xtest")
    token = login.json()["access_token"]

    acc = await client.post(
        "/accounts",
        json={"name": "Checking", "account_type": "personal"},
        headers={"Authorization": f"Bearer {token}"},
    )
    acc_id = acc.json()["id"]

    # deposit
    dep = await client.post("/transactions/deposit", json={"account_id": acc_id, "amount": 500}, headers={"Authorization": f"Bearer {token}"})
    assert dep.status_code == 200

    # withdraw
    wd = await client.post("/transactions/withdraw", json={"account_id": acc_id, "amount": 200}, headers={"Authorization": f"Bearer {token}"})
    assert wd.status_code == 200

    # check balance
    bal = await client.get(f"/accounts/{acc_id}/balance?currency=USD", headers={"Authorization": f"Bearer {token}"})
    assert float(bal.json()["balance"]) == 300


@pytest.mark.asyncio
async def test_transfer_flow(client, auth_helper):
    login = await auth_helper(client, "c@test.com", "123", "ctest")
    token = login.json()["access_token"]

    a1 = await client.post(
        "/accounts",
        json={"name": "A1", "account_type": "personal"},
        headers={"Authorization": f"Bearer {token}"},
    )
    a2 = await client.post(
        "/accounts",
        json={"name": "A2", "account_type": "personal"},
        headers={"Authorization": f"Bearer {token}"},
    )

    id1 = a1.json()["id"]
    id2 = a2.json()["id"]

    await client.post("/transactions/deposit", json={"account_id": id1, "amount": 1000}, headers={"Authorization": f"Bearer {token}"})

    tr = await client.post("/transactions/transfer",
                           json={"from_id": id1, "to_id": id2, "amount": 400},
                           headers={"Authorization": f"Bearer {token}"})

    assert tr.status_code == 200
