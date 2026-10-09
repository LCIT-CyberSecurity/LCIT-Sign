from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from test_auth_flow import login_as, make_app
from test_documents import make_minimal_pdf_bytes

from lcit_sign import models  # noqa: F401 - registers tables on Base.metadata
from lcit_sign.database import Base

TEST_MASTER_KEY = "test-master-key-not-for-production-use"  # noqa: S105


def setup_operator_and_signer(tmp_path, mock_oidc_base_url, **overrides):
    """Bootstrap an app with an ADMIN (bootstrap identity), an OPERATOR and
    a SIGNER, returning (app, operator_client, signer_client, admin_client).
    """
    app = make_app(tmp_path, mock_oidc_base_url, **overrides)
    admin = TestClient(app)
    admin.__enter__()
    Base.metadata.create_all(app.state.engine)
    login_as(admin, mock_oidc_base_url, sub="u-direction-1")  # bootstrap ADMIN

    operator_client = TestClient(app)
    login_as(operator_client, mock_oidc_base_url, sub="u-sales-1")
    operator_id = operator_client.get("/api/auth/me").json()["id"]
    assert admin.post(
        f"/api/admin/users/{operator_id}/roles", json={"role": "OPERATOR"}
    ).status_code == 201

    signer_client = TestClient(app)
    login_as(signer_client, mock_oidc_base_url, sub="u-it-1")
    signer_id = signer_client.get("/api/auth/me").json()["id"]
    assert admin.post(
        f"/api/admin/users/{signer_id}/roles", json={"role": "SIGNER"}
    ).status_code == 201

    return app, operator_client, signer_client, admin


def publish_a_document(operator_client: TestClient, ask: TestClient | None = None):
    """Upload and publish a document. With `ask`, also run a campaign (owned by `operator_client`)
    that asks that person to sign it: signing needs a request, there is no unasked signature."""
    pdf_bytes = make_minimal_pdf_bytes()
    document = operator_client.post(
        "/api/documents",
        data={"title": "Charte informatique", "version_label": "1.0"},
        files={"file": ("charte.pdf", pdf_bytes, "application/pdf")},
    ).json()
    version_id = document["versions"][0]["id"]
    if ask is not None:
        fields = [{"page": 1, "x": 0.1, "y": 0.7, "width": 0.3, "height": 0.06,
                   "kind": "SIGNATURE", "role": 1}]
        assert operator_client.put(
            f"/api/documents/versions/{version_id}/fields", json={"fields": fields}
        ).status_code == 200
    publish_response = operator_client.post(f"/api/documents/versions/{version_id}/publish")
    assert publish_response.status_code == 200
    if ask is not None:
        ask_for_signature(operator_client, version_id, ask.get("/api/auth/me").json()["id"])
    return document, version_id, pdf_bytes


def ask_for_signature(owner: TestClient, version_id: str, signer_id: str) -> str:
    """A campaign of `owner` asking `signer_id` to sign `version_id` (returns the campaign id)."""
    campaign = owner.post("/api/campaigns", json={"name": "Demande de signature"})
    assert campaign.status_code == 201, campaign.text
    cid = campaign.json()["id"]
    assert owner.post(
        f"/api/campaigns/{cid}/documents", json={"document_version_id": version_id}
    ).status_code == 201
    launched = owner.post(f"/api/campaigns/{cid}/launch", json={"user_ids": [signer_id]})
    assert launched.status_code == 200, launched.text
    return cid


def test_sign_produces_signed_pdf_certificate_evidence_and_verifies(tmp_path, mock_oidc_base_url):
    app, operator, signer, _admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, original_bytes = publish_a_document(operator, ask=signer)

    response = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert response.status_code == 201, response.text
    signature_id = response.json()["id"]

    signed_pdf = signer.get(f"/api/signatures/{signature_id}/signed-pdf")
    assert signed_pdf.status_code == 200
    assert signed_pdf.content.startswith(b"%PDF-")
    assert signed_pdf.content != original_bytes

    certificate = signer.get(f"/api/signatures/{signature_id}/certificate")
    assert certificate.status_code == 200
    assert certificate.content.startswith(b"%PDF-")

    evidence = signer.get(f"/api/signatures/{signature_id}/evidence").json()
    assert evidence["signing_key_id"]
    assert evidence["evidence_hash"]
    assert evidence["original_document_sha256"]

    verify = signer.get(f"/api/signatures/{signature_id}/verify")
    assert verify.status_code == 200
    assert verify.json() == {
        "valid": True,
        "checks": {
            "original_document_hash": True,
            "signed_document_hash": True,
            "evidence_hash": True,
            "cryptographic_signature": True,
            "signing_key_trusted": True,
            "metadata_consistent": True,
        },
    }


