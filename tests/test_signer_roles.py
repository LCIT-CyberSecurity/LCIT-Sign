from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from test_campaigns import get_user_id, setup_campaign_fixture
from test_prepared_fields import element, upload


def prepare_two_role_document(operator, labels=None) -> str:
    """Signataire 1 (the RSSI) signs and dates; Signataire 2 (each employee) signs."""
    version_id = upload(operator, title="PSSI", pages=1)
    response = operator.put(
        f"/api/documents/versions/{version_id}/fields",
        json={
            "fields": [
                element("SIGNATURE", role=1, y=0.7),
                element("DATE", role=1, y=0.75, x=0.5, width=0.2),
                element("SIGNATURE", role=2, y=0.85),
            ],
            "role_labels": labels or {"1": "RSSI", "2": "Collaborateur"},
        },
    )
    assert response.status_code == 200, response.text
    operator.post(f"/api/documents/versions/{version_id}/publish")
    return version_id


def new_campaign(operator, version_id) -> dict:
    campaign = operator.post("/api/campaigns", json={"name": "PSSI 2026"}).json()
    operator.post(
        f"/api/campaigns/{campaign['id']}/documents", json={"document_version_id": version_id}
    )
    return campaign


def test_roles_carry_the_names_given_in_the_editor(tmp_path, mock_oidc_base_url):
    _, _, operator, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    version_id = prepare_two_role_document(operator)
    got = operator.get(f"/api/documents/versions/{version_id}/fields").json()
    assert got["role_labels"] == {"1": "RSSI", "2": "Collaborateur"}

    campaign = new_campaign(operator, version_id)
    shown = operator.get(f"/api/campaigns/{campaign['id']}").json()
    assert shown["roles_required"] == 2
    assert [(r["role"], r["label"], r["user_id"]) for r in shown["roles"]] == [
        (1, "RSSI", None),
        (2, "Collaborateur", None),
    ]


def test_launch_needs_every_signer_defined_and_in_a_sensible_shape(tmp_path, mock_oidc_base_url):
    _, _, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    rssi, other = get_user_id(signer1), get_user_id(signer2)
    campaign = new_campaign(operator, prepare_two_role_document(operator))
    url = f"/api/campaigns/{campaign['id']}/launch"
    fixed = {"role": 1, "mode": "FIXED", "user_id": rssi}
    each = {"role": 2, "mode": "EACH"}

    # Nothing said about who is who.
    refused = operator.post(url, json={"user_ids": [other]})
    assert refused.status_code == 422 and "2 signataires" in refused.text
    # A role missing, the list placed before a fixed signer, a person twice, no person.
    assert operator.post(url, json={"user_ids": [other], "roles": [fixed]}).status_code == 422
    swapped = [{"role": 1, "mode": "EACH"}, {"role": 2, "mode": "FIXED", "user_id": rssi}]
    assert operator.post(url, json={"user_ids": [other], "roles": swapped}).status_code == 422
    twice = [fixed, {"role": 2, "mode": "FIXED", "user_id": rssi}]
    assert operator.post(url, json={"roles": twice}).status_code == 422
    nobody = [{"role": 1, "mode": "FIXED"}, each]
    assert operator.post(url, json={"user_ids": [other], "roles": nobody}).status_code == 422
    # A list of recipients needs recipients.
    assert operator.post(url, json={"roles": [fixed, each]}).status_code == 400
    # Still a draft after all those refusals.
    assert operator.get(f"/api/campaigns/{campaign['id']}").json()["status"] == "DRAFT"


