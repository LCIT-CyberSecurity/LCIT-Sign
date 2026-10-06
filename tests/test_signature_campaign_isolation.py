"""A signature answers ONE campaign. When the same version is asked of the same person by two
campaigns, signing one never closes the other."""

from __future__ import annotations

from sqlalchemy import select
from test_campaigns import get_user_id, setup_campaign_fixture
from test_prepared_fields import element, upload

from lcit_sign.models.campaign import AssignmentStatus, SignatureAssignment
from lcit_sign.models.signature import Signature


def publish(operator) -> str:
    version_id = upload(operator, title="Charte", pages=1)
    assert operator.put(
        f"/api/documents/versions/{version_id}/fields",
        json={"fields": [element("SIGNATURE", role=1, y=0.7)]},
    ).status_code == 200
    assert operator.post(f"/api/documents/versions/{version_id}/publish").status_code == 200
    return version_id


def ask(operator, version_id: str, person: str, name: str) -> str:
    campaign = operator.post("/api/campaigns", json={"name": name}).json()
    operator.post(
        f"/api/campaigns/{campaign['id']}/documents", json={"document_version_id": version_id}
    )
    launched = operator.post(f"/api/campaigns/{campaign['id']}/launch", json={"user_ids": [person]})
    assert launched.status_code == 200, launched.text
    return campaign["id"]


def statuses(app) -> dict[str, str]:
    with app.state.session_factory() as db:
        return {
            str(a.campaign_id): a.status.value
            for a in db.execute(select(SignatureAssignment)).scalars()
        }


def signatures(app) -> list[Signature]:
    with app.state.session_factory() as db:
        return list(db.execute(select(Signature)).scalars())


def test_one_campaign_signs_as_before(tmp_path, mock_oidc_base_url):
    app, _, operator, signer, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    version_id = publish(operator)
    only = ask(operator, version_id, get_user_id(signer), "A")
    signed = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert signed.status_code == 201, signed.text
    assert statuses(app) == {only: "SIGNED"}
    assert [str(s.campaign_id) for s in signatures(app)] == [only]


def test_a_generic_signature_is_refused_when_two_campaigns_ask_the_same_version(
    tmp_path, mock_oidc_base_url
):
    app, _, operator, signer, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    version_id = publish(operator)
    person = get_user_id(signer)
    a = ask(operator, version_id, person, "A")
    b = ask(operator, version_id, person, "B")

    refused = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert refused.status_code == 409
    assert "plusieurs campagnes" in refused.json()["detail"]
    # Nothing was signed, nothing was closed.
    assert signatures(app) == []
    assert statuses(app) == {a: "PENDING", b: "PENDING"}


def test_signing_campaign_a_leaves_b_open_and_b_can_be_signed_later(tmp_path, mock_oidc_base_url):
    app, _, operator, signer, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    version_id = publish(operator)
    person = get_user_id(signer)
    a = ask(operator, version_id, person, "A")
    b = ask(operator, version_id, person, "B")

    signed_a = signer.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True, "campaign_id": a}
    )
    assert signed_a.status_code == 201, signed_a.text
    assert statuses(app) == {a: "SIGNED", b: "PENDING"}
    (only,) = signatures(app)
    assert str(only.campaign_id) == a
    assert signer.get(f"/api/signatures/{only.id}/evidence").json()["campaign_id"] == a
    assert signer.get(f"/api/signatures/{only.id}/verify").json()["valid"] is True

    # B is still theirs to sign: it is the only one left open, so no campaign has to be named.
    signed_b = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert signed_b.status_code == 201, signed_b.text
    assert statuses(app) == {a: "SIGNED", b: "SIGNED"}
    assert sorted(str(s.campaign_id) for s in signatures(app)) == sorted([a, b])


def test_a_campaign_that_does_not_ask_this_person_cannot_be_named(tmp_path, mock_oidc_base_url):
    app, _, operator, signer, other = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    version_id = publish(operator)
    mine = ask(operator, version_id, get_user_id(signer), "A")
    ask(operator, version_id, get_user_id(other), "B")
    others = operator.get("/api/campaigns").json()
    theirs = next(c["id"] for c in others if c["id"] != mine)
    refused = signer.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True, "campaign_id": theirs}
    )
    assert refused.status_code == 409
    assert signatures(app) == []


def test_sign_all_answers_only_its_own_campaign(tmp_path, mock_oidc_base_url):
    app, _, operator, signer, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    version_id = publish(operator)
    person = get_user_id(signer)
    a = ask(operator, version_id, person, "A")
    b = ask(operator, version_id, person, "B")
    done = signer.post(f"/api/sign-all/{a}", json={"consent": True, "shared": {}, "values": {}})
    assert done.status_code == 200, done.text
    assert statuses(app) == {a: "SIGNED", b: "PENDING"}
    (only,) = signatures(app)
    assert str(only.campaign_id) == a
