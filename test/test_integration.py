import pytest

@pytest.mark.asyncio
async def test_full_flow(client):
    # register
    await client.post("/auth/register", json={"email": "i@test.com", "password": "pass"})

    # login
    login = await client.post("/auth/login", json={"email": "i@test.com", "password": "pass"})
    token = login.json()["access_token"]

    # create account
    acc = await client.post("/accounts/", json={"type": "checking"}, headers={"Authorization": f"Bearer {token}"})
    acc_id = acc.json()["id"]

    # deposit
    await client.post("/transactions/deposit", json={"account_id": acc_id, "amount": 200}, headers={"Authorization": f"Bearer {token}"})

    # check dashboard
    dash = await client.get("/dashboard/", headers={"Authorization": f"Bearer {token}"})
    assert dash.status_code == 200