def test_double_signing_is_rejected(tmp_path, mock_oidc_base_url):
    app, operator, signer, _admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator, ask=signer)

    first = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert first.status_code == 201
    second = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert second.status_code == 409


def test_sign_without_consent_is_rejected(tmp_path, mock_oidc_base_url):
    app, operator, signer, _admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator, ask=signer)
    response = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": False})
    assert response.status_code == 400


def test_cannot_sign_a_draft_version(tmp_path, mock_oidc_base_url):
    app, operator, signer, _admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    pdf_bytes = make_minimal_pdf_bytes()
    document = operator.post(
        "/api/documents",
        data={"title": "Draft doc", "version_label": "1.0"},
        files={"file": ("d.pdf", pdf_bytes, "application/pdf")},
    ).json()
    version_id = document["versions"][0]["id"]  # never published

    response = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert response.status_code == 409


def test_user_without_signer_role_cannot_sign_unasked(tmp_path, mock_oidc_base_url):
    app, operator, _signer, _admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator)
    # Everyone can sign by default; once an administrator takes the role away, nothing unasked.
    operator_id = operator.get("/api/auth/me").json()["id"]
    assert _admin.delete(f"/api/admin/users/{operator_id}/roles/SIGNER").status_code == 200
    response = operator.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert response.status_code == 403


def test_signing_without_master_key_returns_503(tmp_path, mock_oidc_base_url):
    app, operator, signer, _admin = setup_operator_and_signer(tmp_path, mock_oidc_base_url)
    _, version_id, _ = publish_a_document(operator, ask=signer)
    response = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert response.status_code == 503


def test_verify_detects_a_tampered_signed_pdf_on_disk(tmp_path, mock_oidc_base_url):
    app, operator, signer, _admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator, ask=signer)
    signature_id = signer.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).json()["id"]

    tampered_path = app.state.storage.path_for("signed", uuid.UUID(signature_id), ".pdf")
    tampered_path.write_bytes(b"%PDF-this-has-been-tampered-with")

    verify = signer.get(f"/api/signatures/{signature_id}/verify").json()
    assert verify["valid"] is False
    assert verify["checks"]["signed_document_hash"] is False


def test_another_users_signature_is_not_accessible(tmp_path, mock_oidc_base_url):
    app, operator, signer, admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator, ask=signer)
    signature_id = signer.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).json()["id"]

    other_signer = TestClient(app)
    login_as(other_signer, mock_oidc_base_url, sub="u-rh-1")
    other_id = other_signer.get("/api/auth/me").json()["id"]
    admin.post(f"/api/admin/users/{other_id}/roles", json={"role": "SIGNER"})

    assert other_signer.get(f"/api/signatures/{signature_id}").status_code == 403
    assert other_signer.get(f"/api/signatures/{signature_id}/signed-pdf").status_code == 403
    assert other_signer.get(f"/api/signatures/{signature_id}/evidence").status_code == 403


def test_admin_can_rotate_signing_key(tmp_path, mock_oidc_base_url):
    app, operator, signer, admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator, ask=signer)
    signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})

    rotate_response = admin.post("/api/admin/signing-keys/rotate")
    assert rotate_response.status_code == 201

    keys = admin.get("/api/admin/signing-keys").json()
    statuses = [k["status"] for k in keys]
    assert statuses.count("ACTIVE") == 1
    assert statuses.count("RETIRED") == 1


# --- signing needs the SIGNER role AND an active request (assignment) ----------------------------


def _set_assignment_status(app, signer: TestClient, status):
    from sqlalchemy import select

    from lcit_sign.models.campaign import SignatureAssignment

    user_id = uuid.UUID(signer.get("/api/auth/me").json()["id"])
    with app.state.session_factory() as db:
        for a in db.execute(
            select(SignatureAssignment).where(SignatureAssignment.user_id == user_id)
        ).scalars():
            a.status = status
        db.commit()


