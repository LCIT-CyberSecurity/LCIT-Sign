from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from test_campaign_changes import prepared_doc, queued
from test_campaigns import get_user_id, setup_campaign_fixture
from test_prepared_fields import element, upload
from test_signer_roles import new_campaign

from lcit_sign.models.audit import AuditEvent
from lcit_sign.models.campaign import Campaign, CampaignDocument
from lcit_sign.services.scheduler import process_scheduled_starts


def days(n: int) -> str:
    return (datetime.now(UTC) + timedelta(days=n)).isoformat()


def start_worker(app, now: datetime) -> int:
    with app.state.session_factory() as db:
        return process_scheduled_starts(db, app.state.settings, app.state.storage, now=now)


def test_a_campaign_can_be_scheduled_and_starts_by_itself_on_its_date(
    tmp_path, mock_oidc_base_url
):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    version_id = prepared_doc(operator, "Charte")
    campaign = new_campaign(operator, version_id)
    base = f"/api/campaigns/{campaign['id']}"
    start = days(7)

    scheduled = operator.post(
        f"{base}/launch",
        json={"user_ids": [get_user_id(signer1)], "start_at": start, "deadline": days(30)},
    )
    assert scheduled.status_code == 200, scheduled.text
    body = scheduled.json()
    assert body["status"] == "SCHEDULED" and body["scheduled_start"] is not None
    # Nobody is asked yet, and nothing was frozen.
    assert operator.get(f"{base}/assignments").json() == []
    assert queued(admin, "DOCUMENT_TO_SIGN") == []
    assert operator.get(f"/api/documents/versions/{version_id}/fields").json()["editable"] is True
    # It cannot be launched again nor edited meanwhile.
    people = {"user_ids": [get_user_id(signer1)]}
    assert operator.post(f"{base}/launch", json=people).status_code == 409
    assert operator.post(f"{base}/recipients", json=people).status_code == 409

    # Before its date the worker leaves it alone; on its date it starts.
    assert start_worker(app, datetime.now(UTC) + timedelta(days=1)) == 0
    assert start_worker(app, datetime.now(UTC) + timedelta(days=8)) == 1
    started = operator.get(base).json()
    assert started["status"] == "ACTIVE" and started["scheduled_start"] is None
    rows = operator.get(f"{base}/assignments").json()
    assert [r["status"] for r in rows] == ["PENDING"] and rows[0]["deadline"] is not None
    assert len(queued(admin, "DOCUMENT_TO_SIGN")) == 1
    assert operator.get(f"/api/documents/versions/{version_id}/fields").json()["editable"] is False
    # Once started, it does not start again.
    assert start_worker(app, datetime.now(UTC) + timedelta(days=9)) == 0


def test_a_start_date_in_the_past_or_missing_means_now(tmp_path, mock_oidc_base_url):
    _, _, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    version_id = prepared_doc(operator, "Charte")
    campaign = new_campaign(operator, version_id)
    launched = operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"user_ids": [get_user_id(signer1)], "start_at": days(-1)},
    )
    assert launched.status_code == 200 and launched.json()["status"] == "ACTIVE"


def test_scheduling_checks_everything_now_not_on_the_day(tmp_path, mock_oidc_base_url):
    _, _, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    people = {"user_ids": [get_user_id(signer1)]}
    version_id = prepared_doc(operator, "Charte")
    campaign = new_campaign(operator, version_id)
    url = f"/api/campaigns/{campaign['id']}/launch"

    # A deadline before the start date makes no sense.
    early = operator.post(url, json={**people, "start_at": days(10), "deadline": days(5)})
    assert early.status_code == 422 and "après la date de début" in early.text
    # Nobody to ask.
    assert operator.post(url, json={"start_at": days(10)}).status_code == 400
    assert operator.get(f"/api/campaigns/{campaign['id']}").json()["status"] == "DRAFT"

    # A document that could not be frozen (a logo is placed but none is configured).
    logo_doc = upload(operator, title="Avec logo")
    operator.put(
        f"/api/documents/versions/{logo_doc}/fields",
        json={"fields": [element("LOGO"), element("SIGNATURE", y=0.5)]},
    )
    other = new_campaign(operator, logo_doc)
    refused = operator.post(
        f"/api/campaigns/{other['id']}/launch", json={**people, "start_at": days(10)}
    )
    assert refused.status_code == 409 and "logo" in refused.text


def test_a_scheduled_campaign_can_be_cancelled_and_then_never_starts(
    tmp_path, mock_oidc_base_url
):
    app, _, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    campaign = new_campaign(operator, prepared_doc(operator, "Charte"))
    base = f"/api/campaigns/{campaign['id']}"
    operator.post(
        f"{base}/launch", json={"user_ids": [get_user_id(signer1)], "start_at": days(3)}
    )
    assert operator.delete(base).status_code == 409  # cancel first, like a running one
    assert operator.post(f"{base}/cancel").json()["status"] == "CANCELLED"
    assert start_worker(app, datetime.now(UTC) + timedelta(days=5)) == 0
    assert operator.get(f"{base}/assignments").json() == []


def test_a_campaign_that_cannot_start_goes_back_to_draft_with_the_reason(
    tmp_path, mock_oidc_base_url
):
    app, _, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    campaign = new_campaign(operator, prepared_doc(operator, "Charte"))
    base = f"/api/campaigns/{campaign['id']}"
    operator.post(
        f"{base}/launch", json={"user_ids": [get_user_id(signer1)], "start_at": days(3)}
    )
    # Between the scheduling and the day, its document disappeared.
    with app.state.session_factory() as db:
        db.execute(delete(CampaignDocument))
        db.commit()

    assert start_worker(app, datetime.now(UTC) + timedelta(days=4)) == 0
    assert operator.get(base).json()["status"] == "DRAFT"
    with app.state.session_factory() as db:
        failed = db.execute(
            select(AuditEvent).where(AuditEvent.action == "CAMPAIGN_START_FAILED")
        ).scalar_one()
        assert failed.result == "FAILURE" and "no documents" in failed.metadata_json["reason"]
        assert db.get(Campaign, uuid.UUID(campaign["id"])).scheduled_start is None
