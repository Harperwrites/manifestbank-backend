import pytest


@pytest.mark.asyncio
async def test_legal_content_serves_current_terms_and_privacy_text(client):
    response = await client.get("/legal/content")

    assert response.status_code == 200
    data = response.json()
    assert data["termsText"].startswith("ManifestBank™ Terms & Conditions")
    assert "Artificial Intelligence Features (Fortune – ManifestBank™ Teller)" in data["termsText"]
    assert data["privacyText"].startswith("ManifestBank™ Privacy Policy")
    assert "Artificial Intelligence Processing (Fortune – Teller)" in data["privacyText"]
    assert data["termsHash"]
    assert data["privacyHash"]


@pytest.mark.asyncio
async def test_legal_accept_updates_consent_versions(client):
    register = await client.post(
        "/auth/register",
        json={
            "email": "legal@test.com",
            "password": "abc12345",
            "username": "legaluser",
            "accept_terms": True,
        },
    )
    assert register.status_code == 200

    login = await client.post(
        "/auth/login",
        json={"identifier": "legal@test.com", "password": "abc12345"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    before = await client.get("/legal/consent", headers=headers)
    assert before.status_code == 200
    before_data = before.json()
    assert before_data["termsAccepted"] is True
    assert before_data["privacyAccepted"] is True
    assert before_data["needsReaccept"] is False

    accept = await client.post("/legal/accept", headers=headers)
    assert accept.status_code == 200
    accept_data = accept.json()
    assert accept_data["status"] == "accepted"
    assert accept_data["termsAccepted"] is True
    assert accept_data["privacyAccepted"] is True

    after = await client.get("/legal/consent", headers=headers)
    assert after.status_code == 200
    after_data = after.json()
    assert after_data["termsAccepted"] is True
    assert after_data["privacyAccepted"] is True
    assert after_data["needsReaccept"] is False
    assert after_data["termsVersion"] == after_data["termsCurrentVersion"]
    assert after_data["privacyVersion"] == after_data["privacyCurrentVersion"]