def test_the_rssi_signs_first_then_each_employee_gets_their_copy_with_it(
    tmp_path, mock_oidc_base_url
):
    app, admin, operator, rssi_client, employee = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url
    )
    rssi, emp = get_user_id(rssi_client), get_user_id(employee)
    version_id = prepare_two_role_document(operator)
    campaign = new_campaign(operator, version_id)
    # The RSSI is also among the people targeted: their signature already covers it.
    launched = operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={
            "user_ids": [rssi, emp],
            "roles": [
                {"role": 1, "mode": "FIXED", "user_id": rssi, "label": "RSSI"},
                {"role": 2, "mode": "EACH", "label": "Collaborateur"},
            ],
        },
    )
    assert launched.status_code == 200, launched.text
    assert launched.json()["assignment_counts"]["WAITING"] == 1
    assert [(r["mode"], r["user_display_name"] is not None) for r in launched.json()["roles"]] == [
        ("FIXED", True),
        ("EACH", False),
    ]

    table = operator.get(f"/api/campaigns/{campaign['id']}/assignments").json()
    assert len(table) == 2  # the RSSI once, the employee once
    by_user = {row["user_id"]: row for row in table}
    assert by_user[rssi]["status"] == "PENDING" and by_user[rssi]["role"] == 1
    assert by_user[emp]["status"] == "WAITING" and by_user[emp]["role"] == 2
    assert by_user[emp]["waiting_on"] == [by_user[rssi]["user_display_name"]]
    assert "RSSI" in by_user[rssi]["role_label"] or "Signataire 1" in by_user[rssi]["role_label"]

    # Only one "to sign" mail went out: to the RSSI.
    queued = admin.get(
        "/api/admin/notifications", params={"notification_type": "DOCUMENT_TO_SIGN"}
    ).json()
    assert [n["recipient_email"] for n in queued] == [by_user[rssi]["user_email"]]

    # The employee cannot sign yet, and is told why.
    sign_url = f"/api/documents/versions/{version_id}/sign"
    early = employee.post(sign_url, json={"consent": True})
    assert early.status_code == 409 and by_user[rssi]["user_display_name"] in early.text
    mine = employee.get("/api/me/assignments").json()[0]
    assert mine["status"] == "WAITING" and mine["waiting_on"]

    # The RSSI signs: only their own two elements are stamped.
    first = rssi_client.post(sign_url, json={"consent": True})
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    first_evidence = rssi_client.get(f"/api/signatures/{first_id}/evidence").json()
    assert [f["role"] for f in first_evidence["field_values"]] == [1, 1]
    assert "prior_signatures" not in first_evidence

    # Now it is the employee's turn, and they were told.
    queued = admin.get(
        "/api/admin/notifications", params={"notification_type": "DOCUMENT_TO_SIGN"}
    ).json()
    assert sorted(n["recipient_email"] for n in queued) == sorted(
        [by_user[rssi]["user_email"], by_user[emp]["user_email"]]
    )
    assert employee.get("/api/me/assignments").json()[0]["status"] == "PENDING"

    second = employee.post(sign_url, json={"consent": True})
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]

    # Their copy carries the RSSI's stamps and their own, and points at the RSSI's signature.
    evidence = employee.get(f"/api/signatures/{second_id}/evidence").json()
    assert sorted(f["role"] for f in evidence["field_values"]) == [1, 1, 2]
    assert evidence["prior_signatures"] == [
        {"signature_id": first_id, "evidence_hash": first_evidence["evidence_hash"]}
    ]
    text = PdfReader(
        BytesIO(employee.get(f"/api/signatures/{second_id}/signed-pdf").content)
    ).pages[0].extract_text()
    assert by_user[rssi]["user_display_name"].split()[0] in text
    assert by_user[emp]["user_display_name"].split()[0] in text
    verdict = employee.get(f"/api/signatures/{second_id}/verify").json()
    assert verdict["valid"] is True and verdict["checks"]["prior_signatures"] is True

    # Everything is signed; nobody is left waiting.
    assert operator.get(f"/api/campaigns/{campaign['id']}").json()["assignment_counts"][
        "SIGNED"
    ] == 2


def test_a_named_person_for_every_role_needs_no_list_of_recipients(tmp_path, mock_oidc_base_url):
    _, _, operator, first_client, second_client = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url
    )
    first, second = get_user_id(first_client), get_user_id(second_client)
    version_id = prepare_two_role_document(operator)
    campaign = new_campaign(operator, version_id)
    launched = operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"roles": [
            {"role": 1, "mode": "FIXED", "user_id": first},
            {"role": 2, "mode": "FIXED", "user_id": second},
        ]},
    )
    assert launched.status_code == 200, launched.text
    sign_url = f"/api/documents/versions/{version_id}/sign"
    assert second_client.post(sign_url, json={"consent": True}).status_code == 409
    assert first_client.post(sign_url, json={"consent": True}).status_code == 201
    assert second_client.post(sign_url, json={"consent": True}).status_code == 201


def test_cancelling_ends_the_copies_still_waiting(tmp_path, mock_oidc_base_url):
    _, _, operator, rssi_client, employee = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    version_id = prepare_two_role_document(operator)
    campaign = new_campaign(operator, version_id)
    operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"user_ids": [get_user_id(employee)], "roles": [
            {"role": 1, "mode": "FIXED", "user_id": get_user_id(rssi_client)},
            {"role": 2, "mode": "EACH"},
        ]},
    )
    cancelled = operator.post(f"/api/campaigns/{campaign['id']}/cancel")
    assert cancelled.status_code == 200
    counts = cancelled.json()["assignment_counts"]
    assert counts["WAITING"] == 0 and counts["CANCELLED"] == 2
    # Signing after the cancellation is refused (not slipped through as campaign-less).
    sign_url = f"/api/documents/versions/{version_id}/sign"
    assert rssi_client.post(sign_url, json={"consent": True}).status_code == 409


def test_a_single_signer_document_still_launches_the_old_way(tmp_path, mock_oidc_base_url):
    _, _, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    version_id = upload(operator, title="Charte")
    operator.put(
        f"/api/documents/versions/{version_id}/fields",
        json={"fields": [element("SIGNATURE")]},
    )
    operator.post(f"/api/documents/versions/{version_id}/publish")
    campaign = new_campaign(operator, version_id)
    launched = operator.post(
        f"/api/campaigns/{campaign['id']}/launch", json={"user_ids": [get_user_id(signer1)]}
    )
    assert launched.status_code == 200 and launched.json()["assignment_counts"]["PENDING"] == 1
    assert signer1.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).status_code == 201
