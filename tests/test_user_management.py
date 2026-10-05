from __future__ import annotations

from sqlalchemy import select
from test_auth_flow import login_as
from test_campaigns import (
    create_and_launch_campaign,
    get_user_id,
    publish_a_document,
    setup_campaign_fixture,
)
from test_directory import sync_directory

from lcit_sign.models.user import User


def test_an_admin_adds_someone_by_email_and_sso_adopts_that_entry(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    created = admin.post(
        "/api/admin/users",
        json={
            "email": "Fatima.Benali@LCIT-test.local",
            "given_name": "Fatima",
            "family_name": "Benali",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["email"] == "fatima.benali@lcit-test.local" and body["source"] == "manual"
    assert body["roles"] == ["SIGNER"] and body["can_delete"] is True
    duplicate = admin.post("/api/admin/users", json={"email": "fatima.benali@lcit-test.local"})
    assert duplicate.status_code == 409
    assert admin.post("/api/admin/users", json={"email": "not-an-address"}).status_code == 422

    # She can already be targeted by a campaign, before she ever signs in...
    _, version_id = publish_a_document(operator)
    campaign = create_and_launch_campaign(operator, version_id, [body["id"]])
    assert campaign["assignment_counts"]["PENDING"] == 1

    # ... and her first SSO login lands on the SAME entry: no duplicate, same roles.
    fatima = login_as(__import__("fastapi.testclient").testclient.TestClient(app),
                      mock_oidc_base_url, sub="u-consultants-1")
    assert fatima.status_code in (302, 307)
    with app.state.session_factory() as db:
        rows = db.execute(
            select(User).where(User.email == "fatima.benali@lcit-test.local")
        ).scalars().all()
        assert len(rows) == 1 and rows[0].id.hex == body["id"].replace("-", "")
        assert rows[0].issuer != "directory:manual" and rows[0].last_login_at is not None


def test_disabling_ends_sessions_blocks_login_and_survives_a_sync(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    sync_directory(admin)
    erwan = get_user_id(signer1)
    assert signer1.get("/api/auth/me").status_code == 200

    off = admin.patch(f"/api/admin/users/{erwan}", json={"active": False})
    assert off.status_code == 200 and off.json()["active"] is False
    assert signer1.get("/api/auth/me").status_code == 401  # the session ended at once

    # The directory still lists him: a sync must not switch him back on.
    sync_directory(admin)
    row = next(u for u in admin.get("/api/admin/users").json() if u["id"] == erwan)
    assert row["active"] is False and row["manually_disabled"] is True

    # Signing in again is refused, with the reason.
    from fastapi.testclient import TestClient

    again = TestClient(app)
    refused = login_as(again, mock_oidc_base_url, sub="u-it-1")
    assert refused.status_code == 403

    on = admin.patch(f"/api/admin/users/{erwan}", json={"active": True})
    assert on.json()["active"] is True and on.json()["manually_disabled"] is False


def test_nobody_can_lock_the_last_administrator_out(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    me = admin.get("/api/auth/me").json()["id"]
    assert admin.patch(f"/api/admin/users/{me}", json={"active": False}).status_code == 409
    assert admin.delete(f"/api/admin/users/{me}").status_code == 409


def test_someone_with_history_is_disabled_never_deleted(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    create_and_launch_campaign(operator, version_id, [get_user_id(signer1)])
    signer1.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})

    erwan = next(u for u in admin.get("/api/admin/users").json() if u["id"] == get_user_id(signer1))
    assert erwan["can_delete"] is False
    refused = admin.delete(f"/api/admin/users/{erwan['id']}")
    assert refused.status_code == 409 and "Désactivez" in refused.text


def test_a_user_with_no_trace_is_deleted_for_good_but_directory_people_are_not(
    tmp_path, mock_oidc_base_url
):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    manual = admin.post("/api/admin/users", json={"email": "temporaire@lcit-test.local"}).json()
    assert admin.delete(f"/api/admin/users/{manual['id']}").status_code == 200
    remaining = admin.get("/api/admin/users").json()
    assert all(u["email"] != "temporaire@lcit-test.local" for u in remaining)

    sync_directory(admin)
    someone = next(u for u in admin.get("/api/admin/users").json() if u["source"] == "local")
    assert someone["can_delete"] is False  # it would simply come back at the next sync
    assert "local" in " ".join(someone["delete_blockers"])


def test_only_administrators_manage_users(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    target = get_user_id(signer2)
    assert operator.post("/api/admin/users", json={"email": "x@y.zz"}).status_code == 403
    assert operator.patch(f"/api/admin/users/{target}", json={"active": False}).status_code == 403
    assert operator.delete(f"/api/admin/users/{target}").status_code == 403
