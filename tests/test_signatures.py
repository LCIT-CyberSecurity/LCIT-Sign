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


def publish_a_document(operator_client: TestClient):
    pdf_bytes = make_minimal_pdf_bytes()
    document = operator_client.post(
        "/api/documents",
        data={"title": "Charte informatique", "version_label": "1.0"},
        files={"file": ("charte.pdf", pdf_bytes, "application/pdf")},
    ).json()
    version_id = document["versions"][0]["id"]
    publish_response = operator_client.post(f"/api/documents/versions/{version_id}/publish")
    assert publish_response.status_code == 200
    return document, version_id, pdf_bytes


def test_sign_produces_signed_pdf_certificate_evidence_and_verifies(tmp_path, mock_oidc_base_url):
    app, operator, signer, _admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, original_bytes = publish_a_document(operator)

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
        },
    }


def test_double_signing_is_rejected(tmp_path, mock_oidc_base_url):
    app, operator, signer, _admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator)

    first = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert first.status_code == 201
    second = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert second.status_code == 409


def test_sign_without_consent_is_rejected(tmp_path, mock_oidc_base_url):
    app, operator, signer, _admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator)
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


def test_user_without_signer_role_cannot_sign(tmp_path, mock_oidc_base_url):
    app, operator, _signer, _admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator)
    response = operator.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert response.status_code == 403


def test_signing_without_master_key_returns_503(tmp_path, mock_oidc_base_url):
    app, operator, signer, _admin = setup_operator_and_signer(tmp_path, mock_oidc_base_url)
    _, version_id, _ = publish_a_document(operator)
    response = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert response.status_code == 503


def test_verify_detects_a_tampered_signed_pdf_on_disk(tmp_path, mock_oidc_base_url):
    app, operator, signer, _admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_a_document(operator)
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
    _, version_id, _ = publish_a_document(operator)
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
    _, version_id, _ = publish_a_document(operator)
    signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})

    rotate_response = admin.post("/api/admin/signing-keys/rotate")
    assert rotate_response.status_code == 201

    keys = admin.get("/api/admin/signing-keys").json()
    statuses = [k["status"] for k in keys]
    assert statuses.count("ACTIVE") == 1
    assert statuses.count("RETIRED") == 1
