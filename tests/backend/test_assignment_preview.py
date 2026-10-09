"""What a signer is shown is what they sign: the document with the earlier signers' marks, and,
once signed, their own signed copy. (The signed copy of the last person to sign was shown as the
untouched original.)"""
from __future__ import annotations

import io

from pypdf import PdfReader
from test_campaigns import get_user_id, setup_campaign_fixture
from test_prepared_fields import element, upload


def two_signers(tmp_path, oidc):
    app, admin, operator, rssi_client, employee = setup_campaign_fixture(tmp_path, oidc)
    version_id = upload(operator, title="PSSI", pages=1)
    operator.put(
        f"/api/documents/versions/{version_id}/fields",
        json={"fields": [
            element("FULL_NAME", role=1, y=0.1),
            element("SIGNATURE", role=1, y=0.2),
            element("SIGNATURE", role=2, y=0.4),
        ]},
    )
    campaign = operator.post("/api/campaigns", json={"name": "PSSI 2026"}).json()
    operator.post(
        f"/api/campaigns/{campaign['id']}/documents", json={"document_version_id": version_id}
    )
    operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"user_ids": [get_user_id(employee)], "roles": [
            {"role": 1, "mode": "FIXED", "user_id": get_user_id(rssi_client)},
            {"role": 2, "mode": "EACH"},
        ]},
    )
    return app, version_id, rssi_client, employee


def my_assignment(client) -> str:
    return client.get("/api/me/assignments").json()[0]["id"]


def first_page_text(content: bytes) -> str:
    return " ".join(PdfReader(io.BytesIO(content)).pages[0].extract_text().split())


def test_the_second_signer_is_shown_the_first_signers_marks_then_their_own_copy(
    tmp_path, mock_oidc_base_url
):
    app, version_id, rssi_client, employee = two_signers(tmp_path, mock_oidc_base_url)
    rssi_name = rssi_client.get("/api/auth/me").json()["display_name"]
    bob_name = employee.get("/api/auth/me").json()["display_name"]
    rssi_view = rssi_client.get(f"/api/assignments/{my_assignment(rssi_client)}/preview")
    assert rssi_view.status_code == 200 and rssi_view.headers["content-type"] == "application/pdf"
    # Nothing from anyone else before the first signer; his own mark is shown where it will be.
    assert bob_name not in first_page_text(rssi_view.content)
    assert rssi_name in first_page_text(rssi_view.content)

    sign = f"/api/documents/versions/{version_id}/sign"
    assert rssi_client.post(sign, json={"consent": True}).status_code == 201

    # Before signing, the employee sees the RSSI's marks already on the document, and their own
    # where they will be (their name in the signature box, in a dotted frame).
    before = employee.get(f"/api/assignments/{my_assignment(employee)}/preview")
    assert rssi_name in first_page_text(before.content)
    assert bob_name in first_page_text(before.content)
    assert len(PdfReader(io.BytesIO(before.content)).pages) == 1  # no attestation page yet
    assert before.headers["cache-control"] == "no-store"

    assert employee.post(sign, json={"consent": True}).status_code == 201
    # After signing, their own signed copy: both marks, and the attestation page.
    after = employee.get(f"/api/assignments/{my_assignment(employee)}/preview")
    pdf = PdfReader(io.BytesIO(after.content))
    assert len(pdf.pages) == 2
    text = first_page_text(after.content)
    assert rssi_name in text and bob_name in text
    # It is exactly the signed copy.
    signature_id = employee.get("/api/signatures/me").json()[0]["id"]
    assert after.content == employee.get(f"/api/signatures/{signature_id}/signed-pdf").content


def test_it_is_only_for_the_person_asked(tmp_path, mock_oidc_base_url):
    app, version_id, rssi_client, employee = two_signers(tmp_path, mock_oidc_base_url)
    mine = my_assignment(employee)
    assert rssi_client.get(f"/api/assignments/{mine}/preview").status_code == 404
    nobody = "/api/assignments/00000000-0000-0000-0000-000000000000/preview"
    assert employee.get(nobody).status_code == 404
    from fastapi.testclient import TestClient

    assert TestClient(app).get(f"/api/assignments/{mine}/preview").status_code == 401


