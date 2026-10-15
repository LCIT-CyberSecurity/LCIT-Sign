from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import event, select
from test_campaigns import (
    create_and_launch_campaign,
    create_campaign_with_document,
    get_user_id,
    publish_a_document,
    setup_campaign_fixture,
)
from test_documents import make_minimal_pdf_bytes

from lcit_sign.models.audit import AuditEvent
from lcit_sign.models.campaign import Campaign, CampaignPreparer, CampaignRole, SignatureAssignment
from lcit_sign.models.document import Document, DocumentField, DocumentVersion
from lcit_sign.models.mail import Notification


def launched(tmp_path, oidc):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, oidc)
    _, version_id = publish_a_document(operator)
    campaign = create_and_launch_campaign(
        operator, version_id, [get_user_id(signer1), get_user_id(signer2)]
    )
    return app, admin, operator, signer1, signer2, version_id, campaign


def enable_sqlite_foreign_keys(app):
    if app.state.engine.dialect.name != "sqlite":
        return

    @event.listens_for(app.state.engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    with app.state.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_a_launched_campaign_keeps_what_was_sent_and_cannot_be_relaunched(
    tmp_path, mock_oidc_base_url
):
    app, admin, operator, s1, s2, version_id, campaign = launched(tmp_path, mock_oidc_base_url)
    cid = campaign["id"]
    # People and documents can be added later (see test_campaign_changes), but what was
    # already sent is part of the campaign, and it is never launched twice.
    link = {"document_version_id": version_id}
    again = operator.post(f"/api/campaigns/{cid}/documents", json=link)
    assert again.status_code == 201
    assert len(operator.get(f"/api/campaigns/{cid}").json()["documents"]) == 1
    assert operator.delete(f"/api/campaigns/{cid}/documents/{version_id}").status_code == 409
    relaunch = operator.post(f"/api/campaigns/{cid}/launch", json={"all_users": True})
    assert relaunch.status_code == 409


def test_cancelling_withdraws_the_campaign_from_signers(tmp_path, mock_oidc_base_url):
    app, admin, operator, s1, s2, version_id, campaign = launched(tmp_path, mock_oidc_base_url)
    cid = campaign["id"]
    assert operator.post(f"/api/campaigns/{cid}/cancel").status_code == 200
    assignments = operator.get(f"/api/campaigns/{cid}/assignments").json()
    assert {a["status"] for a in assignments} == {"CANCELLED"}
    refused = s1.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert refused.status_code == 409 and "plus ouverte" in refused.text


def test_closing_ends_the_signing_but_keeps_what_was_signed(tmp_path, mock_oidc_base_url):
    app, admin, operator, s1, s2, version_id, campaign = launched(tmp_path, mock_oidc_base_url)
    cid = campaign["id"]
    assert s1.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).status_code == 201
    assert operator.post(f"/api/campaigns/{cid}/close").status_code == 200
    statuses = sorted(a["status"] for a in operator.get(f"/api/campaigns/{cid}/assignments").json())
    assert statuses == ["EXPIRED", "SIGNED"]
    assert s2.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).status_code == 409


def test_a_cancelled_campaign_with_no_signature_can_be_deleted(tmp_path, mock_oidc_base_url):
    app, admin, operator, s1, s2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    enable_sqlite_foreign_keys(app)
    _, version_id = publish_a_document(operator)
    campaign = create_and_launch_campaign(operator, version_id, [get_user_id(s1), get_user_id(s2)])
    cid = campaign["id"]
    # Running: cancel first.
    running = operator.delete(f"/api/campaigns/{cid}")
    assert running.status_code == 409 and "annulez" in running.text
    operator.post(f"/api/campaigns/{cid}/cancel")
    assert operator.delete(f"/api/campaigns/{cid}").status_code == 200
    assert operator.get(f"/api/campaigns/{cid}").status_code == 404
    assert operator.get("/api/campaigns").json() == []
    with app.state.session_factory() as db:
        assert (
            db.execute(
                select(SignatureAssignment).where(SignatureAssignment.campaign_id == uuid.UUID(cid))
            ).first()
            is None
        )
        assert (
            db.execute(
                select(Notification).where(Notification.related_assignment_id.is_not(None))
            ).first()
            is None
        )


def test_a_campaign_that_holds_signatures_is_archived_not_deleted(tmp_path, mock_oidc_base_url):
    app, admin, operator, s1, s2, version_id, campaign = launched(tmp_path, mock_oidc_base_url)
    cid = campaign["id"]
    s1.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    operator.post(f"/api/campaigns/{cid}/close")

    detail = operator.get(f"/api/campaigns/{cid}").json()
    assert any("signature" in reason for reason in detail["delete_blockers"])
    refused = operator.delete(f"/api/campaigns/{cid}")
    assert refused.status_code == 409 and "Archivez" in refused.text

    archived = operator.post(f"/api/campaigns/{cid}/archive")
    assert archived.status_code == 200 and archived.json()["status"] == "ARCHIVED"
    assert operator.post(f"/api/campaigns/{cid}/archive").status_code == 409
    # The proof is still there.
    assert len(operator.get(f"/api/campaigns/{cid}/assignments").json()) == 2


def test_only_staff_can_cancel_delete_or_archive(tmp_path, mock_oidc_base_url):
    app, admin, operator, s1, s2, version_id, campaign = launched(tmp_path, mock_oidc_base_url)
    cid = campaign["id"]
    for call in (
        lambda: s1.post(f"/api/campaigns/{cid}/cancel"),
        lambda: s1.delete(f"/api/campaigns/{cid}"),
        lambda: s1.post(f"/api/campaigns/{cid}/archive"),
    ):
        # Not their campaign: hidden (404) or refused (403), never done.
        assert call().status_code in (403, 404)
    assert admin.post(f"/api/campaigns/{cid}/cancel").status_code == 200
    assert admin.delete(f"/api/campaigns/{cid}").status_code == 200


