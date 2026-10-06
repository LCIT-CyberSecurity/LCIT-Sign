"""People from outside the company: added by e-mail address, told how to sign in, recognised on
their first sign-in, never touched by a directory sync."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_auth_flow import login_as
from test_campaign_changes import prepared_doc
from test_campaigns import get_user_id, setup_campaign_fixture
from test_signer_roles import new_campaign

from lcit_sign.models.mail import Notification
from lcit_sign.models.user import User
from lcit_sign.services.signing_mail import to_sign_message

URL = "/api/campaigns/_meta/externals"


def test_an_operator_adds_someone_from_outside_by_their_address(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    created = operator.post(
        URL,
        json={
            "email": "  Jean.Client@Partenaire.COM ",
            "given_name": "Jean",
            "family_name": "Client",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["email"] == "jean.client@partenaire.com" and body["external"] is True
    assert body["existing"] is False and body["display_name"] == "Jean Client"

    # He is on the list of people that can be asked, marked as outside, and a signer only.
    listed = {u["email"]: u for u in operator.get("/api/campaigns/_meta/users").json()}
    assert listed["jean.client@partenaire.com"]["external"] is True
    users = {u["email"]: u for u in admin.get("/api/admin/users").json()}
    assert users["jean.client@partenaire.com"]["external"] is True
    assert users["jean.client@partenaire.com"]["roles"] == ["SIGNER"]

    # The same address again gives the same person; nobody is duplicated or changed.
    again = operator.post(URL, json={"email": "jean.client@partenaire.com", "given_name": "Autre"})
    assert again.json()["id"] == body["id"] and again.json()["existing"] is True
    assert admin.get("/api/admin/users").json().count(users["jean.client@partenaire.com"]) == 1
    # An employee is reused as what they are, not turned into an outsider.
    employee = operator.post(
        URL, json={"email": users[next(e for e in users if e.startswith("erwan"))]["email"]}
    )
    assert employee.json()["existing"] is True and employee.json()["external"] is False


def test_the_address_is_checked_and_only_staff_can_add_people(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    assert operator.post(URL, json={"email": "pas une adresse"}).status_code == 422
    assert operator.post(URL, json={"email": "a@b"}).status_code == 422
    assert signer.post(URL, json={"email": "x@y.fr"}).status_code == 403
    assert TestClient(app).post(URL, json={"email": "x@y.fr"}).status_code == 401
    # Someone an administrator switched off cannot be brought back through the side door.
    erwan = get_user_id(signer)
    admin.patch(f"/api/admin/users/{erwan}", json={"active": False})
    email = next(u["email"] for u in admin.get("/api/admin/users").json() if u["id"] == erwan)
    assert operator.post(URL, json={"email": email}).status_code == 409


def test_they_are_asked_like_anyone_and_told_how_to_sign_in(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    outsider = operator.post(
        URL, json={"email": "jean@partenaire.com", "given_name": "Jean"}
    ).json()
    campaign = new_campaign(operator, prepared_doc(operator, "Contrat"))
    launched = operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"user_ids": [outsider["id"], get_user_id(signer)]},
    )
    assert launched.status_code == 200, launched.text

    with app.state.session_factory() as db:
        bodies = {
            n.recipient_email: n.body_text
            for n in db.execute(select(Notification)).scalars()
            if n.subject.startswith("Document à signer")
        }
    outside = bodies["jean@partenaire.com"]
    assert "Vous n'avez aucun compte à créer" in outside and "jean@partenaire.com" in outside
    assert "Microsoft ou Google" in outside
    inside = next(body for email, body in bodies.items() if email != "jean@partenaire.com")
    assert "aucun compte à créer" not in inside


def test_the_message_says_why_it_is_their_turn_when_someone_signed_first():
    person = User(display_name="Jean", email="jean@partenaire.com", external=True)
    subject, body = to_sign_message(
        person,
        title="PSSI",
        campaign_name="Politiques",
        public_base_url="https://sign.test",
        signed_by="Rita Rssi",
    )
    assert subject == "Document à signer : PSSI"
    assert "Rita Rssi a signé" in body and "à votre tour" in body and "https://sign.test" in body


def test_on_first_sign_in_they_become_the_person_who_was_added(tmp_path, mock_oidc_base_url):
    """Fatima signs in through the mock SSO with the address the operator typed."""
    app, admin, operator, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    added = operator.post(URL, json={"email": "fatima.benali@lcit-test.local"}).json()
    campaign = new_campaign(operator, prepared_doc(operator, "Contrat"))
    operator.post(f"/api/campaigns/{campaign['id']}/launch", json={"user_ids": [added["id"]]})

    fatima = TestClient(app)
    login_as(fatima, mock_oidc_base_url, sub="u-consultants-1")
    me = fatima.get("/api/auth/me").json()
    assert me["id"] == added["id"] and me["roles"] == ["SIGNER"]
    # What was asked of her is waiting for her, and nothing of the operators' side is open.
    assert [a["document_title"] for a in fatima.get("/api/me/assignments").json()] == ["Contrat"]
    assert fatima.get("/api/campaigns").status_code == 403
    assert fatima.get("/api/admin/users").status_code == 403


def test_a_directory_sync_leaves_outsiders_alone(tmp_path, mock_oidc_base_url):
    app, admin, operator, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    added = operator.post(URL, json={"email": "jean@partenaire.com"}).json()
    assert admin.post("/api/admin/directory/sync?source=local").json()["status"] == "SUCCESS"
    users = {u["id"]: u for u in admin.get("/api/admin/users").json()}
    assert users[added["id"]]["active"] is True and users[added["id"]]["external"] is True
