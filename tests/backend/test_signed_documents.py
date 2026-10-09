from __future__ import annotations

import csv
import io
import zipfile

from test_campaign_changes import prepared_doc
from test_campaigns import get_user_id, setup_campaign_fixture, without_signer_role


def launch(operator, title, people):
    # Named after its document, so a search on one title cannot match the other campaign.
    campaign = operator.post("/api/campaigns", json={"name": f"Campagne {title}"}).json()
    version_id = prepared_doc(operator, title)
    operator.post(
        f"/api/campaigns/{campaign['id']}/documents", json={"document_version_id": version_id}
    )
    response = operator.post(f"/api/campaigns/{campaign['id']}/launch", json={"user_ids": people})
    assert response.status_code == 200, response.text
    version = response.json()["documents"][0]["version_id"]
    return campaign["id"], version


def sign(client, version):
    done = client.post(f"/api/documents/versions/{version}/sign", json={"consent": True})
    assert done.status_code == 201, done.text
    return done.json()["id"]


def test_signed_and_outstanding_documents_of_one_or_several_campaigns(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    one, two = get_user_id(signer1), get_user_id(signer2)
    first, first_version = launch(operator, "Charte", [one, two])
    second, second_version = launch(operator, "PSSI", [one])
    sign(signer1, first_version)
    sign(signer1, second_version)

    everything = operator.get("/api/signed/documents").json()
    assert everything["totals"] == {"signed": 2, "outstanding": 1, "waiting": 0}
    assert {r["document_title"] for r in everything["signed"]} == {"Charte", "PSSI"}
    # Who still has to sign what.
    assert [
        (r["signer_email"], r["document_title"], r["status"]) for r in everything["outstanding"]
    ] == [(everything["outstanding"][0]["signer_email"], "Charte", "PENDING")]
    assert len(everything["campaigns"]) == 2

    # One campaign, then both, then a search.
    only_first = operator.get("/api/signed/documents", params={"campaign_ids": [first]}).json()
    assert [r["document_title"] for r in only_first["signed"]] == ["Charte"]
    both = operator.get("/api/signed/documents", params={"campaign_ids": [first, second]}).json()
    assert both["totals"]["signed"] == 2
    searched = operator.get("/api/signed/documents", params={"q": "pssi"}).json()
    assert [r["document_title"] for r in searched["signed"]] == ["PSSI"]
    assert searched["outstanding"] == []


def test_an_operator_opens_the_signed_pdf_of_someone_else(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version = launch(operator, "Charte", [get_user_id(signer1)])
    signature = sign(signer1, version)
    pdf = operator.get(f"/api/signatures/{signature}/signed-pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_only_staff_see_the_signed_documents(tmp_path, mock_oidc_base_url):
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    # A signer sees the signed documents of the campaigns they run: none yet. Without the role,
    # nothing at all.
    assert signer1.get("/api/signed/documents").json()["campaigns"] == []
    without_signer_role(admin, signer1)
    assert signer1.get("/api/signed/documents").status_code == 403
    assert signer1.get("/api/signed/export.zip").status_code == 403
    assert admin.get("/api/signed/documents").status_code == 200


def test_the_zip_holds_one_folder_per_campaign_and_indexes_what_is_left(
    tmp_path, mock_oidc_base_url
):
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    one, two = get_user_id(signer1), get_user_id(signer2)
    first, first_version = launch(operator, "Charte", [one, two])
    second, second_version = launch(operator, "=PSSI()", [one])  # a title a spreadsheet would run
    sign(signer1, first_version)
    sign(signer1, second_version)

    response = operator.get("/api/signed/export.zip")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = archive.namelist()
    pdfs = [n for n in names if n.endswith(".pdf")]
    assert len(pdfs) == 2 and all("/" in n for n in pdfs)
    assert {"index-signes.csv", "reste-a-signer.csv"} <= set(names)
    assert all(archive.read(n).startswith(b"%PDF") for n in pdfs)
    # No path can escape the archive, whatever the title.
    assert not any(n.startswith("/") or ".." in n.split("/") for n in names)

    signed_rows = list(
        csv.reader(io.StringIO(archive.read("index-signes.csv").decode("utf-8-sig")))
    )
    assert len(signed_rows) == 3  # header + 2
    assert not any(cell.startswith("=") for row in signed_rows for cell in row)
    left = list(csv.reader(io.StringIO(archive.read("reste-a-signer.csv").decode("utf-8-sig"))))
    assert len(left) == 2 and left[1][1] == "Charte"

    only_first = operator.get("/api/signed/export.zip", params={"campaign_ids": [first]})
    assert (
        len(
            [
                n
                for n in zipfile.ZipFile(io.BytesIO(only_first.content)).namelist()
                if n.endswith(".pdf")
            ]
        )
        == 1
    )
    assert operator.get("/api/signed/export.zip", params={"q": "inconnu"}).status_code == 404