def _sign(client: TestClient, version_id: str):
    return client.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})


def test_a_pending_or_viewed_request_lets_a_signer_sign(tmp_path, mock_oidc_base_url):  # A, B
    from lcit_sign.models.campaign import AssignmentStatus

    app, operator, signer, _ = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, pending_version, _ = publish_a_document(operator, ask=signer)
    assert _sign(signer, pending_version).status_code == 201  # PENDING
    _, viewed_version, _ = publish_a_document(operator, ask=signer)
    with app.state.session_factory() as db:
        from sqlalchemy import select

        from lcit_sign.models.campaign import SignatureAssignment

        for a in db.execute(select(SignatureAssignment)).scalars():
            if str(a.document_version_id) == viewed_version:
                a.status = AssignmentStatus.VIEWED
        db.commit()
    assert _sign(signer, viewed_version).status_code == 201


def test_a_signer_without_a_request_cannot_sign_a_published_document(  # C
    tmp_path, mock_oidc_base_url
):
    app, operator, signer, _ = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator)  # published, nobody asked
    refused = _sign(signer, version_id)
    assert refused.status_code == 409
    assert "Aucune demande de signature active" in refused.json()["detail"]
    # Not even with a campaign named, and the owner cannot sign their own document unasked.
    assert signer.post(
        f"/api/documents/versions/{version_id}/sign",
        json={"consent": True, "campaign_id": str(uuid.uuid4())},
    ).status_code == 409
    assert _sign(operator, version_id).status_code == 409
    # Nothing was created behind the scenes.
    from sqlalchemy import func, select

    from lcit_sign.models.campaign import SignatureAssignment
    from lcit_sign.models.signature import Signature

    with app.state.session_factory() as db:
        assert db.execute(select(func.count()).select_from(Signature)).scalar_one() == 0
        assert db.execute(select(func.count()).select_from(SignatureAssignment)).scalar_one() == 0


def test_a_request_without_the_signer_role_is_not_enough(tmp_path, mock_oidc_base_url):  # D
    app, operator, signer, admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator, ask=signer)
    signer_id = signer.get("/api/auth/me").json()["id"]
    assert admin.delete(f"/api/admin/users/{signer_id}/roles/SIGNER").status_code == 200
    assert _sign(signer, version_id).status_code == 403
    back = admin.post(f"/api/admin/users/{signer_id}/roles", json={"role": "SIGNER"})
    assert back.status_code == 201
    assert _sign(signer, version_id).status_code == 201  # role back: the same request works


def test_a_waiting_cancelled_or_expired_request_refuses_the_signature(  # E, F, G
    tmp_path, mock_oidc_base_url
):
    from lcit_sign.models.campaign import AssignmentStatus

    app, operator, signer, _ = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator, ask=signer)
    for status in (AssignmentStatus.WAITING, AssignmentStatus.CANCELLED, AssignmentStatus.EXPIRED):
        _set_assignment_status(app, signer, status)
        refused = _sign(signer, version_id)
        assert refused.status_code == 409, status
    _set_assignment_status(app, signer, AssignmentStatus.PENDING)
    assert _sign(signer, version_id).status_code == 201


def test_signing_twice_is_refused(tmp_path, mock_oidc_base_url):  # H
    app, operator, signer, _ = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator, ask=signer)
    assert _sign(signer, version_id).status_code == 201
    assert _sign(signer, version_id).status_code == 409


def test_someone_who_designates_themselves_in_a_campaign_then_signs(  # I
    tmp_path, mock_oidc_base_url
):
    app, operator, _signer, _ = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator, ask=operator)  # the owner asks themself
    from sqlalchemy import select

    from lcit_sign.models.campaign import AssignmentStatus, SignatureAssignment

    me = uuid.UUID(operator.get("/api/auth/me").json()["id"])
    with app.state.session_factory() as db:
        assignment = db.execute(
            select(SignatureAssignment).where(SignatureAssignment.user_id == me)
        ).scalar_one()
        assert assignment.status == AssignmentStatus.PENDING
    assert _sign(operator, version_id).status_code == 201
