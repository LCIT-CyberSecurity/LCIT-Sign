from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from test_auth_flow import make_app  # noqa: F401
from test_campaigns import (
    create_campaign_with_document,
    get_user_id,
    publish_a_document,
    setup_campaign_fixture,
)

from lcit_sign.api.diagnostics import get_diagnostics_http_client
from lcit_sign.models.campaign import AssignmentStatus, Campaign, SignatureAssignment
from lcit_sign.models.mail import Notification, NotificationType
from lcit_sign.models.signature import Signature
from lcit_sign.services.scheduler import (
    add_months,
    process_directory_syncs,
    process_reminders,
    process_renewals,
)


def _launch(operator, version_id, user_ids, **policy):
    campaign = create_campaign_with_document(operator, version_id, "Politique")
    response = operator.post(
        f"/api/campaigns/{campaign['id']}/launch", json={"user_ids": user_ids, **policy}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _reminders(app) -> int:
    with app.state.session_factory() as db:
        return len(
            db.execute(
                select(Notification).where(
                    Notification.notification_type == NotificationType.REMINDER
                )
            ).scalars().all()
        )


def test_automatic_reminders_follow_the_policy(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    _launch(
        operator, version_id, [get_user_id(signer1), get_user_id(signer2)],
        reminder_first_days=7, reminder_interval_days=7, reminder_max_count=2,
    )
    start = datetime.now(UTC)
    with app.state.session_factory() as db:
        # Too early: nothing.
        assert process_reminders(db, app.state.settings, start + timedelta(days=3)) == 0
        # J+7: both outstanding people.
        assert process_reminders(db, app.state.settings, start + timedelta(days=7, hours=1)) == 2
        # Same moment again: idempotent.
        assert process_reminders(db, app.state.settings, start + timedelta(days=7, hours=1)) == 0
        # J+14: second (last allowed) reminder.
        assert process_reminders(db, app.state.settings, start + timedelta(days=14, hours=2)) == 2
        # Maximum reached.
        assert process_reminders(db, app.state.settings, start + timedelta(days=30)) == 0
    assert _reminders(app) == 4


def test_signed_people_are_not_reminded(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url
    )
    _, version_id = publish_a_document(operator)
    _launch(
        operator, version_id, [get_user_id(signer1), get_user_id(signer2)],
        reminder_first_days=1, reminder_interval_days=1,
    )
    assert signer1.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).status_code == 201
    with app.state.session_factory() as db:
        assert process_reminders(db, app.state.settings, datetime.now(UTC) + timedelta(days=2)) == 1


def test_reminder_before_deadline(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    deadline = datetime.now(UTC) + timedelta(days=30)
    _launch(
        operator, version_id, [get_user_id(signer1)], deadline=deadline.isoformat(),
        reminder_first_days=100, reminder_interval_days=100, reminder_before_deadline_days=3,
    )
    with app.state.session_factory() as db:
        assert process_reminders(db, app.state.settings, deadline - timedelta(days=10)) == 0
        assert process_reminders(db, app.state.settings, deadline - timedelta(days=2)) == 1
        assert process_reminders(db, app.state.settings, deadline - timedelta(days=1)) == 0


def test_invalid_policy_is_rejected(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    campaign = create_campaign_with_document(operator, version_id, "Bad")
    response = operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"user_ids": [get_user_id(signer1)], "renewal_every": 3},
    )
    assert response.status_code == 422


def test_renewal_opens_a_followup_campaign_and_allows_resigning(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    first = _launch(
        operator, version_id, [get_user_id(signer1), get_user_id(signer2)],
        renewal_every=6, renewal_unit="MONTHS",
    )
    first_signature = signer1.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).json()
    assert first_signature["campaign_id"] == first["id"]

    with app.state.session_factory() as db:
        assert process_renewals(db, app.state.settings, datetime.now(UTC) + timedelta(days=30)) == 0
        later = datetime.now(UTC) + timedelta(days=190)
        assert process_renewals(db, app.state.settings, later) == 1
        assert process_renewals(db, app.state.settings, later) == 0  # once only

        renewed = db.execute(
            select(Campaign).where(Campaign.renewal_of_campaign_id.is_not(None))
        ).scalar_one()
        assert renewed.status.value == "ACTIVE"
        statuses = {
            a.status
            for a in db.execute(
                select(SignatureAssignment).where(SignatureAssignment.campaign_id == renewed.id)
            ).scalars()
        }
        assert statuses == {AssignmentStatus.PENDING}

    # The same version can be signed again — a second, separate signature.
    again = signer1.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert again.status_code == 201, again.text
    assert again.json()["campaign_id"] == str(renewed.id)
    assert again.json()["id"] != first_signature["id"]
    # ... but not twice for the same campaign.
    assert signer1.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).status_code == 409
    # Both proofs stay valid.
    assert signer1.get(f"/api/signatures/{first_signature['id']}/verify").json()["valid"]
    assert signer1.get(f"/api/signatures/{again.json()['id']}/verify").json()["valid"]
    with app.state.session_factory() as db:
        assert len(db.execute(select(Signature)).scalars().all()) == 2


