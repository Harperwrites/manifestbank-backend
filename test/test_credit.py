import pytest

from app.models.credit import CreditAction, CreditTodo


@pytest.mark.asyncio
async def test_credit_summary_bureau_and_report_load(client, auth_helper):
    login = await auth_helper(client, "credit1@test.com", "pass", "creditone")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    summary = await client.get("/credit/summary?days=30", headers=headers)
    actions = await client.get("/credit/actions", headers=headers)
    bureau = await client.get("/credit/bureau/iab?days=30", headers=headers)
    report = await client.get("/credit/report", headers=headers)

    assert summary.status_code == 200
    assert actions.status_code == 200
    assert bureau.status_code == 200
    assert report.status_code == 200

    summary_body = summary.json()
    assert set(summary_body["scores"].keys()) == {"composite", "iab", "emotional", "ctb"}
    assert summary_body["daily_cap"] == 5
    assert isinstance(summary_body["trend_7d"], list)

    bureau_body = bureau.json()
    assert bureau_body["bureau"] == "IAB"
    assert bureau_body["days"] == 30
    assert len(bureau_body["drivers"]) == 2

    assert isinstance(actions.json(), list)
    assert any(item["action_type"] == "daily_login" for item in report.json()["items"])


@pytest.mark.asyncio
async def test_credit_todo_is_idempotent_and_removable(client, auth_helper, db):
    login = await auth_helper(client, "credit2@test.com", "pass", "credittwo")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    await client.get("/credit/actions", headers=headers)
    action = db.query(CreditAction).filter(CreditAction.action_type == "journal_entry").first()
    assert action is not None

    first = await client.post("/credit/todos", json={"action_id": action.id}, headers=headers)
    second = await client.post("/credit/todos", json={"action_id": action.id}, headers=headers)
    listing = await client.get("/credit/todos", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert any(item["id"] == first.json()["id"] and item["status"] == "open" for item in listing.json())

    deleted = await client.delete(f"/credit/todos/{first.json()['id']}", headers=headers)
    after_delete = await client.get("/credit/todos", headers=headers)

    assert deleted.status_code == 200
    assert all(item["id"] != first.json()["id"] for item in after_delete.json())


@pytest.mark.asyncio
async def test_credit_todo_pin_requires_signature_membership(client, auth_helper, db):
    login = await auth_helper(client, "creditpinfree@test.com", "pass", "creditpinfree", premium=False, verified=True)
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    await client.get("/credit/actions", headers=headers)
    action = db.query(CreditAction).filter(CreditAction.action_type == "journal_entry").first()
    assert action is not None

    pinned = await client.post("/credit/todos", json={"action_id": action.id}, headers=headers)

    assert pinned.status_code == 403
    assert pinned.json()["detail"] == "ManifestBank™ Signature required to pin credit actions."


@pytest.mark.asyncio
async def test_credit_auto_completion_flows_into_report_and_closes_todo(client, auth_helper, db):
    login = await auth_helper(client, "credit3@test.com", "pass", "creditthree")
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    await client.get("/credit/actions", headers=headers)
    action = db.query(CreditAction).filter(CreditAction.action_type == "wealth_target_update").first()
    assert action is not None

    pinned = await client.post("/credit/todos", json={"action_id": action.id}, headers=headers)
    assert pinned.status_code == 200

    updated = await client.patch("/users/wealth-target", json={"wealth_target_usd": 250000}, headers=headers)
    assert updated.status_code == 200

    todo_rows = db.query(CreditTodo).filter(CreditTodo.action_type == "wealth_target_update").all()
    assert todo_rows
    assert all(todo.status == "completed" for todo in todo_rows)

    report = await client.get("/credit/report", headers=headers)
    assert report.status_code == 200
    assert any(item["action_type"] == "wealth_target_update" for item in report.json()["items"])

    summary = await client.get("/credit/summary?days=7", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["daily_used"] >= 1


@pytest.mark.asyncio
async def test_credit_actions_complete_is_compat_only_and_respects_daily_cap(client, auth_helper, db):
    login = await auth_helper(
        client,
        "credit4@test.com",
        "pass",
        "creditfour",
        premium=False,
        verified=True,
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    await client.get("/credit/actions", headers=headers)
    actions = (
        db.query(CreditAction)
        .filter(CreditAction.action_type.in_(["journal_entry", "affirmation_save", "wealth_target_update"]))
        .order_by(CreditAction.id.asc())
        .limit(3)
        .all()
    )
    assert len(actions) == 3

    first = await client.post("/credit/actions/complete", json={"action_id": actions[0].id}, headers=headers)
    second = await client.post("/credit/actions/complete", json={"action_id": actions[1].id}, headers=headers)
    third = await client.post("/credit/actions/complete", json={"action_id": actions[2].id}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert third.status_code == 429

    todo_rows = db.query(CreditTodo).filter(CreditTodo.action_type == actions[0].action_type).all()
    assert todo_rows == []

    report = await client.get("/credit/report", headers=headers)
    assert report.status_code == 200
    report_items = report.json()["items"]
    assert len(report_items) == 2
    assert any(item["action_type"] == "daily_login" for item in report_items)
    assert any(item["action_type"] == actions[0].action_type for item in report_items)


@pytest.mark.asyncio
async def test_credit_daily_login_endpoint_is_idempotent_and_reports_points(client, auth_helper):
    premium_login = await auth_helper(client, "credit5@test.com", "pass", "creditfive", premium=True, verified=True)
    premium_token = premium_login.json()["access_token"]
    premium_headers = {"Authorization": f"Bearer {premium_token}"}

    first = await client.post("/credit/daily-login", headers=premium_headers)
    second = await client.post("/credit/daily-login", headers=premium_headers)
    report = await client.get("/credit/report", headers=premium_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    # Login already awards the user's daily login credit.
    assert first.json() == {"awarded": False, "points": 0}
    assert second.json() == {"awarded": False, "points": 0}
    assert report.status_code == 200
    assert len([item for item in report.json()["items"] if item["action_type"] == "daily_login"]) == 1

    free_login = await auth_helper(client, "credit6@test.com", "pass", "creditsix", premium=False, verified=True)
    free_token = free_login.json()["access_token"]
    free_headers = {"Authorization": f"Bearer {free_token}"}

    free_daily = await client.post("/credit/daily-login", headers=free_headers)

    assert free_daily.status_code == 200
    assert free_daily.json() == {"awarded": False, "points": 0}
