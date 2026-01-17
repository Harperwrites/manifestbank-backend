import pytest

@pytest.mark.asyncio
async def test_get_current_user(client):
    await client.post("/auth/register", json={"email": "me@test.com", "password": "pass"})

    login = await client.post("/auth/login", json={"email": "me@test.com", "password": "pass"})
    token = login.json()["access_token"]

    r = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    assert r.json()["email"] == "me@test.com"
