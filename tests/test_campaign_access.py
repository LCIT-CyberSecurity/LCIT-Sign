"""Who sees a campaign and what is inside it: owner and preparers read the content, an operator
supervises every campaign without reading what is confidential, an administrator can do all, and
a preparer of another campaign sees nothing of it. All enforced by the API, not by the buttons."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_auth_flow import login_as, make_app
from test_campaigns import TEST_MASTER_KEY
from test_prepared_fields import element, upload

from lcit_sign import models  # noqa: F401 - registers tables
from lcit_sign.database import Base
from lcit_sign.models.audit import AuditEvent
from lcit_sign.models.campaign import Campaign, CampaignPreparer


@dataclass
class World:
    app: object
    admin: TestClient
    rh: TestClient  # owner of the HR campaign (a plain SIGNER)
    rh2: TestClient  # the colleague an operator makes preparer of it (a plain SIGNER)
    legal: TestClient  # owner of the legal campaign (a plain SIGNER)
    operator: TestClient  # business administrator (OPERATOR)
    bob: TestClient  # an ordinary person: a SIGNER, asked to sign both campaigns
    ghost: TestClient  # someone whose SIGNER role an administrator took away
    ids: dict[str, str]
    hr: str = ""
    hr_version: str = ""
    law: str = ""
    law_version: str = ""


def build(tmp_path, oidc) -> World:
    app = make_app(tmp_path, oidc, master_key=TEST_MASTER_KEY)
    admin = TestClient(app)
    admin.__enter__()
    Base.metadata.create_all(app.state.engine)
    login_as(admin, oidc, sub="u-direction-1")  # the bootstrap administrator
    ids: dict[str, str] = {}

    def person(name: str, sub: str, *roles: str) -> TestClient:
        client = TestClient(app)
        login_as(client, oidc, sub=sub)
        ids[name] = client.get("/api/auth/me").json()["id"]
        for role in roles:
            granted = admin.post(f"/api/admin/users/{ids[name]}/roles", json={"role": role})
            assert granted.status_code == 201
        return client

    world = World(
        app=app, admin=admin,
        rh=person("rh", "u-rh-1"),
        rh2=person("rh2", "u-compta-1"),
        legal=person("legal", "u-sales-1"),
        operator=person("operator", "u-consultants-1", "OPERATOR"),
        bob=person("bob", "u-it-1"),
        ghost=person("ghost", "u-compta-2"),
        ids=ids,
    )
    assert admin.delete(f"/api/admin/users/{ids['ghost']}/roles/SIGNER").status_code == 200
    world.hr, world.hr_version = campaign_for(world.rh, ids["bob"], "Entretiens RH 2027")
    world.law, world.law_version = campaign_for(world.legal, ids["bob"], "NDA Juridique")
    return world


def campaign_for(owner: TestClient, signer_id: str, name: str) -> tuple[str, str]:
    """A published document with a signature element, and a launched campaign for `signer_id`."""
    version = upload(owner, title=f"Doc {name}", pages=1)
    assert owner.put(f"/api/documents/versions/{version}/fields", json={
        "fields": [element("SIGNATURE", role=1, y=0.7)]}).status_code == 200
    assert owner.post(f"/api/documents/versions/{version}/publish").status_code == 200
    campaign = owner.post("/api/campaigns", json={"name": name})
    assert campaign.status_code == 201, campaign.text
    cid = campaign.json()["id"]
    assert owner.post(f"/api/campaigns/{cid}/documents", json={"document_version_id": version}
                      ).status_code == 201
    launched = owner.post(f"/api/campaigns/{cid}/launch", json={"user_ids": [signer_id]})
    assert launched.status_code == 200, launched.text
    return cid, version


def sign(client: TestClient, version: str, campaign: str) -> str:
    done = client.post(f"/api/documents/versions/{version}/sign",
                       json={"consent": True, "campaign_id": campaign})
    assert done.status_code == 201, done.text
    return done.json()["id"]


# --- who can start a campaign ------------------------------------------------------------------


def test_a_signer_starts_and_owns_a_campaign_someone_without_the_role_cannot(
    tmp_path, mock_oidc_base_url
):
    w = build(tmp_path, mock_oidc_base_url)
    assert w.ghost.post("/api/campaigns", json={"name": "X"}).status_code == 403
    assert w.ghost.get("/api/campaigns").status_code == 403
    own = w.bob.post("/api/campaigns", json={"name": "Celle de Bob"})
    assert own.status_code == 201
    assert own.json()["owner"]["id"] == w.ids["bob"]
    # …and sees only that one, never the HR or legal campaigns he was merely asked to sign.
    assert [c["name"] for c in w.bob.get("/api/campaigns").json()] == ["Celle de Bob"]
    shown = w.rh.get(f"/api/campaigns/{w.hr}").json()
    assert shown["owner"]["id"] == w.ids["rh"] and shown["created_by"]["id"] == w.ids["rh"]
    assert shown["access"] == {"operate": True, "content": True}


# --- preparers see their own campaigns, and only those -----------------------------------------


def test_a_preparer_sees_their_campaign_and_not_another_teams(tmp_path, mock_oidc_base_url):
    w = build(tmp_path, mock_oidc_base_url)
    assert [c["id"] for c in w.rh.get("/api/campaigns").json()] == [w.hr]
    assert [c["id"] for c in w.legal.get("/api/campaigns").json()] == [w.law]
    # Straight to the API, whatever the interface hides: the other team's campaign does not exist.
    for call in (
        w.rh.get(f"/api/campaigns/{w.law}"),
        w.rh.get(f"/api/campaigns/{w.law}/assignments"),
        w.rh.post(f"/api/campaigns/{w.law}/remind"),
        w.rh.get(f"/api/campaigns/{w.law}/reports"),
        w.rh.post(f"/api/campaigns/{w.law}/cancel"),
        w.rh.put(f"/api/campaigns/{w.law}/owner", json={"user_id": w.ids["rh"]}),
    ):
        assert call.status_code == 404, call.request.url
    # Nor its documents: not the content, not the elements, not the pages.
    for url in (
        f"/api/documents/versions/{w.law_version}/content",
        f"/api/documents/versions/{w.law_version}/fields",
        f"/api/documents/versions/{w.law_version}/pages",
    ):
        assert w.rh.get(url).status_code == 403, url
    assert w.rh.post(f"/api/documents/versions/{w.law_version}/archive").status_code == 403
    law_title = "Doc NDA Juridique"
    assert law_title not in w.rh.get("/api/documents").text
    assert w.rh.get("/api/campaigns/_meta/dashboard").json()["campaigns"]["active"] == 1


def test_the_signed_pdf_of_a_campaign_is_not_readable_by_another_preparer(
    tmp_path, mock_oidc_base_url
):
    w = build(tmp_path, mock_oidc_base_url)
    signature = sign(w.bob, w.hr_version, w.hr)
    for url in (
        f"/api/signatures/{signature}/signed-pdf",
        f"/api/signatures/{signature}/certificate",
        f"/api/signatures/{signature}/evidence",
        f"/api/signatures/{signature}",
    ):
        assert w.legal.get(url).status_code == 403, url
        assert w.rh.get(url).status_code == 200, url  # its owner
        assert w.admin.get(url).status_code == 200, url
    zipped = w.legal.get("/api/signed/export.zip")
    assert zipped.status_code == 404  # nothing of theirs is signed yet
    assert w.legal.get("/api/signed/documents").json()["signed"] == []
    assert len(w.rh.get("/api/signed/documents").json()["signed"]) == 1
    assert w.rh.get("/api/signed/export.zip").status_code == 200


# --- the operator supervises, and does not read ------------------------------------------------


def test_an_operator_sees_every_campaign_and_its_progress_but_not_its_content(
    tmp_path, mock_oidc_base_url
):
    w = build(tmp_path, mock_oidc_base_url)
    signature = sign(w.bob, w.hr_version, w.hr)
    names = {c["name"]: c for c in w.operator.get("/api/campaigns").json()}
    assert set(names) == {"Entretiens RH 2027", "NDA Juridique"}
    hr = names["Entretiens RH 2027"]
    assert hr["owner"]["id"] == w.ids["rh"] and hr["access"] == {"operate": True, "content": False}
    assert w.operator.get(f"/api/campaigns/{w.hr}/assignments").status_code == 200  # progress
    assert w.operator.get(f"/api/signatures/{signature}").status_code == 200  # who signed, when
    assert w.operator.get(f"/api/signatures/{signature}/chain").status_code == 200
    assert w.operator.get("/api/campaigns/_meta/dashboard").json()["campaigns"]["active"] == 2

    # The confidential content stays closed, even to a direct API call.
    for url in (
        f"/api/signatures/{signature}/signed-pdf",
        f"/api/signatures/{signature}/certificate",
        f"/api/signatures/{signature}/evidence",
        f"/api/documents/versions/{w.hr_version}/content",
        f"/api/documents/versions/{w.hr_version}/fields",
        f"/api/campaigns/{w.hr}/reports",
    ):
        assert w.operator.get(url).status_code == 403, url
    assert w.operator.post(f"/api/campaigns/{w.hr}/reports").status_code == 403
    launch = w.operator.post(f"/api/campaigns/{w.hr}/launch", json={"user_ids": []})
    assert launch.status_code == 403
    assert w.operator.get("/api/signed/export.zip").status_code == 404
    assert w.operator.get("/api/signed/documents").json()["signed"] == []
    # The library shows that the document exists, nothing more.
    assert "Doc Entretiens RH 2027" in w.operator.get("/api/documents").text


def test_an_operator_made_a_preparer_can_then_read_it_and_it_leaves_a_trace(
    tmp_path, mock_oidc_base_url
):
    w = build(tmp_path, mock_oidc_base_url)
    signature = sign(w.bob, w.hr_version, w.hr)
    assert w.operator.get(f"/api/signatures/{signature}/signed-pdf").status_code == 403
    added = w.operator.post(f"/api/campaigns/{w.hr}/preparers", json={"user_id": w.ids["operator"]})
    assert added.status_code == 201, added.text
    assert added.json()["access"]["content"] is True
    assert w.operator.get(f"/api/signatures/{signature}/signed-pdf").status_code == 200
    assert w.operator.get(f"/api/documents/versions/{w.hr_version}/content").status_code == 200
    with w.app.state.session_factory() as db:
        event = db.execute(
            select(AuditEvent).where(AuditEvent.action == "CAMPAIGN_PREPARER_ADDED")
        ).scalar_one()
        assert event.actor_id is not None and w.ids["operator"] in str(event.metadata_json)
    # The other team's campaign is still closed to them.
    assert w.operator.get(f"/api/signatures/{sign(w.bob, w.law_version, w.law)}/signed-pdf"
                          ).status_code == 403


# --- an absence: add a colleague, hand over, keep the history ----------------------------------


def test_an_operator_hands_a_campaign_over_and_the_history_stays(tmp_path, mock_oidc_base_url):
    w = build(tmp_path, mock_oidc_base_url)
    assert w.rh2.get(f"/api/campaigns/{w.hr}").status_code == 404
    assert w.operator.post(f"/api/campaigns/{w.hr}/preparers", json={"user_id": w.ids["rh2"]}
                           ).status_code == 201
    assert w.rh2.get(f"/api/campaigns/{w.hr}").json()["access"]["content"] is True

    moved = w.operator.put(f"/api/campaigns/{w.hr}/owner", json={"user_id": w.ids["rh2"]})
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["owner"]["id"] == w.ids["rh2"]
    assert body["created_by"]["id"] == w.ids["rh"]  # who started it never changes
    # The previous owner stays a preparer until someone removes them; the new owner needs no row.
    assert [p["id"] for p in body["preparers"]] == [w.ids["rh"]]
    assert w.rh.get(f"/api/campaigns/{w.hr}").json()["access"]["content"] is True
    with w.app.state.session_factory() as db:
        assert db.execute(select(CampaignPreparer).where(
            CampaignPreparer.user_id == uuid.UUID(w.ids["rh2"]))).first() is None
        assert db.execute(select(AuditEvent).where(
            AuditEvent.action == "CAMPAIGN_OWNER_CHANGED")).scalar_one()

    # The owner is not removed as a preparer; the old one can be, and loses sight of it.
    assert w.operator.delete(f"/api/campaigns/{w.hr}/preparers/{w.ids['rh2']}").status_code == 409
    assert w.operator.delete(f"/api/campaigns/{w.hr}/preparers/{w.ids['rh']}").status_code == 200
    assert w.rh.get(f"/api/campaigns/{w.hr}").status_code == 404


def test_only_people_who_can_prepare_become_owner_or_preparer(tmp_path, mock_oidc_base_url):
    w = build(tmp_path, mock_oidc_base_url)
    for call in (
        w.operator.post(f"/api/campaigns/{w.hr}/preparers", json={"user_id": w.ids["ghost"]}),
        w.operator.put(f"/api/campaigns/{w.hr}/owner", json={"user_id": w.ids["ghost"]}),
    ):
        assert call.status_code == 422 and "Signataire" in call.json()["detail"]
    # Bob is asked to sign it, which gives no say on how it runs.
    assert w.bob.post(f"/api/campaigns/{w.hr}/preparers", json={"user_id": w.ids["rh2"]}
                      ).status_code in (403, 404)
    # Someone who already runs it is not added twice.
    assert w.operator.post(f"/api/campaigns/{w.hr}/preparers", json={"user_id": w.ids["rh"]}
                           ).status_code == 409


# --- the administrator, and the campaigns that already existed ---------------------------------


def test_an_administrator_keeps_the_full_access(tmp_path, mock_oidc_base_url):
    w = build(tmp_path, mock_oidc_base_url)
    signature = sign(w.bob, w.hr_version, w.hr)
    assert {c["name"] for c in w.admin.get("/api/campaigns").json()} == {
        "Entretiens RH 2027", "NDA Juridique"}
    assert w.admin.get(f"/api/campaigns/{w.hr}").json()["access"]["content"] is True
    assert w.admin.get(f"/api/signatures/{signature}/signed-pdf").status_code == 200
    assert w.admin.get(f"/api/documents/versions/{w.hr_version}/content").status_code == 200
    assert w.admin.get(f"/api/campaigns/{w.hr}/reports").status_code == 200


def test_a_campaign_from_before_owners_existed_stays_with_its_creator(tmp_path, mock_oidc_base_url):
    w = build(tmp_path, mock_oidc_base_url)
    with w.app.state.session_factory() as db:
        campaign = db.get(Campaign, uuid.UUID(w.hr))
        assert campaign is not None
        campaign.owner_id = None  # as the rows of an older database
        db.commit()
    assert w.rh.get(f"/api/campaigns/{w.hr}").json()["access"]["content"] is True
    assert w.rh.get(f"/api/campaigns/{w.hr}").json()["owner"]["id"] == w.ids["rh"]
    assert w.legal.get(f"/api/campaigns/{w.hr}").status_code == 404


def test_the_person_asked_to_sign_needs_the_signer_role_and_a_stranger_still_cannot(
    tmp_path, mock_oidc_base_url
):
    w = build(tmp_path, mock_oidc_base_url)
    assert w.bob.get("/api/auth/me").json()["roles"] == ["SIGNER"]  # the default
    signature = sign(w.bob, w.hr_version, w.hr)
    assert w.bob.get(f"/api/signatures/{signature}/signed-pdf").status_code == 200  # their own
    # Someone not asked, with no SIGNER role, cannot sign a published document of their own accord.
    stranger = w.admin.post("/api/admin/users", json={"email": "z@corp.test"}).json()
    assert stranger["roles"] == ["SIGNER"]  # signing is the default
    legal_id = w.legal.get("/api/auth/me").json()["id"]
    assert w.admin.delete(f"/api/admin/users/{legal_id}/roles/SIGNER").status_code == 200
    assert w.legal.post(f"/api/documents/versions/{w.hr_version}/sign",
                        json={"consent": True}).status_code == 403
