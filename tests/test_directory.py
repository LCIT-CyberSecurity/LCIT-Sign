from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_auth_flow import login_as, make_app
from test_campaigns import (
    create_campaign_with_document,
    get_user_id,
    publish_a_document,
    setup_campaign_fixture,
)

from lcit_sign import models  # noqa: F401 - registers tables on Base.metadata
from lcit_sign.database import Base
from lcit_sign.models.user import User

TEST_MASTER_KEY = "test-master-key-not-for-production-use"  # noqa: S105


def sync_directory(admin: TestClient) -> dict:
    response = admin.post("/api/admin/directory/sync")
    assert response.status_code == 200, response.text
    return response.json()


def find_group_id(admin: TestClient, name: str) -> str:
    groups = admin.get("/api/admin/directory/groups").json()
    matches = [g for g in groups if g["name"] == name]
    assert matches, f"group {name!r} not found in {groups}"
    return matches[0]["id"]


def test_sync_creates_groups_and_users(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url, crashtest=True
    )
    run = sync_directory(admin)
    assert run["status"] == "SUCCESS"
    assert run["groups_added"] == 6
    # admin/operator/signer1/signer2 already logged in via SSO before the
    # sync ran, so those 4 are reconciled (updated) rather than created.
    assert run["users_added"] == 20
    assert run["users_updated"] == 4

    groups = admin.get("/api/admin/directory/groups").json()
    assert len(groups) == 6
    assert sum(g["member_count"] for g in groups) == 24


def test_sync_is_idempotent(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url, crashtest=True
    )
    sync_directory(admin)
    second_run = sync_directory(admin)
    assert second_run["groups_added"] == 0
    assert second_run["groups_updated"] == 6
    assert second_run["users_added"] == 0
    assert second_run["users_updated"] == 24


def test_group_members_listing(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url, crashtest=True
    )
    sync_directory(admin)
    group_id = find_group_id(admin, "IT")
    members = admin.get(f"/api/admin/directory/groups/{group_id}/members").json()
    assert len(members) == 4
    assert {m["email"] for m in members} == {
        "erwan.petit@lcit-test.local",
        "sophie.michel@lcit-test.local",
        "thomas.caron@lcit-test.local",
        "valerie.andre@lcit-test.local",
    }


def test_non_admin_cannot_trigger_sync(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url, crashtest=True
    )
    response = operator.post("/api/admin/directory/sync")
    assert response.status_code == 403


def test_campaign_can_target_a_group(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url, crashtest=True
    )
    sync_directory(admin)
    group_id = find_group_id(admin, "IT")

    _, version_id = publish_a_document(operator)
    campaign = create_campaign_with_document(operator, version_id, "Campagne IT")
    launch = operator.post(
        f"/api/campaigns/{campaign['id']}/launch", json={"group_ids": [group_id]}
    )
    assert launch.status_code == 200, launch.text
    assert launch.json()["assignment_counts"]["PENDING"] == 4
    assert launch.json()["target_mode"] == "GROUPS"


def test_campaign_can_combine_group_and_extra_users(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url, crashtest=True
    )
    sync_directory(admin)
    group_id = find_group_id(admin, "IT")  # 4 members — signer1 (u-it-1) is one of them
    extra_user_id = get_user_id(operator)  # operator is u-sales-1, not in IT: a true addition

    _, version_id = publish_a_document(operator)
    campaign = create_campaign_with_document(operator, version_id, "Campagne mixte")
    launch = operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"group_ids": [group_id], "user_ids": [extra_user_id]},
    )
    assert launch.status_code == 200, launch.text
    assert launch.json()["assignment_counts"]["PENDING"] == 5
    assert launch.json()["target_mode"] == "GROUPS_AND_USERS"


def test_sso_login_reconciles_with_directory_provisioned_user(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY, crashtest=True)
    admin = TestClient(app)
    admin.__enter__()
    Base.metadata.create_all(app.state.engine)
    login_as(admin, mock_oidc_base_url, sub="u-direction-1")  # alice, bootstrap ADMIN

    db = app.state.session_factory()
    try:
        alice_rows_after_login = db.execute(
            select(User).where(User.email == "alice.martin@lcit-test.local")
        ).scalars().all()
        assert len(alice_rows_after_login) == 1
        alice_id_from_login = alice_rows_after_login[0].id
    finally:
        db.close()

    sync_directory(admin)

    db = app.state.session_factory()
    try:
        alice_rows_after_sync = db.execute(
            select(User).where(User.email == "alice.martin@lcit-test.local")
        ).scalars().all()
        # Sync must have reconciled onto the same row, not created a second one.
        assert len(alice_rows_after_sync) == 1
        assert alice_rows_after_sync[0].id == alice_id_from_login
        assert alice_rows_after_sync[0].issuer == mock_oidc_base_url
    finally:
        db.close()

    group_id = find_group_id(admin, "Direction")
    members = admin.get(f"/api/admin/directory/groups/{group_id}/members").json()
    assert str(alice_id_from_login) in {m["id"] for m in members}


def test_directory_provisioned_user_can_still_be_claimed_by_a_later_login(
    tmp_path, mock_oidc_base_url
):
    """The reverse order: sync runs first, creating a directory-only row,
    then the real person logs in via SSO and should adopt that same row.
    """
    app = make_app(tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY, crashtest=True)
    bootstrap_admin_client = TestClient(app)
    bootstrap_admin_client.__enter__()
    Base.metadata.create_all(app.state.engine)
    login_as(bootstrap_admin_client, mock_oidc_base_url, sub="u-direction-1")

    sync_directory(bootstrap_admin_client)

    db = app.state.session_factory()
    try:
        bob_before_login = db.execute(
            select(User).where(User.email == "bob.dupont@lcit-test.local")
        ).scalar_one()
        assert bob_before_login.issuer.startswith("directory:")
        bob_id = bob_before_login.id
    finally:
        db.close()

    bob_client = TestClient(app)
    login_as(bob_client, mock_oidc_base_url, sub="u-rh-1")

    db = app.state.session_factory()
    try:
        bob_rows = db.execute(
            select(User).where(User.email == "bob.dupont@lcit-test.local")
        ).scalars().all()
        assert len(bob_rows) == 1
        assert bob_rows[0].id == bob_id
        assert bob_rows[0].issuer == mock_oidc_base_url
    finally:
        db.close()
