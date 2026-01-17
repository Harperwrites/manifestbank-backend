import pytest

@pytest.mark.asyncio
async def test_register_duplicate(client):
    payload = {"email": "a@test.com", "password": "123"}
    r1 = await client.post("/auth/register", json=payload)
    r2 = await client.post("/auth/register", json=payload)

    assert r1.status_code == 200
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/auth/register", json={"email": "x@test.com", "password": "abc"})
    r = await client.post("/auth/login", json={"email": "x@test.com", "password": "nope"})
    assert r.status_code == 401
