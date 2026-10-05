from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from test_auth_flow import login_as, make_app
from test_campaigns import (
    create_campaign_with_document,
    get_user_id,
    setup_campaign_fixture,
)
from test_directory import find_group_id, sync_directory
from test_documents import make_minimal_pdf_bytes
from test_signatures import publish_a_document as publish_for_signing
from test_signatures import setup_operator_and_signer

from lcit_sign.logging_utils import JsonFormatter
from lcit_sign.models.session import Session as SessionRecord
from lcit_sign.models.signature import Signature
from lcit_sign.models.user import User

TEST_MASTER_KEY = "test-master-key-not-for-production-use"  # noqa: S105


def _publish(operator: TestClient) -> str:
    from test_campaigns import publish_a_document

    return publish_a_document(operator)[1]


# --- authorization matrix (spec §118) -----------------------------------


def test_signer_cannot_call_operator_or_admin_apis(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    assert signer1.get("/api/campaigns").status_code == 403
    assert signer1.get("/api/admin/audit").status_code == 403
    assert signer1.post("/api/admin/signing-keys/rotate").status_code == 403


def test_operator_cannot_call_admin_apis(tmp_path, mock_oidc_base_url):
    app, admin, operator, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    assert operator.get("/api/admin/audit").status_code == 403
    assert operator.post("/api/admin/signing-keys/rotate").status_code == 403
    assert operator.put("/api/admin/mail-connector", json={}).status_code in (403, 422)
    assert operator.post("/api/admin/directory/sync").status_code == 403


def test_expired_and_revoked_sessions_are_refused(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    assert signer1.get("/api/auth/me").status_code == 200
    user_id = uuid.UUID(get_user_id(signer1))

    with app.state.session_factory() as db:
        db.execute(
            update(SessionRecord)
            .where(SessionRecord.user_id == user_id)
            .values(last_activity_at=datetime.now(UTC) - timedelta(days=2))
        )
        db.commit()
    assert signer1.get("/api/auth/me").status_code == 401

    # A fresh login works, then an admin-side revocation kills it.
    login_as(signer1, mock_oidc_base_url, sub="u-it-1")
    assert signer1.get("/api/auth/me").status_code == 200
    with app.state.session_factory() as db:
        db.execute(
            update(SessionRecord)
            .where(SessionRecord.user_id == user_id)
            .values(revoked_at=datetime.now(UTC))
        )
        db.commit()
    assert signer1.get("/api/auth/me").status_code == 401


def test_deactivated_user_cannot_log_in_but_keeps_signatures(tmp_path, mock_oidc_base_url):
    app, operator, signer, admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_for_signing(operator)
    signature_id = signer.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).json()["id"]

    with app.state.session_factory() as db:
        user = db.execute(select(User).where(User.subject == "u-it-1")).scalar_one()
        user.active = False
        db.commit()
    assert signer.get("/api/auth/me").status_code == 401

    with app.state.session_factory() as db:
        assert db.get(Signature, uuid.UUID(signature_id)) is not None
    # The proof stays verifiable for others (admin) after deactivation.
    verify = admin.get(f"/api/signatures/{signature_id}/verify")
    assert verify.status_code in (200, 403)


# --- integrity (spec §45, §118) -----------------------------------------


def test_tampered_original_pdf_fails_verification(tmp_path, mock_oidc_base_url):
    app, operator, signer, _ = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_for_signing(operator)
    signature_id = signer.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).json()["id"]
    original = app.state.storage.path_for("documents", uuid.UUID(version_id), ".pdf")
    original.write_bytes(original.read_bytes() + b"\n% tampered")

    verify = signer.get(f"/api/signatures/{signature_id}/verify").json()
    assert verify["valid"] is False
    assert verify["checks"]["original_document_hash"] is False


def test_tampered_evidence_fails_verification(tmp_path, mock_oidc_base_url):
    app, operator, signer, _ = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_for_signing(operator)
    signature_id = signer.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).json()["id"]
    with app.state.session_factory() as db:
        row = db.get(Signature, uuid.UUID(signature_id))
        row.email_snapshot = "someone.else@example.test"
        db.commit()

    verify = signer.get(f"/api/signatures/{signature_id}/verify").json()
    assert verify["valid"] is False
    assert verify["checks"]["evidence_hash"] is False


def test_rotation_keeps_old_signatures_valid(tmp_path, mock_oidc_base_url):
    app, operator, signer, admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY
    )
    _, version_id, _ = publish_for_signing(operator)
    signature_id = signer.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).json()["id"]
    assert admin.post("/api/admin/signing-keys/rotate").status_code == 201
    assert signer.get(f"/api/signatures/{signature_id}/verify").json()["valid"] is True


