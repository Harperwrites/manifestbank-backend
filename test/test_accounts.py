import pytest

@pytest.mark.asyncio
async def test_create_account_and_get(client):
    await client.post("/auth/register", json={"email": "a@test.com", "password": "123"})
    login = await client.post("/auth/login", json={"email": "a@test.com", "password": "123"})
    token = login.json()["access_token"]

    create = await client.post("/accounts/", json={"type": "checking"}, headers={"Authorization": f"Bearer {token}"})
    assert create.status_code == 200

    acc_id = create.json()["id"]
    get_acc = await client.get(f"/accounts/{acc_id}", headers={"Authorization": f"Bearer {token}"})
    assert get_acc.status_code == 200
    assert get_acc.json()["type"] == "checking"


@pytest.mark.asyncio
async def test_account_access_control(client):
    await client.post("/auth/register", json={"email": "u1@test.com", "password": "111"})
    await client.post("/auth/register", json={"email": "u2@test.com", "password": "222"})

    login1 = await client.post("/auth/login", json={"email": "u1@test.com", "password": "111"})
    token1 = login1.json()["access_token"]

    acc = await client.post("/accounts/", json={"type": "savings"}, headers={"Authorization": f"Bearer {token1}"})
    acc_id = acc.json()["id"]

    login2 = await client.post("/auth/login", json={"email": "u2@test.com", "password": "222"})
    token2 = login2.json()["access_token"]

    forbidden = await client.get(f"/accounts/{acc_id}", headers={"Authorization": f"Bearer {token2}"})
    assert forbidden.status_code == 403