def test_add_months_clamps_to_month_end():
    assert add_months(datetime(2026, 1, 31, tzinfo=UTC), 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert add_months(datetime(2026, 11, 15, tzinfo=UTC), 3) == datetime(2027, 2, 15, tzinfo=UTC)


def test_scheduled_directory_sync_runs_when_due(tmp_path, mock_oidc_base_url):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    put = admin.put(
        "/api/admin/directory/sources/local/config", json={"sync_interval_minutes": 60}
    )
    assert put.status_code == 200, put.text
    with app.state.session_factory() as db, httpx.Client() as client:
        now = datetime.now(UTC)
        assert process_directory_syncs(db, app.state.settings, client, now) == 1
        assert process_directory_syncs(db, app.state.settings, client, now) == 0
        later = now + timedelta(minutes=61)
        assert process_directory_syncs(db, app.state.settings, client, later) == 1


def test_diagnostics_reports_components_without_secrets(tmp_path, mock_oidc_base_url):
    app, admin, operator, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)

    def fake_client():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        with httpx.Client(transport=transport) as client:
            yield client

    app.dependency_overrides[get_diagnostics_http_client] = fake_client
    admin.put(
        "/api/admin/directory/sources/entra/config",
        json={"fields": {"tenant_id": "73405479-f042-45d7-8149-c90341261b65", "client_id": "9a8b7c6d-5e4f-4321-b0a9-8c7d6e5f4a3b"}, "secret": "FAKE-DIAG-SECRET-1"},  # noqa: E501
    )
    response = admin.get("/api/admin/diagnostics")
    assert response.status_code == 200
    body = response.json()
    names = {c["name"]: c["status"] for c in body["checks"]}
    assert set(names) == {
        "application", "database", "filesystem", "signing_key",
        "oidc", "directory", "smtp", "worker", "builtin_admin",
    }
    assert names["database"] == "OK" and names["filesystem"] == "OK"
    assert names["oidc"] == "OK"
    assert "FAKE-DIAG-SECRET-1" not in response.text
    assert operator.get("/api/admin/diagnostics").status_code == 403


def test_dashboard_and_assignment_filters(tmp_path, mock_oidc_base_url):
    from test_directory import find_group_id, sync_directory

    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    sync_directory(admin)
    it_group = find_group_id(admin, "IT")
    _, version_id = publish_a_document(operator)
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    campaign = create_campaign_with_document(operator, version_id, "Suivi")
    launched = operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"group_ids": [it_group], "user_ids": [get_user_id(signer2)], "deadline": past},
    )
    assert launched.status_code == 200, launched.text
    expected = launched.json()["assignment_counts"]["PENDING"]  # 4 IT members + signer2 = 5

    # One person opens the document, another signs.
    assert signer1.get(f"/api/documents/versions/{version_id}/content").status_code == 200
    assert signer2.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).status_code == 201

    board = operator.get("/api/campaigns/_meta/dashboard").json()
    assert board["campaigns"]["active"] == 1
    assert board["assignments"]["expected"] == expected
    assert board["assignments"]["signed"] == 1
    assert board["assignments"]["outstanding"] == expected - 1
    assert board["assignments"]["not_viewed"] == expected - 2  # signer1 viewed, signer2 signed
    assert board["assignments"]["overdue"] == expected - 1      # the deadline has passed
    assert board["signature_rate"] == round(100 / expected)
    assert admin.get("/api/campaigns/_meta/dashboard").status_code == 200
    assert signer1.get("/api/campaigns/_meta/dashboard").status_code == 403

    base = f"/api/campaigns/{campaign['id']}/assignments"
    everyone = operator.get(base).json()
    assert len(everyone) == expected
    assert {"groups", "document_title"} <= set(everyone[0])
    assert everyone[0]["document_title"].startswith("Charte informatique")

    assert len(operator.get(base, params={"status": "SIGNED"}).json()) == 1
    assert len(operator.get(base, params={"overdue": "true"}).json()) == expected - 1
    assert len(operator.get(base, params={"viewed": "true"}).json()) >= 1
    assert len(operator.get(base, params={"viewed": "false"}).json()) == expected - 1
    in_group = operator.get(base, params={"group_id": it_group}).json()
    assert len(in_group) == 4 and all("IT" in row["groups"] for row in in_group)
    assert operator.get(base, params={"document_version_id": version_id}).json() == everyone
    other = str(uuid.uuid4())
    assert operator.get(base, params={"document_version_id": other}).json() == []
