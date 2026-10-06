from __future__ import annotations

from test_campaigns import get_user_id, setup_campaign_fixture
from test_prepared_fields import element, upload
from test_signer_roles import new_campaign, prepare_two_role_document


def statuses(operator, campaign_id) -> dict[str, str]:
    rows = operator.get(f"/api/campaigns/{campaign_id}/assignments").json()
    # The follow-up table names a document "Title v1.0".
    return {f"{r['user_id']}:{r['document_title'].rsplit(' v', 1)[0]}": r["status"] for r in rows}


def queued(admin, kind) -> list[str]:
    rows = admin.get("/api/admin/notifications", params={"notification_type": kind}).json()
    return [n["recipient_email"] for n in rows]


def prepared_doc(operator, title: str) -> str:
    version_id = upload(operator, title=title)
    operator.put(
        f"/api/documents/versions/{version_id}/fields",
        json={"fields": [element("SIGNATURE")]},
    )
    return version_id


def launched(operator, user_ids, *, title="Charte"):
    version_id = prepared_doc(operator, title)
    campaign = new_campaign(operator, version_id)
    response = operator.post(f"/api/campaigns/{campaign['id']}/launch", json={"user_ids": user_ids})
    assert response.status_code == 200, response.text
    return campaign["id"], version_id


def test_people_can_be_added_and_removed_after_the_launch(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    one, two = get_user_id(signer1), get_user_id(signer2)
    campaign_id, version_id = launched(operator, [one])
    base = f"/api/campaigns/{campaign_id}"

    added = operator.post(f"{base}/recipients", json={"user_ids": [two]})
    assert added.status_code == 200 and added.json()["added"] == 1
    assert statuses(operator, campaign_id)[f"{two}:Charte"] == "PENDING"
    assert len(queued(admin, "DOCUMENT_TO_SIGN")) == 2
    # Asking someone already asked changes nothing.
    assert operator.post(f"{base}/recipients", json={"user_ids": [two]}).json()["added"] == 0

    # The newcomer can sign.
    assert signer2.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).status_code == 201

    # Removing cancels what is outstanding and leaves what was signed.
    assert operator.delete(f"{base}/recipients/{one}").json()["cancelled"] == 1
    assert operator.delete(f"{base}/recipients/{two}").json()["cancelled"] == 0
    after = statuses(operator, campaign_id)
    assert after[f"{one}:Charte"] == "CANCELLED" and after[f"{two}:Charte"] == "SIGNED"
    assert signer1.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).status_code == 409

    # Asked again later, the person gets their copy back.
    assert operator.post(f"{base}/recipients", json={"user_ids": [one]}).json()["added"] == 1
    assert statuses(operator, campaign_id)[f"{one}:Charte"] == "PENDING"


def test_a_newcomer_waits_for_the_rssi_when_the_documents_have_two_signers(
    tmp_path, mock_oidc_base_url
):
    app, admin, operator, rssi_client, employee = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url
    )
    rssi, emp, newcomer = get_user_id(rssi_client), get_user_id(employee), get_user_id(operator)
    version_id = prepare_two_role_document(operator)
    campaign = new_campaign(operator, version_id)
    operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"user_ids": [emp], "roles": [
            {"role": 1, "mode": "FIXED", "user_id": rssi},
            {"role": 2, "mode": "EACH"},
        ]},
    )
    base = f"/api/campaigns/{campaign['id']}"
    assert operator.post(f"{base}/recipients", json={"user_ids": [newcomer]}).json()["added"] == 1
    assert statuses(operator, campaign["id"])[f"{newcomer}:PSSI"] == "WAITING"

    rssi_client.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    after = statuses(operator, campaign["id"])
    assert after[f"{newcomer}:PSSI"] == "PENDING" and after[f"{emp}:PSSI"] == "PENDING"

    # The designated signers do not change after the launch.
    assert operator.delete(f"{base}/recipients/{rssi}").status_code == 409


def test_a_document_added_after_the_launch_is_prepared_then_sent(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    one, two = get_user_id(signer1), get_user_id(signer2)
    campaign_id, _ = launched(operator, [one, two])
    base = f"/api/campaigns/{campaign_id}"

    extra = prepared_doc(operator, "Annexe")
    added_doc = operator.post(f"{base}/documents", json={"document_version_id": extra})
    assert added_doc.status_code == 201
    shown = {d["title"]: d for d in operator.get(base).json()["documents"]}
    assert shown["Annexe"]["released"] is False and shown["Charte"]["released"] is True
    assert not any(k.endswith(":Annexe") for k in statuses(operator, campaign_id))
    # Until it is sent it can still be taken back out.
    assert operator.delete(f"{base}/documents/{extra}").status_code == 200
    operator.post(f"{base}/documents", json={"document_version_id": extra})

    sent = operator.post(f"{base}/documents/{extra}/release")
    assert sent.status_code == 200 and sent.json()["copies"] == 2
    after = statuses(operator, campaign_id)
    assert after[f"{one}:Annexe"] == "PENDING" and after[f"{two}:Annexe"] == "PENDING"
    assert operator.get(f"/api/documents/versions/{extra}/fields").json()["editable"] is False
    sign_extra = f"/api/documents/versions/{extra}/sign"
    assert signer1.post(sign_extra, json={"consent": True}).status_code == 201
    # Once sent it is part of the campaign.
    assert operator.delete(f"{base}/documents/{extra}").status_code == 409
    assert operator.post(f"{base}/documents/{extra}/release").status_code == 409
    # A document added later also reaches people added later.
    other = prepared_doc(operator, "Annexe 2")
    operator.post(f"{base}/documents", json={"document_version_id": other})
    operator.post(f"{base}/documents/{other}/release")
    operator.post(f"{base}/recipients", json={"user_ids": [get_user_id(operator)]})
    mine = [k for k in statuses(operator, campaign_id) if k.startswith(get_user_id(operator))]
    assert len(mine) == 3  # Charte, Annexe and Annexe 2


def test_a_closed_campaign_is_no_longer_modified(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    campaign_id, _ = launched(operator, [get_user_id(signer1)])
    operator.post(f"/api/campaigns/{campaign_id}/close")
    base = f"/api/campaigns/{campaign_id}"
    later = {"user_ids": [get_user_id(signer2)]}
    assert operator.post(f"{base}/recipients", json=later).status_code == 409
    extra = prepared_doc(operator, "Tard")
    refused = operator.post(f"{base}/documents", json={"document_version_id": extra})
    assert refused.status_code == 409


def test_reminders_can_target_some_people_only(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    one, two = get_user_id(signer1), get_user_id(signer2)
    campaign_id, _ = launched(operator, [one, two])
    base = f"/api/campaigns/{campaign_id}"

    only_one = operator.post(f"{base}/remind", json={"user_ids": [one]})
    assert only_one.status_code == 200 and only_one.json()["reminders_queued"] == 1
    rows = {r["user_id"]: r for r in operator.get(f"{base}/assignments").json()}
    assert rows[one]["reminder_count"] == 1 and rows[two]["reminder_count"] == 0
    # A row of the table, by its own id.
    by_row = operator.post(f"{base}/remind", json={"assignment_ids": [rows[two]["id"]]})
    assert by_row.json()["reminders_queued"] == 1
    # No body: everyone still outstanding, as before.
    assert operator.post(f"{base}/remind").json()["reminders_queued"] == 2