def test_a_draft_campaign_can_be_deleted_straight_away(tmp_path, mock_oidc_base_url):
    app, admin, operator, s1, s2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    draft = create_campaign_with_document(operator, version_id, "Brouillon")
    assert operator.delete(f"/api/campaigns/{draft['id']}").status_code == 200
    # The document itself is untouched.
    assert operator.get("/api/documents").json()[0]["versions"][0]["can_delete"] is True


def test_a_draft_with_signers_and_preparers_can_be_deleted_with_foreign_keys_enabled(
    tmp_path, mock_oidc_base_url
):
    database_url = os.environ.get("LCIT_SIGN_CAMPAIGN_TEST_DATABASE_URL")
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url, **({"database_url": database_url} if database_url else {})
    )

    enable_sqlite_foreign_keys(app)

    document = operator.post(
        "/api/documents",
        data={"title": "Prepared test document", "version_label": "1.0"},
        files={"file": ("prepared.pdf", make_minimal_pdf_bytes(), "application/pdf")},
    ).json()
    version_id = document["versions"][0]["id"]
    prepared = operator.put(
        f"/api/documents/versions/{version_id}/fields",
        json={
            "fields": [
                {
                    "page": 1,
                    "x": 0.1,
                    "y": 0.1,
                    "width": 0.3,
                    "height": 0.05,
                    "kind": "SIGNATURE",
                    "role": 1,
                },
                {
                    "page": 1,
                    "x": 0.1,
                    "y": 0.3,
                    "width": 0.3,
                    "height": 0.05,
                    "kind": "SIGNATURE",
                    "role": 2,
                },
            ],
            "role_labels": {"1": "Responsable", "2": "Collaborateur"},
        },
    )
    assert prepared.status_code == 200, prepared.text
    assert operator.post(f"/api/documents/versions/{version_id}/publish").status_code == 200
    campaign = create_campaign_with_document(operator, version_id, "Draft with configured roles")
    campaign_id = uuid.UUID(campaign["id"])
    document_version_id = uuid.UUID(version_id)

    roles = operator.put(
        f"/api/campaigns/{campaign['id']}/signers",
        json={
            "signers": [
                {"role": 1, "mode": "FIXED", "user_id": get_user_id(signer1)},
                {"role": 2, "mode": "EACH"},
            ]
        },
    )
    assert roles.status_code == 200, roles.text
    preparer = operator.post(
        f"/api/campaigns/{campaign['id']}/preparers",
        json={"user_id": get_user_id(signer2)},
    )
    assert preparer.status_code == 201, preparer.text

    with app.state.session_factory() as db:
        assert (
            len(
                db.execute(select(CampaignRole).where(CampaignRole.campaign_id == campaign_id))
                .scalars()
                .all()
            )
            == 2
        )
        assert db.get(CampaignPreparer, (campaign_id, uuid.UUID(get_user_id(signer2)))) is not None

    deleted = operator.delete(f"/api/campaigns/{campaign['id']}")
    assert deleted.status_code == 200, deleted.text

    with app.state.session_factory() as db:
        assert (
            db.execute(select(CampaignRole).where(CampaignRole.campaign_id == campaign_id)).first()
            is None
        )
        assert db.get(CampaignPreparer, (campaign_id, uuid.UUID(get_user_id(signer2)))) is None
        assert db.get(Document, uuid.UUID(document["id"])) is not None
        assert db.get(DocumentVersion, document_version_id) is not None
        assert (
            len(
                db.execute(
                    select(DocumentField).where(
                        DocumentField.document_version_id == document_version_id
                    )
                )
                .scalars()
                .all()
            )
            == 2
        )
        assert (
            db.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "CAMPAIGN_DELETED",
                    AuditEvent.target_id == str(campaign_id),
                )
            ).scalar_one_or_none()
            is not None
        )


def test_failed_campaign_delete_rolls_back_rows_and_audit(
    tmp_path, mock_oidc_base_url, monkeypatch
):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    campaign = operator.post("/api/campaigns", json={"name": "Delete rollback"}).json()
    campaign_id = uuid.UUID(campaign["id"])
    assert (
        operator.put(
            f"/api/campaigns/{campaign['id']}/signers",
            json={"signers": [{"role": 1, "mode": "FIXED", "user_id": get_user_id(signer1)}]},
        ).status_code
        == 200
    )
    assert (
        operator.post(
            f"/api/campaigns/{campaign['id']}/preparers",
            json={"user_id": get_user_id(signer2)},
        ).status_code
        == 201
    )

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr("lcit_sign.api.campaigns.append_audit_event", fail_audit)
    with pytest.raises(RuntimeError, match="simulated audit failure"):
        operator.delete(f"/api/campaigns/{campaign['id']}")

    with app.state.session_factory() as db:
        assert db.get(Campaign, campaign_id) is not None
        assert db.get(CampaignRole, (campaign_id, 1)) is not None
        assert db.get(CampaignPreparer, (campaign_id, uuid.UUID(get_user_id(signer2)))) is not None
        assert (
            db.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "CAMPAIGN_DELETED",
                    AuditEvent.target_id == str(campaign_id),
                )
            ).scalar_one_or_none()
            is None
        )
