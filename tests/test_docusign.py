"""Signing through DocuSign: the connection, the choice of method, the envelope of each signer,
and what comes back — all against the mock DocuSign of the test stack (no account, no network)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_campaigns import get_user_id, setup_campaign_fixture
from test_prepared_fields import element, upload

from lcit_sign.api import docusign as docusign_api
from lcit_sign.models.docusign import DocusignEnvelope
from lcit_sign.services.docusign import DocusignClient
from lcit_sign.services.docusign_flow import process_docusign

METHODS = "/api/campaigns/_meta/signature-methods"
MOCK_PATH = Path(__file__).resolve().parents[1] / "mock_docusign" / "app.py"


@pytest.fixture
def mock(tmp_path, monkeypatch):
    """The mock DocuSign, driven in-process: one HTTP client that answers for DocuSign."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("MOCK_DOCUSIGN_DATA", str(tmp_path / "docusign"))
    spec = importlib.util.spec_from_file_location("mock_docusign_app", MOCK_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.STORE = tmp_path / "docusign"
    client = TestClient(module.app)
    client.store = tmp_path / "docusign" / "envelopes.json"  # type: ignore[attr-defined]
    # Only the DocuSign module is given this client: the rest of the app keeps the real httpx.
    monkeypatch.setattr(docusign_api, "httpx", SimpleNamespace(Client=lambda **kw: client))
    return client


def work(app, mock) -> int:
    """One turn of the worker."""
    db = app.state.session_factory()
    try:
        return process_docusign(
            db, app.state.settings, app.state.storage,
            client_factory=lambda cfg: DocusignClient(mock, cfg),
        )
    finally:
        db.close()


def envelopes(app) -> list[DocusignEnvelope]:
    db = app.state.session_factory()
    try:
        return list(db.query(DocusignEnvelope).order_by(DocusignEnvelope.created_at))
    finally:
        db.close()


def prepare(operator, roles=(1,)) -> str:
    version_id = upload(operator, title="Charte", pages=1)
    fields = [element("SIGNATURE", role=r, y=0.2 + 0.2 * r) for r in roles]
    assert operator.put(
        f"/api/documents/versions/{version_id}/fields", json={"fields": fields}
    ).status_code == 200
    operator.post(f"/api/documents/versions/{version_id}/publish")
    return version_id


def draft(operator, version_id) -> str:
    campaign = operator.post("/api/campaigns", json={"name": "Charte 2026"}).json()
    operator.post(
        f"/api/campaigns/{campaign['id']}/documents", json={"document_version_id": version_id}
    )
    return campaign["id"]


def sign_in_the_mock(mock, envelope_id: str) -> None:
    assert mock.post(f"/sign/{envelope_id}", data={"action": "sign"}, follow_redirects=False
                     ).status_code == 303


# --- the connection --------------------------------------------------------------------------


def test_the_connection_is_kept_without_ever_showing_the_key(tmp_path, mock_oidc_base_url, mock):
    _, admin, operator, _, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    shown = admin.get("/api/admin/docusign").json()
    assert shown["configured"] is False and shown["guide"] and shown["private_key"]["help"]
    assert len(shown["fields"]) == 4 and all(f["help"] for f in shown["fields"])

    refused = admin.put("/api/admin/docusign", json={
        "environment": "demo", "integration_key": "k", "user_id": "u", "account_id": "a",
        "private_key": "not a key",
    })
    assert refused.status_code == 422 and "RSA" in refused.json()["detail"]
    assert admin.put("/api/admin/docusign", json={
        "environment": "demo", "integration_key": "k", "user_id": "u", "account_id": "a",
    }).status_code == 422  # a key is needed the first time

    mocked = admin.post("/api/admin/docusign/test-setup")
    assert mocked.status_code == 200 and mocked.json()["configured"] is True
    assert "MIIE" not in mocked.text and mocked.json()["has_private_key"] is True
    # Another administrator-only door: an operator cannot read or change it.
    assert operator.get("/api/admin/docusign").status_code == 403

    checked = admin.post("/api/admin/docusign/test-connection").json()
    assert checked == {"ok": True, "message": "Connexion à DocuSign réussie."}


# --- the choice of method ---------------------------------------------------------------------


def test_docusign_cannot_be_chosen_before_it_is_set_up(tmp_path, mock_oidc_base_url, mock):
    _, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    methods = {m["method"]: m for m in operator.get(METHODS).json()}
    assert methods["LOCAL"]["available"] is True and methods["DOCUSIGN"]["available"] is False
    campaign_id = draft(operator, prepare(operator))
    launch = operator.post(f"/api/campaigns/{campaign_id}/launch", json={
        "user_ids": [get_user_id(signer1)], "signature_method": "DOCUSIGN"})
    assert launch.status_code == 409
    assert "DocuSign n'est pas configuré" in launch.json()["detail"]

    admin.post("/api/admin/docusign/test-setup")
    methods = {m["method"]: m for m in operator.get(METHODS).json()}
    assert methods["DOCUSIGN"]["available"] is True


# --- one signer, from the launch to the signed file -------------------------------------------


def test_a_docusign_request_goes_out_and_comes_back_signed(tmp_path, mock_oidc_base_url, mock):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    admin.post("/api/admin/docusign/test-setup")
    person = get_user_id(signer1)
    version_id = prepare(operator)
    campaign_id = draft(operator, version_id)
    launched = operator.post(f"/api/campaigns/{campaign_id}/launch", json={
        "user_ids": [person], "signature_method": "DOCUSIGN"})
    assert launched.status_code == 200, launched.text
    assert operator.get(f"/api/campaigns/{campaign_id}").json()["signature_method"] == "DOCUSIGN"

    # DocuSign mails the signer: LCIT Sign does not send its own "to sign" message.
    assert [e.status for e in envelopes(app)] == ["QUEUED"]
    db = app.state.session_factory()
    from lcit_sign.models.mail import Notification, NotificationType
    assert not db.query(Notification).filter(
        Notification.notification_type == NotificationType.DOCUMENT_TO_SIGN).count()
    db.close()

    # The person sees where it stands, and cannot sign it here.
    mine = signer1.get("/api/me/assignments").json()[0]
    assert mine["signature_method"] == "DOCUSIGN" and mine["docusign"]["status"] == "QUEUED"
    assert signer1.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True}
                        ).status_code == 409
    assert signer1.post(f"/api/sign-all/{campaign_id}", json={"consent": True, "values": {}}
                        ).status_code == 409

    assert work(app, mock) == 1
    sent = envelopes(app)[0]
    assert sent.status == "SENT" and sent.envelope_id
    assert work(app, mock) == 0  # nothing new until the person signs

    sign_in_the_mock(mock, sent.envelope_id)
    assert work(app, mock) == 1
    assert envelopes(app)[0].status == "COMPLETED"

    signed = signer1.get("/api/signatures/me").json()
    assert len(signed) == 1
    signature_id = signed[0]["id"]
    pdf = signer1.get(f"/api/signatures/{signature_id}/signed-pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert signer1.get(f"/api/signatures/{signature_id}/evidence").json()["docusign"][
        "envelope_id"] == sent.envelope_id
    assert signer1.get(f"/api/signatures/{signature_id}/verify").json()["valid"] is True
    assert signer1.get("/api/me/assignments").json()[0]["status"] == "SIGNED"


