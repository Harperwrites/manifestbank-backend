import pytest
from app.models.ether import Profile
from app.models.user import User

@pytest.mark.asyncio
async def test_register_duplicate(client):
    payload = {"email": "a@test.com", "password": "123", "username": "atest", "accept_terms": True}
    r1 = await client.post("/auth/register", json=payload)
    r2 = await client.post("/auth/register", json=payload)

    assert r1.status_code == 200
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post(
        "/auth/register",
        json={"email": "x@test.com", "password": "abc", "username": "xtest", "accept_terms": True},
    )
    r = await client.post("/auth/login", json={"email": "x@test.com", "password": "nope"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_update_username_does_not_change_ether_profile_display_name(client, db):
    await client.post(
        "/auth/register",
        json={
            "email": "rename@test.com",
            "password": "abc12345",
            "username": "oldname",
            "accept_terms": True,
        },
    )
    user = db.query(User).filter(User.email == "rename@test.com").first()
    user.email_verified = True
    db.add(user)
    db.commit()

    login = await client.post("/auth/login", json={"identifier": "rename@test.com", "password": "abc12345"})
    token = login.json()["access_token"]
    response = await client.patch(
        "/auth/username",
        json={"username": "newname"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    assert profile is not None
    assert profile.display_name == "oldname"


@pytest.mark.asyncio
async def test_update_username_preserves_custom_profile_display_name(client, db):
    await client.post(
        "/auth/register",
        json={
            "email": "custom@test.com",
            "password": "abc12345",
            "username": "oldcustom",
            "accept_terms": True,
        },
    )
    user = db.query(User).filter(User.email == "custom@test.com").first()
    user.email_verified = True
    db.add(user)
    db.commit()
    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    profile.display_name = "Custom Ether Name"
    db.add(profile)
    db.commit()

    login = await client.post("/auth/login", json={"identifier": "custom@test.com", "password": "abc12345"})
    token = login.json()["access_token"]
    response = await client.patch(
        "/auth/username",
        json={"username": "newcustom"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    db.refresh(profile)
    assert profile.display_name == "Custom Ether Name"


@pytest.mark.asyncio
async def test_ether_profile_routes_prefer_ether_display_name_over_dashboard_username(client, db):
    await client.post(
        "/auth/register",
        json={
            "email": "ethername@test.com",
            "password": "abc12345",
            "username": "dashboardname",
            "accept_terms": True,
        },
    )
    user = db.query(User).filter(User.email == "ethername@test.com").first()
    user.email_verified = True
    db.add(user)
    db.commit()

    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    profile.display_name = "Ether Persona"
    db.add(profile)
    db.commit()

    login = await client.post("/auth/login", json={"identifier": "ethername@test.com", "password": "abc12345"})
    token = login.json()["access_token"]

    me_profile = await client.get("/ether/me-profile", headers={"Authorization": f"Bearer {token}"})
    public_profile = await client.get(f"/ether/profiles/{profile.id}", headers={"Authorization": f"Bearer {token}"})

    assert me_profile.status_code == 200
    assert public_profile.status_code == 200
    assert me_profile.json()["display_name"] == "Ether Persona"
    assert public_profile.json()["display_name"] == "Ether Persona"
