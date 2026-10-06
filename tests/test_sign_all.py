from __future__ import annotations

from test_campaigns import get_user_id, setup_campaign_fixture
from test_prepared_fields import element, upload


def doc_with_shared_answer(operator, title: str, *, role: int = 1) -> str:
    version_id = upload(operator, title=title)
    operator.put(
        f"/api/documents/versions/{version_id}/fields",
        json={
            "fields": [
                element("SIGNATURE", role=role, y=0.8),
                element("TEXT", role=role, y=0.2, label="Fonction", group_key="fonction"),
            ]
        },
    )
    return version_id


def launch(operator, versions, body, name="Campagne"):
    campaign = operator.post("/api/campaigns", json={"name": name}).json()
    for version_id in versions:
        operator.post(
            f"/api/campaigns/{campaign['id']}/documents", json={"document_version_id": version_id}
        )
    response = operator.post(f"/api/campaigns/{campaign['id']}/launch", json=body)
    assert response.status_code == 200, response.text
    return campaign["id"]


def my_signatures(client) -> list[dict]:
    return client.get("/api/signatures/me").json()


def test_one_click_signs_every_document_with_the_answer_typed_once(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    versions = [doc_with_shared_answer(operator, f"Doc {n}") for n in "ABC"]
    campaign_id = launch(operator, versions, {"user_ids": [get_user_id(signer1)]})
    url = f"/api/sign-all/{campaign_id}"

    ask = signer1.get(url).json()
    assert [d["title"] for d in ask["documents"]] == ["Doc A", "Doc B", "Doc C"]
    assert {i["group_key"] for d in ask["documents"] for i in d["inputs"]} == {"fonction"}

    # Consent is required; a missing answer refuses the whole batch and nothing is signed.
    assert signer1.post(url, json={"consent": False}).status_code == 400
    missing = signer1.post(url, json={"consent": True})
    assert missing.status_code == 422 and "Fonction" in missing.text
    assert my_signatures(signer1) == []

    done = signer1.post(url, json={"consent": True, "shared": {"fonction": "RSSI"}})
    assert done.status_code == 200, done.text
    assert done.json()["signed"] == 3
    signatures = my_signatures(signer1)
    assert len(signatures) == 3
    # Each document has its own proof, with the shared answer stamped on it.
    for sig in done.json()["signatures"]:
        evidence = signer1.get(f"/api/signatures/{sig['id']}/evidence").json()
        assert "RSSI" in [f["value"] for f in evidence["field_values"]]
        assert signer1.get(f"/api/signatures/{sig['id']}/verify").json()["valid"] is True

    # Nothing left: a second click does nothing, and someone not asked cannot sign.
    assert (
        signer1.post(url, json={"consent": True, "shared": {"fonction": "RSSI"}}).status_code == 409
    )
    assert signer2.post(url, json={"consent": True}).status_code == 409
    assert signer1.get(url).json()["documents"] == []


def test_an_answer_for_one_single_element_wins_over_the_shared_one(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    first = doc_with_shared_answer(operator, "Doc A")
    second = doc_with_shared_answer(operator, "Doc B")
    campaign_id = launch(operator, [first, second], {"user_ids": [get_user_id(signer1)]})
    fields = operator.get(f"/api/documents/versions/{first}/fields").json()["fields"]
    text_id = next(f["id"] for f in fields if f["kind"] == "TEXT")
    done = signer1.post(
        f"/api/sign-all/{campaign_id}",
        json={"consent": True, "shared": {"fonction": "Partagé"}, "values": {text_id: "Propre"}},
    )
    assert done.status_code == 200, done.text
    values = {}
    for sig in done.json()["signatures"]:
        evidence = signer1.get(f"/api/signatures/{sig['id']}/evidence").json()
        values[sig["document_version_id"]] = [
            f["value"] for f in evidence["field_values"] if f["kind"] == "TEXT"
        ]
    assert values[first] == ["Propre"] and values[second] == ["Partagé"]


def test_the_fixed_signer_signs_all_documents_and_everyone_else_is_then_asked(
    tmp_path, mock_oidc_base_url
):
    """The RSSI case: one click for all the policies, then each employee gets every document."""
    app, admin, operator, rssi_client, employee = setup_campaign_fixture(
        tmp_path, mock_oidc_base_url
    )
    rssi, emp = get_user_id(rssi_client), get_user_id(employee)
    versions = []
    for title in ("PSSI", "Charte"):
        version_id = upload(operator, title=title)
        operator.put(
            f"/api/documents/versions/{version_id}/fields",
            json={
                "fields": [
                    element("SIGNATURE", role=1, y=0.7),
                    element("SIGNATURE", role=2, y=0.85),
                ]
            },
        )
        versions.append(version_id)
    campaign_id = launch(
        operator,
        versions,
        {
            "user_ids": [emp],
            "roles": [
                {"role": 1, "mode": "FIXED", "user_id": rssi},
                {"role": 2, "mode": "EACH"},
            ],
        },
    )
    # The employee has nothing to sign yet.
    assert employee.get(f"/api/sign-all/{campaign_id}").json()["documents"] == []
    assert employee.get(f"/api/sign-all/{campaign_id}").json()["waiting"] == 2

    assert (
        rssi_client.post(f"/api/sign-all/{campaign_id}", json={"consent": True}).json()["signed"]
        == 2
    )
    after = employee.get(f"/api/sign-all/{campaign_id}").json()
    assert [d["title"] for d in after["documents"]] == ["Charte", "PSSI"] and after["waiting"] == 0
    assert (
        employee.post(f"/api/sign-all/{campaign_id}", json={"consent": True}).json()["signed"] == 2
    )


def test_a_closed_campaign_cannot_be_signed(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    campaign_id = launch(
        operator, [doc_with_shared_answer(operator, "Doc A")], {"user_ids": [get_user_id(signer1)]}
    )
    operator.post(f"/api/campaigns/{campaign_id}/close")
    assert signer1.get(f"/api/sign-all/{campaign_id}").status_code == 409
    assert (
        signer1.post(
            f"/api/sign-all/{campaign_id}", json={"consent": True, "shared": {"fonction": "x"}}
        ).status_code
        == 409
    )
