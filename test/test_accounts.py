import pytest

@pytest.mark.asyncio
async def test_create_account_and_get(client, auth_helper):
    login = await auth_helper(client, "a@test.com", "123", "atest")
    token = login.json()["access_token"]

    create = await client.post(
        "/accounts",
        json={"name": "Test Account", "account_type": "personal"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create.status_code == 200

    acc_id = create.json()["id"]
    get_acc = await client.get(f"/accounts/{acc_id}", headers={"Authorization": f"Bearer {token}"})
    assert get_acc.status_code == 200
    assert get_acc.json()["account_type"] == "personal"


@pytest.mark.asyncio
async def test_account_access_control(client, auth_helper):
    login1 = await auth_helper(client, "u1@test.com", "111", "userone")
    token1 = login1.json()["access_token"]

    acc = await client.post(
        "/accounts",
        json={"name": "U1 Account", "account_type": "personal"},
        headers={"Authorization": f"Bearer {token1}"},
    )
    acc_id = acc.json()["id"]

    login2 = await auth_helper(client, "u2@test.com", "222", "usertwo")
    token2 = login2.json()["access_token"]

    forbidden = await client.get(f"/accounts/{acc_id}", headers={"Authorization": f"Bearer {token2}"})
    assert forbidden.status_code == 403
