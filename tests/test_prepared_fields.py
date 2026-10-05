from __future__ import annotations

import uuid
from io import BytesIO

from PIL import Image
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from test_signatures import setup_operator_and_signer

from lcit_sign.models.signature import Signature

MASTER = "test-master-key-not-for-production-use"


def pdf_bytes(pages: int = 2) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def png_bytes() -> bytes:
    out = BytesIO()
    Image.new("RGB", (120, 60), (101, 69, 155)).save(out, "PNG")
    return out.getvalue()


def upload(operator, title="Contrat", pages=2) -> str:
    created = operator.post(
        "/api/documents",
        data={"title": title, "version_label": "1.0"},
        files={"file": ("c.pdf", pdf_bytes(pages), "application/pdf")},
    ).json()
    return created["versions"][0]["id"]


def element(kind, **kw):
    return {"page": 1, "x": 0.1, "y": 0.1, "width": 0.3, "height": 0.05, "kind": kind, **kw}


def setup(tmp_path, oidc):
    return setup_operator_and_signer(tmp_path, oidc, master_key=MASTER)


def test_operator_places_elements_on_a_draft_and_reads_them_back(tmp_path, mock_oidc_base_url):
    app, operator, signer, admin = setup(tmp_path, mock_oidc_base_url)
    version_id = upload(operator)

    pages = operator.get(f"/api/documents/versions/{version_id}/pages").json()
    assert [(p["number"], p["width"], p["height"]) for p in pages] == [
        (1, 612.0, 792.0), (2, 612.0, 792.0)]

    saved = operator.put(
        f"/api/documents/versions/{version_id}/fields",
        json={"fields": [
            element("SIGNATURE", label="Signature"),
            element("DATE", y=0.2),
            element("TEXT", page=2, y=0.5, label="Fonction", group_key="fonction"),
        ]},
    )
    assert saved.status_code == 200, saved.text
    body = operator.get(f"/api/documents/versions/{version_id}/fields").json()
    assert body["editable"] is True
    assert [f["kind"] for f in body["fields"]] == ["SIGNATURE", "DATE", "TEXT"]
    assert body["fields"][0]["automatic"] is True and body["fields"][2]["automatic"] is False

    # Saving again replaces the set (the editor sends the whole page layout).
    operator.put(f"/api/documents/versions/{version_id}/fields", json={"fields": []})
    assert operator.get(f"/api/documents/versions/{version_id}/fields").json()["fields"] == []


def test_impossible_elements_are_refused_and_only_staff_can_prepare(tmp_path, mock_oidc_base_url):
    app, operator, signer, admin = setup(tmp_path, mock_oidc_base_url)
    version_id = upload(operator, pages=1)
    url = f"/api/documents/versions/{version_id}/fields"
    assert operator.put(url, json={"fields": [element("TEXT", page=3)]}).status_code == 422
    off_page = {"fields": [element("TEXT", x=0.9, width=0.3)]}
    assert operator.put(url, json=off_page).status_code == 422
    assert operator.put(url, json={"fields": [element("BOGUS")]}).status_code == 422
    assert signer.put(url, json={"fields": []}).status_code == 403
    assert signer.get(url).status_code == 403
    assert signer.get(f"/api/documents/versions/{version_id}/pages").status_code == 403


def test_elements_are_frozen_when_the_version_is_published(tmp_path, mock_oidc_base_url):
    app, operator, signer, admin = setup(tmp_path, mock_oidc_base_url)
    version_id = upload(operator)
    url = f"/api/documents/versions/{version_id}/fields"
    operator.put(url, json={"fields": [element("DATE")]})
    assert operator.post(f"/api/documents/versions/{version_id}/publish").status_code == 200
    frozen = operator.put(url, json={"fields": []})
    assert frozen.status_code == 409
    got = operator.get(url).json()
    assert got["editable"] is False and len(got["fields"]) == 1


