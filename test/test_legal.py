import pytest

from app.models.legal_acceptance import LegalAcceptance


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
    assert before_data["hasPriorAcceptance"] is True

    accept = await client.post("/legal/accept", headers=headers)
    assert accept.status_code == 200
    accept_data = accept.json()
    assert accept_data["status"] == "accepted"
    assert accept_data["termsAccepted"] is True
    assert accept_data["privacyAccepted"] is True
    assert accept_data["historyCount"] == 2

    after = await client.get("/legal/consent", headers=headers)
    assert after.status_code == 200
    after_data = after.json()
    assert after_data["termsAccepted"] is True
    assert after_data["privacyAccepted"] is True
    assert after_data["needsReaccept"] is False
    assert after_data["termsVersion"] == after_data["termsCurrentVersion"]
    assert after_data["privacyVersion"] == after_data["privacyCurrentVersion"]


@pytest.mark.asyncio
async def test_legal_consent_marks_existing_users_for_updated_copy(client, db):
    register = await client.post(
        "/auth/register",
        json={
            "email": "legacylegal@test.com",
            "password": "abc12345",
            "username": "legacylegal",
            "accept_terms": True,
        },
    )
    assert register.status_code == 200

    from app.models.user import User

    user = db.query(User).filter(User.email == "legacylegal@test.com").first()
    user.terms_version = "older-terms-version"
    user.privacy_version = "older-privacy-version"
    db.add(user)
    db.commit()

    login = await client.post(
        "/auth/login",
        json={"identifier": "legacylegal@test.com", "password": "abc12345"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    consent = await client.get("/legal/consent", headers=headers)
    assert consent.status_code == 200
    data = consent.json()
    assert data["termsAccepted"] is False
    assert data["privacyAccepted"] is False
    assert data["needsReaccept"] is True
    assert data["hasPriorAcceptance"] is True


@pytest.mark.asyncio
async def test_legal_acceptance_history_preserves_old_versions(client, db):
    register = await client.post(
        "/auth/register",
        json={
            "email": "historylegal@test.com",
            "password": "abc12345",
            "username": "historylegal",
            "accept_terms": True,
        },
    )
    assert register.status_code == 200

    from app.models.user import User
    from app.routes import legal as legal_routes

    user = db.query(User).filter(User.email == "historylegal@test.com").first()
    original_terms_version = user.terms_version
    original_privacy_version = user.privacy_version

    user.terms_version = "older-terms-version"
    user.privacy_version = "older-privacy-version"
    db.add(user)
    db.add(
        LegalAcceptance(
            user_id=user.id,
            document_type="terms",
            version="older-terms-version",
            accepted_at=user.terms_accepted_at,
        )
    )
    db.add(
        LegalAcceptance(
            user_id=user.id,
            document_type="privacy",
            version="older-privacy-version",
            accepted_at=user.privacy_accepted_at,
        )
    )
    db.commit()

    login = await client.post(
        "/auth/login",
        json={"identifier": "historylegal@test.com", "password": "abc12345"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    accept = await client.post("/legal/accept", headers=headers)
    assert accept.status_code == 200

    history = (
        db.query(LegalAcceptance)
        .filter(LegalAcceptance.user_id == user.id)
        .order_by(LegalAcceptance.document_type, LegalAcceptance.version)
        .all()
    )
    history_keys = {(row.document_type, row.version) for row in history}
    assert ("terms", "older-terms-version") in history_keys
    assert ("privacy", "older-privacy-version") in history_keys
    assert ("terms", legal_routes.TERMS_VERSION) in history_keys
    assert ("privacy", legal_routes.PRIVACY_VERSION) in history_keys
    assert ("terms", original_terms_version) in history_keys
    assert ("privacy", original_privacy_version) in history_keys