def test_the_envelope_carries_the_elements_of_that_signer_in_the_right_place(
    tmp_path, mock_oidc_base_url, mock
):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    admin.post("/api/admin/docusign/test-setup")
    campaign_id = draft(operator, prepare(operator))
    operator.post(f"/api/campaigns/{campaign_id}/launch", json={
        "user_ids": [get_user_id(signer1)], "signature_method": "DOCUSIGN"})
    work(app, mock)
    (envelope,) = json.loads(mock.store.read_text()).values()
    assert "@" in envelope["signer"]["email"]
    (tab,) = envelope["tabs"]["signHereTabs"]
    # element(): x=0.1, y=0.4 of a 612 x 792 page, from the top left.
    assert (tab["pageNumber"], tab["xPosition"], tab["yPosition"]) == ("1", "61", "317")


# --- several signers, one after the other -----------------------------------------------------


def test_the_second_signer_is_sent_what_the_first_one_signed(tmp_path, mock_oidc_base_url, mock):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    admin.post("/api/admin/docusign/test-setup")
    first, second = get_user_id(signer1), get_user_id(signer2)
    version_id = prepare(operator, roles=(1, 2))
    campaign_id = draft(operator, version_id)
    assert operator.put(f"/api/campaigns/{campaign_id}/signers", json={"signers": [
        {"role": 1, "mode": "FIXED", "user_id": first},
        {"role": 2, "mode": "EACH"},
    ]}).status_code == 200
    assert operator.post(f"/api/campaigns/{campaign_id}/launch", json={
        "user_ids": [second], "signature_method": "DOCUSIGN"}).status_code == 200

    work(app, mock)
    stored = json.loads(mock.store.read_text())
    assert len(stored) == 1  # only the first one is asked, the second waits
    (first_envelope,) = stored.values()
    sign_in_the_mock(mock, first_envelope["id"])
    work(app, mock)  # the first signature comes back and releases the second person
    assert [e.status for e in envelopes(app)] == ["COMPLETED", "QUEUED"]

    work(app, mock)
    stored = json.loads(mock.store.read_text())
    assert len(stored) == 2
    second_envelope = next(e for e in stored.values() if e["id"] != first_envelope["id"])
    # What the second person signs is the first one's signed file, not the blank original.
    assert second_envelope["pdf"] != first_envelope["pdf"]
    import base64
    from io import BytesIO

    from pypdf import PdfReader
    assert len(PdfReader(BytesIO(base64.b64decode(second_envelope["pdf"]))).pages) > 1
    assert second_envelope["signer"]["email"] != first_envelope["signer"]["email"]

    sign_in_the_mock(mock, second_envelope["id"])
    work(app, mock)
    assert [(e.status, e.error) for e in envelopes(app)] == [("COMPLETED", None)] * 2
    assert signer2.get("/api/signatures/me").json()[0]["campaign_id"] == campaign_id


