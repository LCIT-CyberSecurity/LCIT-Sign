from __future__ import annotations

from test_campaigns import (
    create_and_launch_campaign,
    get_user_id,
    publish_a_document,
    setup_campaign_fixture,
)

TEST_MASTER_KEY = "test-master-key-not-for-production-use"  # noqa: S105


def test_generate_and_download_report(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    campaign = create_and_launch_campaign(
        operator, version_id, [get_user_id(signer1), get_user_id(signer2)]
    )

    signer1.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})

    create_response = operator.post(f"/api/campaigns/{campaign['id']}/reports")
    assert create_response.status_code == 201, create_response.text
    report = create_response.json()
    assert report["display_id"].startswith("PV-")

    pdf_response = operator.get(f"/api/reports/{report['id']}/pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.content.startswith(b"%PDF-")

    csv_response = operator.get(f"/api/reports/{report['id']}/csv")
    assert csv_response.status_code == 200
    csv_text = csv_response.content.decode("utf-8")
    assert "report_id" in csv_text
    assert campaign["name"] in csv_text

    verify_response = operator.get(f"/api/reports/{report['id']}/verify")
    assert verify_response.status_code == 200
    assert verify_response.json() == {
        "valid": True,
        "checks": {"pdf_hash": True, "cryptographic_signature": True},
    }


def test_report_lists_signers_and_non_signers(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    campaign = create_and_launch_campaign(
        operator, version_id, [get_user_id(signer1), get_user_id(signer2)]
    )
    signer1.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})

    report = operator.post(f"/api/campaigns/{campaign['id']}/reports").json()
    csv_text = operator.get(f"/api/reports/{report['id']}/csv").content.decode("utf-8")

    assert "erwan.petit@lcit-test.local,Erwan Petit,SIGNED" in csv_text
    assert "bob.dupont@lcit-test.local,Bob Dupont,PENDING" in csv_text


def test_report_list_endpoint(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    campaign = create_and_launch_campaign(operator, version_id, [get_user_id(signer1)])
    operator.post(f"/api/campaigns/{campaign['id']}/reports")
    operator.post(f"/api/campaigns/{campaign['id']}/reports")

    reports = operator.get(f"/api/campaigns/{campaign['id']}/reports").json()
    assert len(reports) == 2


def test_signer_cannot_generate_reports(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = publish_a_document(operator)
    campaign = create_and_launch_campaign(operator, version_id, [get_user_id(signer1)])

    response = signer1.post(f"/api/campaigns/{campaign['id']}/reports")
    assert response.status_code in (403, 404)  # a signer asked to sign is not on the campaign
