from __future__ import annotations

from test_campaigns import (
    create_and_launch_campaign,
    create_campaign_with_document,
    get_user_id,
    publish_a_document,
    setup_campaign_fixture,
)


def launched(tmp_path, oidc):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, oidc)
    _, version_id = publish_a_document(operator)
    campaign = create_and_launch_campaign(
        operator, version_id, [get_user_id(signer1), get_user_id(signer2)]
    )
    return app, admin, operator, signer1, signer2, version_id, campaign


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
    app, admin, operator, s1, s2, version_id, campaign = launched(tmp_path, mock_oidc_base_url)
    cid = campaign["id"]
    # Running: cancel first.
    running = operator.delete(f"/api/campaigns/{cid}")
    assert running.status_code == 409 and "annulez" in running.text
    operator.post(f"/api/campaigns/{cid}/cancel")
    assert operator.delete(f"/api/campaigns/{cid}").status_code == 200
    assert operator.get(f"/api/campaigns/{cid}").status_code == 404
    assert operator.get("/api/campaigns").json() == []


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
        assert call().status_code == 403
    assert admin.post(f"/api/campaigns/{cid}/cancel").status_code == 200
    assert admin.delete(f"/api/campaigns/{cid}").status_code == 200


def test_a_draft_campaign_can_be_deleted_straight_away(tmp_path, mock_oidc_base_url):
    app, admin, operator, s1, s2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    draft = create_campaign_with_document(operator, version_id, "Brouillon")
    assert operator.delete(f"/api/campaigns/{draft['id']}").status_code == 200
    # The document itself is untouched.
    assert operator.get("/api/documents").json()[0]["versions"][0]["can_delete"] is True