def test_uploaded_filename_cannot_traverse_the_filesystem(tmp_path, mock_oidc_base_url):
    app, admin, operator, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    response = operator.post(
        "/api/documents",
        data={"title": "x", "version_label": "1.0"},
        files={"file": ("../../../../etc/evil.pdf", make_minimal_pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 201
    assert not (tmp_path / "evil.pdf").exists()
    version_id = response.json()["versions"][0]["id"]
    assert app.state.storage.path_for("documents", uuid.UUID(version_id), ".pdf").exists()


def test_group_change_after_launch_does_not_alter_the_campaign(tmp_path, mock_oidc_base_url):
    app, admin, operator, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    sync_directory(admin)
    group_id = find_group_id(admin, "IT")
    version_id = _publish(operator)
    campaign = create_campaign_with_document(operator, version_id, "Snapshot")
    launch = operator.post(
        f"/api/campaigns/{campaign['id']}/launch", json={"group_ids": [group_id]}
    ).json()
    before = launch["assignment_counts"]["PENDING"]

    # A new member joins IT afterwards.
    newcomer = TestClient(app)
    login_as(newcomer, mock_oidc_base_url, sub="u-consultants-1")
    from lcit_sign.models.directory import GroupMembership

    with app.state.session_factory() as db:
        user = db.execute(select(User).where(User.subject == "u-consultants-1")).scalar_one()
        db.add(GroupMembership(group_id=uuid.UUID(group_id), user_id=user.id))
        db.commit()

    detail = operator.get(f"/api/campaigns/{campaign['id']}").json()
    assert detail["assignment_counts"]["PENDING"] == before


# --- web hardening (spec §81-83) ------------------------------------------


def test_cross_origin_state_changing_request_is_rejected(tmp_path, mock_oidc_base_url):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    evil = admin.post(
        "/api/admin/signing-keys/rotate", headers={"Origin": "https://evil.example"}
    )
    assert evil.status_code == 403
    cross_site = admin.post(
        "/api/admin/signing-keys/rotate", headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert cross_site.status_code == 403
    ok = admin.post(
        "/api/admin/signing-keys/rotate", headers={"Origin": "http://testserver"}
    )
    assert ok.status_code == 201


def test_login_is_rate_limited(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url, rate_limit_enabled=True)
    with TestClient(app) as client:
        codes = [
            client.get("/api/auth/login", follow_redirects=False).status_code for _ in range(25)
        ]
    assert codes[:20] == [302] * 20
    assert 429 in codes[20:]


def test_ssrf_targets_are_rejected(tmp_path, mock_oidc_base_url):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    base = {"from_address": "a@example.test", "username": "", "use_starttls": False}
    for host, port in [("169.254.169.254", 25), ("127.0.0.1", 22), ("0.0.0.0", 25)]:  # noqa: S104
        response = admin.put(
            "/api/admin/mail-connector", json={**base, "host": host, "port": port}
        )
        assert response.status_code == 422, (host, port, response.text)


def test_unhandled_errors_do_not_leak_a_stack_trace(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url)

    @app.get("/api/_boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail /srv/app/x.py")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/_boom")
    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text
    assert response.json()["request_id"]


# --- secret leakage (spec §71, §119) ---------------------------------------


def test_known_secrets_never_reach_logs(tmp_path, mock_oidc_base_url, caplog):
    fake_secrets = {
        "client_secret": "FAKE-CLIENT-SECRET-7f3a",
        "smtp_password": "FAKE-SMTP-PASSWORD-91bc",
        "connector_secret": "FAKE-CONNECTOR-SECRET-5d2e",
    }
    caplog.set_level(logging.DEBUG)
    app, admin, operator, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    admin.put(
        "/api/admin/directory/sources/entra/config",
        json={"fields": {"tenant_id": "t", "client_id": "c"},
              "secret": fake_secrets["connector_secret"]},
    )
    admin.put(
        "/api/admin/mail-connector",
        json={"host": "localhost", "port": 2525, "from_address": "a@example.test",
              "username": "u", "password": fake_secrets["smtp_password"]},
    )
    admin.post("/api/admin/mail-connector/test-connection")
    admin.get("/api/admin/audit")
    logger = logging.getLogger("leak-check")
    logger.info("explicit", extra={"password": fake_secrets["smtp_password"],
                                    "client_secret": fake_secrets["client_secret"]})

    formatter = JsonFormatter()
    rendered = "\n".join(formatter.format(r) for r in caplog.records)
    for value in fake_secrets.values():
        assert value not in rendered

    # ... nor into the audit trail.
    audit = json.dumps(admin.get("/api/admin/audit").json())
    for value in fake_secrets.values():
        assert value not in audit


def test_session_cookie_is_httponly_samesite_and_opaque(tmp_path, mock_oidc_base_url):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    client = TestClient(app)
    response = login_as(client, mock_oidc_base_url, sub="u-it-1")
    cookies = [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]
    session_cookies = [c for c in cookies if c.lower().startswith("lcit_sign_session")]
    assert session_cookies, cookies
    for cookie in session_cookies:
        assert "httponly" in cookie.lower()
        assert "samesite" in cookie.lower()
    # No OIDC token ever lands in a cookie or in the response body.
    assert "eyJ" not in "".join(cookies)
