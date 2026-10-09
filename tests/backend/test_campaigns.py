from __future__ import annotations

from fastapi.testclient import TestClient
from test_auth_flow import login_as, make_app
from test_documents import make_minimal_pdf_bytes

from lcit_sign import models  # noqa: F401 - registers tables on Base.metadata
from lcit_sign.database import Base

TEST_MASTER_KEY = "test-master-key-not-for-production-use"  # noqa: S105


def setup_campaign_fixture(tmp_path, mock_oidc_base_url, **overrides):
    """ADMIN (bootstrap), one OPERATOR, two SIGNERs, all logged in and
    role-assigned; returns (app, admin, operator, signer1, signer2).
    """
    app = make_app(tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY, **overrides)
    admin = TestClient(app)
    admin.__enter__()
    Base.metadata.create_all(app.state.engine)
    login_as(admin, mock_oidc_base_url, sub="u-direction-1")

    def make_user(sub: str, role: str) -> TestClient:
        client = TestClient(app)
        login_as(client, mock_oidc_base_url, sub=sub)
        user_id = client.get("/api/auth/me").json()["id"]
        grant = admin.post(f"/api/admin/users/{user_id}/roles", json={"role": role})
        assert grant.status_code == 201
        return client

    operator = make_user("u-sales-1", "OPERATOR")
    signer1 = make_user("u-it-1", "SIGNER")
    signer2 = make_user("u-rh-1", "SIGNER")

    return app, admin, operator, signer1, signer2


def publish_a_document(operator: TestClient):
    pdf_bytes = make_minimal_pdf_bytes()
    document = operator.post(
        "/api/documents",
        data={"title": "Charte informatique", "version_label": "1.0"},
        files={"file": ("charte.pdf", pdf_bytes, "application/pdf")},
    ).json()
    version_id = document["versions"][0]["id"]
    operator.post(f"/api/documents/versions/{version_id}/publish")
    return document, version_id


def create_campaign_with_document(operator: TestClient, version_id: str, name: str) -> dict:
    campaign = operator.post("/api/campaigns", json={"name": name}).json()
    operator.post(
        f"/api/campaigns/{campaign['id']}/documents", json={"document_version_id": version_id}
    )
    return campaign


def create_and_launch_campaign(operator: TestClient, version_id: str, user_ids: list[str]):
    campaign = create_campaign_with_document(operator, version_id, "Campagne 2026")
    launch = operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"user_ids": user_ids},
    )
    assert launch.status_code == 200, launch.text
    return launch.json()


def get_user_id(client: TestClient) -> str:
    return client.get("/api/auth/me").json()["id"]


def without_signer_role(admin: TestClient, client: TestClient) -> TestClient:
    """An administrator takes SIGNER away: the person keeps an account and no right at all."""
    taken = admin.delete(f"/api/admin/users/{get_user_id(client)}/roles/SIGNER")
    assert taken.status_code == 200 and taken.json()["roles"] == []
    return client


def test_launch_creates_pending_assignments_for_each_target(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)

    campaign = create_and_launch_campaign(
        operator, version_id, [get_user_id(signer1), get_user_id(signer2)]
    )
    assert campaign["status"] == "ACTIVE"
    assert campaign["assignment_counts"]["PENDING"] == 2

    assignments = operator.get(f"/api/campaigns/{campaign['id']}/assignments").json()
    assert len(assignments) == 2
    assert {a["status"] for a in assignments} == {"PENDING"}


def test_viewing_then_signing_updates_assignment_status(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    campaign = create_and_launch_campaign(
        operator, version_id, [get_user_id(signer1), get_user_id(signer2)]
    )

    view_response = signer1.get(f"/api/documents/versions/{version_id}/content")
    assert view_response.status_code == 200

    my_assignments = signer1.get("/api/me/assignments").json()
    assert my_assignments[0]["status"] == "VIEWED"

    sign_response = signer1.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    )
    assert sign_response.status_code == 201

    my_assignments = signer1.get("/api/me/assignments").json()
    assert my_assignments[0]["status"] == "SIGNED"
    assert my_assignments[0]["signed_at"] is not None

    detail = operator.get(f"/api/campaigns/{campaign['id']}").json()
    assert detail["assignment_counts"]["SIGNED"] == 1
    assert detail["assignment_counts"]["PENDING"] == 1


def test_signer_without_assignment_cannot_view_document(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    create_and_launch_campaign(operator, version_id, [get_user_id(signer1)])  # signer2 excluded

    response = signer2.get(f"/api/documents/versions/{version_id}/content")
    assert response.status_code == 403


def test_all_users_target_mode_includes_everyone_active(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)

    campaign = create_campaign_with_document(operator, version_id, "Tout le monde")
    launch = operator.post(
        f"/api/campaigns/{campaign['id']}/launch", json={"all_users": True}
    )
    assert launch.status_code == 200
    # admin + operator + signer1 + signer2 were all logged in, so all 4 exist as users.
    assert launch.json()["assignment_counts"]["PENDING"] == 4


def test_cannot_launch_an_empty_population(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    campaign = create_campaign_with_document(operator, version_id, "Vide")
    response = operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"user_ids": []},
    )
    assert response.status_code == 400


def test_cannot_launch_a_campaign_with_no_documents(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    campaign = operator.post("/api/campaigns", json={"name": "Sans document"}).json()
    response = operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"user_ids": [get_user_id(signer1)]},
    )
    assert response.status_code == 400


def test_cannot_relaunch_an_active_campaign(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    campaign = create_and_launch_campaign(operator, version_id, [get_user_id(signer1)])
    second_launch = operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"user_ids": [get_user_id(signer2)]},
    )
    assert second_launch.status_code == 409


def test_close_and_cancel_lifecycle(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    campaign = create_and_launch_campaign(operator, version_id, [get_user_id(signer1)])

    close_response = operator.post(f"/api/campaigns/{campaign['id']}/close")
    assert close_response.status_code == 200
    assert close_response.json()["status"] == "CLOSED"

    cancel_after_close = operator.post(f"/api/campaigns/{campaign['id']}/cancel")
    assert cancel_after_close.status_code == 409

    draft = operator.post("/api/campaigns", json={"name": "A annuler"}).json()
    cancel_draft = operator.post(f"/api/campaigns/{draft['id']}/cancel")
    assert cancel_draft.status_code == 200
    assert cancel_draft.json()["status"] == "CANCELLED"


def test_a_signer_prepares_campaigns_and_someone_without_the_role_cannot(
    tmp_path, mock_oidc_base_url
):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    assert signer1.post("/api/campaigns", json={"name": "Ma campagne"}).status_code == 201
    without_signer_role(admin, signer2)
    assert signer2.post("/api/campaigns", json={"name": "Interdit"}).status_code == 403


def test_unauthenticated_cannot_list_own_assignments(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)
        assert client.get("/api/me/assignments").status_code == 401
