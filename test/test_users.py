import pytest

@pytest.mark.asyncio
async def test_get_current_user(client, auth_helper):
    login = await auth_helper(client, "me@test.com", "pass", "metest", premium=False)
    token = login.json()["access_token"]

    r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    assert r.json()["email"] == "me@test.com"