def test_looking_at_it_counts_as_having_seen_it(tmp_path, mock_oidc_base_url):
    app, version_id, rssi_client, employee = two_signers(tmp_path, mock_oidc_base_url)
    assert rssi_client.get("/api/me/assignments").json()[0]["status"] == "PENDING"
    rssi_client.get(f"/api/assignments/{my_assignment(rssi_client)}/preview")
    assert rssi_client.get("/api/me/assignments").json()[0]["status"] == "VIEWED"
    # Not their turn yet: looking does not change anything.
    employee.get(f"/api/assignments/{my_assignment(employee)}/preview")
    assert employee.get("/api/me/assignments").json()[0]["status"] == "WAITING"


def test_the_page_of_a_signature_says_who_signed_and_who_is_left(tmp_path, mock_oidc_base_url):
    app, version_id, rssi_client, employee = two_signers(tmp_path, mock_oidc_base_url)
    rssi_name = rssi_client.get("/api/auth/me").json()["display_name"]
    bob_name = employee.get("/api/auth/me").json()["display_name"]
    sign = f"/api/documents/versions/{version_id}/sign"
    first = rssi_client.post(sign, json={"consent": True}).json()["id"]

    # The named signer sees himself signed, and a count for the recipients still to come (a
    # recipient's name is for the staff and for the recipient: here the staff see it by name).
    chain = rssi_client.get(f"/api/signatures/{first}/chain").json()
    assert [(s["name"], s["status"], s["mine"]) for s in chain["steps"]] == [
        (rssi_name, "SIGNED", True)
    ]
    assert chain["complete"] is False
    assert chain["others"] == {"count": 1, "signed": 0}

    assert employee.post(sign, json={"consent": True}).status_code == 201
    second = employee.get("/api/signatures/me").json()[0]["id"]
    # The recipient sees the named signer first, then himself.
    mine = employee.get(f"/api/signatures/{second}/chain").json()
    assert [(s["name"], s["status"], s["mine"]) for s in mine["steps"]] == [
        (rssi_name, "SIGNED", False),
        (bob_name, "SIGNED", True),
    ]
    assert mine["complete"] is True and mine["others"] is None
    assert all(s["signed_at"] and s["display_id"] for s in mine["steps"])


def test_a_recipient_never_reads_the_other_recipients_names(tmp_path, mock_oidc_base_url):
    app, admin, operator, rssi_client, employee = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url
    )
    version_id = upload(operator, title="Charte", pages=1)
    operator.put(
        f"/api/documents/versions/{version_id}/fields", json={"fields": [element("SIGNATURE")]}
    )
    campaign = operator.post("/api/campaigns", json={"name": "Charte 2026"}).json()
    operator.post(
        f"/api/campaigns/{campaign['id']}/documents", json={"document_version_id": version_id}
    )
    # Everyone signs their own copy: the employee and the operator-as-recipient.
    operator.post(
        f"/api/campaigns/{campaign['id']}/launch",
        json={"user_ids": [get_user_id(employee), get_user_id(rssi_client)]},
    )
    sign = f"/api/documents/versions/{version_id}/sign"
    employee.post(sign, json={"consent": True})
    rssi_client.post(sign, json={"consent": True})
    mine = employee.get("/api/signatures/me").json()[0]["id"]
    seen = employee.get(f"/api/signatures/{mine}/chain").json()
    assert len(seen["steps"]) == 1 and seen["steps"][0]["mine"] is True
    assert seen["others"] == {"count": 1, "signed": 1}  # a count, no name
    # The staff see everyone.
    everyone = operator.get(f"/api/signatures/{mine}/chain").json()
    assert len(everyone["steps"]) == 2 and everyone["others"] is None
    # Not someone else's chain.
    assert rssi_client.get(f"/api/signatures/{mine}/chain").status_code == 403