# --- when it does not go through --------------------------------------------------------------


def test_a_refusal_by_the_signer_is_recorded_and_a_cancelled_request_withdraws_the_envelope(
    tmp_path, mock_oidc_base_url, mock
):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    admin.post("/api/admin/docusign/test-setup")
    campaign_id = draft(operator, prepare(operator))
    operator.post(f"/api/campaigns/{campaign_id}/launch", json={
        "user_ids": [get_user_id(signer1), get_user_id(signer2)], "signature_method": "DOCUSIGN"})
    work(app, mock)
    one, two = json.loads(mock.store.read_text()).values()
    mock.post(f"/sign/{one['id']}", data={"action": "decline"}, follow_redirects=False)
    work(app, mock)
    assert sorted(e.status for e in envelopes(app)) == ["DECLINED", "SENT"]

    assert operator.post(f"/api/campaigns/{campaign_id}/cancel").status_code == 200
    work(app, mock)
    assert sorted(e.status for e in envelopes(app)) == ["DECLINED", "VOIDED"]
    assert json.loads(mock.store.read_text())[two["id"]]["status"] == "voided"


def test_a_docusign_error_is_kept_and_retried_then_given_up(tmp_path, mock_oidc_base_url, mock):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    admin.post("/api/admin/docusign/test-setup")
    campaign_id = draft(operator, prepare(operator))
    operator.post(f"/api/campaigns/{campaign_id}/launch", json={
        "user_ids": [get_user_id(signer1)], "signature_method": "DOCUSIGN"})

    class Refusing(DocusignClient):
        def create_envelope(self, **kwargs):
            from lcit_sign.services.docusign import DocusignError
            raise DocusignError("DocuSign a refusé la demande (test).")

    db = app.state.session_factory()
    for _ in range(5):
        process_docusign(db, app.state.settings, app.state.storage,
                         client_factory=lambda cfg: Refusing(mock, cfg))
    db.close()
    (row,) = envelopes(app)
    assert row.status == "FAILED" and row.attempts == 5 and "refusé" in row.error
    assert signer1.get("/api/me/assignments").json()[0]["docusign"]["error"] == row.error