def test_signing_stamps_automatic_and_typed_elements_and_the_proof_covers_them(
    tmp_path, mock_oidc_base_url
):
    app, operator, signer, admin = setup(tmp_path, mock_oidc_base_url)
    version_id = upload(operator)
    operator.put(
        f"/api/documents/versions/{version_id}/fields",
        json={"fields": [
            element("SIGNATURE", x=0.1, y=0.8, width=0.3, height=0.06),
            element("DATE", x=0.5, y=0.8, width=0.2, height=0.04),
            element("TEXT", page=2, y=0.3, width=0.4, height=0.04, label="Fonction"),
        ]},
    )
    operator.post(f"/api/documents/versions/{version_id}/publish")

    form = signer.get(f"/api/documents/versions/{version_id}/signing-form").json()
    assert [f["label"] for f in form["inputs"]] == ["Fonction"]
    assert {f["kind"] for f in form["automatic"]} == {"SIGNATURE", "DATE"}
    text_id = form["inputs"][0]["id"]

    sign_url = f"/api/documents/versions/{version_id}/sign"
    missing = signer.post(sign_url, json={"consent": True})
    assert missing.status_code == 422 and "Fonction" in missing.text
    assert signer.post(sign_url, json={"consent": True, "values": {"zzz": "x"}}).status_code == 422

    signed = signer.post(sign_url, json={"consent": True, "values": {text_id: "Directeur général"}})
    assert signed.status_code == 201, signed.text
    signature_id = signed.json()["id"]

    pdf = signer.get(f"/api/signatures/{signature_id}/signed-pdf").content
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 3  # original pages + the attestation
    page1, page2 = reader.pages[0].extract_text(), reader.pages[1].extract_text()
    assert "Directeur général" in page2
    assert signer.get("/api/auth/me").json()["display_name"].split()[0] in page1

    evidence = signer.get(f"/api/signatures/{signature_id}/evidence").json()
    assert "fields_sha256" in evidence and len(evidence["field_values"]) == 3
    assert signer.get(f"/api/signatures/{signature_id}/verify").json()["valid"] is True

    # What was stamped is part of the proof: change it and verification fails.
    with app.state.session_factory() as db:
        row = db.execute(
            select(Signature).where(Signature.id == uuid.UUID(signature_id))
        ).scalar_one()
        tampered = [dict(v) for v in row.field_values]
        tampered[0]["x"] = 0.9
        row.field_values = tampered
        db.commit()
    verdict = signer.get(f"/api/signatures/{signature_id}/verify").json()
    assert verdict["valid"] is False and verdict["checks"]["evidence_hash"] is False


def test_a_value_typed_once_fills_every_element_of_the_group_when_signing(
    tmp_path, mock_oidc_base_url
):
    app, operator, signer, admin = setup(tmp_path, mock_oidc_base_url)
    version_id = upload(operator)
    operator.put(
        f"/api/documents/versions/{version_id}/fields",
        json={"fields": [
            element("TEXT", page=1, label="Société", group_key="societe"),
            element("TEXT", page=2, label="Société", group_key="societe"),
        ]},
    )
    operator.post(f"/api/documents/versions/{version_id}/publish")
    inputs = signer.get(f"/api/documents/versions/{version_id}/signing-form").json()["inputs"]
    assert len(inputs) == 2
    signed = signer.post(
        f"/api/documents/versions/{version_id}/sign",
        json={"consent": True, "values": {inputs[0]["id"]: "LCIT"}},
    )
    assert signed.status_code == 201, signed.text
    raw = signer.get(f"/api/signatures/{signed.json()['id']}/signed-pdf").content
    pdf = PdfReader(BytesIO(raw))
    assert "LCIT" in pdf.pages[0].extract_text() and "LCIT" in pdf.pages[1].extract_text()


def test_a_document_without_prepared_elements_signs_exactly_as_before(tmp_path, mock_oidc_base_url):
    app, operator, signer, admin = setup(tmp_path, mock_oidc_base_url)
    version_id = upload(operator, pages=1)
    operator.post(f"/api/documents/versions/{version_id}/publish")
    signed = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert signed.status_code == 201
    evidence = signer.get(f"/api/signatures/{signed.json()['id']}/evidence").json()
    assert "fields_sha256" not in evidence  # the field set of old signatures is untouched
    assert signer.get(f"/api/signatures/{signed.json()['id']}/verify").json()["valid"] is True


def test_logo_element_needs_the_company_logo_before_publishing_and_is_stamped(
    tmp_path, mock_oidc_base_url
):
    app, operator, signer, admin = setup(tmp_path, mock_oidc_base_url)
    version_id = upload(operator, pages=1)
    operator.put(
        f"/api/documents/versions/{version_id}/fields",
        json={"fields": [element("LOGO", x=0.1, y=0.05, width=0.25, height=0.1)]},
    )
    blocked = operator.post(f"/api/documents/versions/{version_id}/publish")
    assert blocked.status_code == 409 and "logo" in blocked.text.lower()

    # Only an administrator configures it, and only a real image is accepted.
    files = {"file": ("logo.png", png_bytes(), "image/png")}
    assert operator.put("/api/admin/branding/logo", files=files).status_code == 403
    fake = {"file": ("logo.png", b"<svg onload=alert(1)>", "image/png")}
    assert admin.put("/api/admin/branding/logo", files=fake).status_code == 422
    assert admin.put("/api/admin/branding/logo", files=files).status_code == 200
    assert signer.get("/api/branding").json()["has_logo"] is True
    assert signer.get("/api/branding/logo").headers["content-type"] == "image/png"

    assert operator.post(f"/api/documents/versions/{version_id}/publish").status_code == 200
    signed = signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True})
    assert signed.status_code == 201, signed.text
    raw = signer.get(f"/api/signatures/{signed.json()['id']}/signed-pdf").content
    pdf = PdfReader(BytesIO(raw))
    assert len(list(pdf.pages[0].images)) == 1

    assert admin.delete("/api/admin/branding/logo").status_code == 200
    assert signer.get("/api/branding").json()["has_logo"] is False
