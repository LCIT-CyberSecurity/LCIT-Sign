from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from test_campaigns import (
    create_and_launch_campaign,
    get_user_id,
    publish_a_document,
    setup_campaign_fixture,
)

from lcit_sign import models  # noqa: F401 - registers tables on Base.metadata
from lcit_sign.models.mail import Notification
from lcit_sign.services.crypto import decrypt_secret, encrypt_secret
from lcit_sign.services.notification_queue import process_pending_notifications

TEST_MASTER_KEY = "test-master-key-not-for-production-use"  # noqa: S105


def test_encrypt_decrypt_roundtrip():
    token = encrypt_secret(TEST_MASTER_KEY, "super-secret-smtp-password")
    assert decrypt_secret(TEST_MASTER_KEY, token) == "super-secret-smtp-password"


def test_decrypt_fails_with_wrong_master_key():
    token = encrypt_secret(TEST_MASTER_KEY, "super-secret-smtp-password")
    with pytest.raises(Exception):  # noqa: B017 - AESGCM raises its own InvalidTag
        decrypt_secret("a-completely-different-master-key", token)


def configure_mail_connector(admin_client, host: str, port: int, **overrides):
    body = {
        "host": host,
        "port": port,
        "use_tls": False,
        "use_starttls": False,
        "username": "",
        "password": None,
        "from_address": "lcit-sign@example.test",
        "reply_to": None,
        "timeout_seconds": 5,
        **overrides,
    }
    response = admin_client.put("/api/admin/mail-connector", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_mail_connector_configuration_never_leaks_the_password(
    tmp_path, mock_oidc_base_url, smtp_test_server
):
    host, port, _handler = smtp_test_server
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)

    body = configure_mail_connector(admin, host, port, username="smtpuser", password="smtp-secret")
    assert "password" not in body
    assert body["password_configured"] is True

    get_body = admin.get("/api/admin/mail-connector").json()
    assert "password" not in get_body
    assert get_body["password_configured"] is True


def test_non_admin_cannot_configure_mail(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    response = operator.put(
        "/api/admin/mail-connector", json={"host": "smtp.example.test", "from_address": "a@b.test"}
    )
    assert response.status_code == 403


def test_test_connection_diagnostics_against_a_real_smtp_server(
    tmp_path, mock_oidc_base_url, smtp_test_server
):
    host, port, _handler = smtp_test_server
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    configure_mail_connector(admin, host, port)

    response = admin.post("/api/admin/mail-connector/test-connection")
    assert response.status_code == 200
    body = response.json()
    assert body["dns"] == "OK"
    assert body["tcp"] == "OK"


def test_test_connection_reports_failure_for_an_unreachable_host(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    configure_mail_connector(admin, "127.0.0.1", 1)  # nothing listens on port 1

    response = admin.post("/api/admin/mail-connector/test-connection")
    assert response.status_code == 200
    assert response.json()["tcp"].startswith("FAIL")


def test_send_test_email_is_delivered(tmp_path, mock_oidc_base_url, smtp_test_server):
    host, port, handler = smtp_test_server
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    configure_mail_connector(admin, host, port)

    response = admin.post(
        "/api/admin/mail-connector/send-test", json={"to": "someone@example.test"}
    )
    assert response.status_code == 200
    assert response.json() == {"sent": True}
    assert len(handler.messages) == 1
    assert handler.messages[0]["rcpt_tos"] == ["someone@example.test"]


def test_campaign_launch_queues_document_to_sign_notifications(
    tmp_path, mock_oidc_base_url, smtp_test_server
):
    host, port, handler = smtp_test_server
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    configure_mail_connector(admin, host, port)
    _, version_id = publish_a_document(operator)
    create_and_launch_campaign(operator, version_id, [get_user_id(signer1), get_user_id(signer2)])

    queued = admin.get(
        "/api/admin/notifications", params={"notification_type": "DOCUMENT_TO_SIGN"}
    ).json()
    assert len(queued) == 2
    assert all(n["status"] == "PENDING" for n in queued)

    db = app.state.session_factory()
    try:
        sent_count = process_pending_notifications(db, app.state.settings)
    finally:
        db.close()
    assert sent_count == 2
    assert len(handler.messages) == 2


def test_notification_retries_on_unreachable_smtp_server(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    configure_mail_connector(admin, "127.0.0.1", 1)
    _, version_id = publish_a_document(operator)
    create_and_launch_campaign(operator, version_id, [get_user_id(signer1)])

    db = app.state.session_factory()
    try:
        sent_count = process_pending_notifications(db, app.state.settings)
    finally:
        db.close()

    assert sent_count == 0
    notifications = admin.get("/api/admin/notifications").json()
    assert notifications[0]["status"] == "RETRY"
    assert notifications[0]["attempt_count"] == 1


def test_notification_fails_permanently_after_max_attempts(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    configure_mail_connector(admin, "127.0.0.1", 1)
    _, version_id = publish_a_document(operator)
    create_and_launch_campaign(operator, version_id, [get_user_id(signer1)])

    db = app.state.session_factory()
    try:
        notification = db.execute(select(Notification)).scalars().first()
        notification.attempt_count = 4  # one more failed attempt reaches MAX_ATTEMPTS
        notification.next_attempt_at = datetime.now(UTC)
        db.commit()

        process_pending_notifications(db, app.state.settings)
        db.refresh(notification)
        assert notification.status.value == "FAILED"
    finally:
        db.close()


def test_signing_queues_a_confirmation_notification(tmp_path, mock_oidc_base_url, smtp_test_server):
    host, port, _handler = smtp_test_server
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    configure_mail_connector(admin, host, port)
    _, version_id = publish_a_document(operator)
    create_and_launch_campaign(operator, version_id, [get_user_id(signer1)])

    sign_response = signer1.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    )
    assert sign_response.status_code == 201

    confirmations = admin.get(
        "/api/admin/notifications", params={"notification_type": "SIGNATURE_CONFIRMATION"}
    ).json()
    assert len(confirmations) == 1
    assert confirmations[0]["recipient_email"] == "erwan.petit@lcit-test.local"


def test_remind_only_targets_outstanding_assignments(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    campaign = create_and_launch_campaign(
        operator, version_id, [get_user_id(signer1), get_user_id(signer2)]
    )

    signer1.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})

    remind_response = operator.post(f"/api/campaigns/{campaign['id']}/remind")
    assert remind_response.status_code == 200
    assert remind_response.json()["reminders_queued"] == 1  # only signer2 is still outstanding

    reminders = admin.get(
        "/api/admin/notifications", params={"notification_type": "REMINDER"}
    ).json()
    assert len(reminders) == 1
