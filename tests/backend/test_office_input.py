"""Word / LibreOffice files as input: checked, converted by the isolated converter, kept as a
source next to the PDF that is signed."""
from __future__ import annotations

import hashlib
import io
import zipfile

import httpx
import pytest
from test_campaigns import setup_campaign_fixture
from test_documents import make_minimal_pdf_bytes

from lcit_sign.api.documents import get_converter_client
from lcit_sign.services.office_conversion import SOURCES_BUCKET


def docx(extra: dict[str, bytes] | None = None, body: bool = True) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        if body:
            archive.writestr("word/document.xml", "<w:document/>")
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return out.getvalue()


def odt() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr("content.xml", "<office:document-content/>")
    return out.getvalue()


OLE = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 600


class FakeConverter:
    def __init__(self, status=200, content=None) -> None:
        self.status, self.content = status, content
        self.calls: list[tuple[str, int]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/convert"
        body = request.content
        # The client's own file name never reaches the converter.
        name = body.split(b'filename="')[1].split(b'"')[0].decode()
        self.calls.append((name, len(body)))
        if self.status != 200:
            return httpx.Response(self.status, json={"detail": "x"})
        return httpx.Response(200, content=self.content or make_minimal_pdf_bytes())


def setup(tmp_path, oidc, converter, url="http://converter:8090"):
    app, admin, operator, *_ = setup_campaign_fixture(tmp_path, oidc, converter_url=url)

    def client():
        with httpx.Client(transport=httpx.MockTransport(converter)) as c:
            yield c

    app.dependency_overrides[get_converter_client] = client
    return app, operator


def upload(operator, name, data, title="Charte", content_type="application/octet-stream"):
    return operator.post(
        "/api/documents",
        data={"title": title, "version_label": "1.0"},
        files={"file": (name, data, content_type)},
    )


@pytest.mark.parametrize(("name", "data"), [("charte.docx", docx()), ("charte.odt", odt()),
                                             ("charte.doc", OLE)])
def test_a_word_or_libreoffice_file_becomes_a_pdf_and_keeps_its_source(
    tmp_path, mock_oidc_base_url, name, data
):
    converter = FakeConverter()
    app, operator = setup(tmp_path, mock_oidc_base_url, converter)
    response = upload(operator, name, data)
    assert response.status_code == 201, response.text
    version = response.json()["versions"][0]
    pdf = make_minimal_pdf_bytes()
    # What is signed is the PDF (its hash is the document's hash); the source is kept, hashed.
    assert version["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert version["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert version["original_filename"] == name and version["mime_type"] == "application/pdf"
    assert converter.calls and converter.calls[0][0].startswith("document.")
    assert name not in converter.calls[0][0]
    storage = app.state.storage
    import uuid
    version_id = uuid.UUID(version["id"])
    extension = "." + name.rsplit(".", 1)[1]
    assert storage.read(SOURCES_BUCKET, version_id, extension) == data
    assert storage.read("documents", version_id, ".pdf") == pdf


def test_the_pdf_is_served_as_usual_and_a_new_version_can_come_from_word(
    tmp_path, mock_oidc_base_url
):
    app, operator = setup(tmp_path, mock_oidc_base_url, FakeConverter())
    pdf = make_minimal_pdf_bytes()
    created = upload(operator, "charte.pdf", pdf, content_type="application/pdf")
    assert created.status_code == 201 and created.json()["versions"][0]["source_sha256"] is None
    document_id = created.json()["id"]
    newer = operator.post(
        f"/api/documents/{document_id}/versions",
        data={"version_label": "2.0"},
        files={"file": ("charte-v2.docx", docx(), "application/octet-stream")},
    )
    assert newer.status_code == 201, newer.text
    assert newer.json()["source_sha256"] is not None


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("macro.docx", docx({"word/vbaProject.bin": b"x"}), "macros"),
        ("faux.docx", b"juste du texte", "pas un document"),
        ("renomme.docx", docx(body=False), "pas un document Word"),
        ("faux.doc", b"texte" * 200, "pas un document Word"),
        ("vide.docx", b"", "vide"),
    ],
)
def test_a_document_that_cannot_be_trusted_is_refused_before_conversion(
    tmp_path, mock_oidc_base_url, name, data, message
):
    converter = FakeConverter()
    app, operator = setup(tmp_path, mock_oidc_base_url, converter)
    response = upload(operator, name, data)
    assert response.status_code == 400 and message in response.text
    assert converter.calls == []  # nothing dangerous ever reached the converter


def test_a_zip_that_explodes_is_refused(tmp_path, mock_oidc_base_url):
    converter = FakeConverter()
    app, operator = setup(tmp_path, mock_oidc_base_url, converter)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"0" * (320 * 1024 * 1024))
    response = upload(operator, "bombe.docx", out.getvalue())
    assert response.status_code == 400 and "volumineux" in response.text
    assert converter.calls == []


def test_other_file_types_are_still_refused(tmp_path, mock_oidc_base_url):
    app, operator = setup(tmp_path, mock_oidc_base_url, FakeConverter())
    for name in ("script.exe", "feuille.xlsx", "macro.docm", "image.png", "notes.txt"):
        assert upload(operator, name, b"MZ" + b"\x00" * 100).status_code == 400, name


def test_without_a_converter_only_pdfs_are_accepted_and_it_says_so(tmp_path, mock_oidc_base_url):
    app, operator = setup(tmp_path, mock_oidc_base_url, FakeConverter(), url="")
    response = upload(operator, "charte.docx", docx())
    assert response.status_code == 503 and "pas activée" in response.text
    ok = upload(operator, "charte.pdf", make_minimal_pdf_bytes(), content_type="application/pdf")
    assert ok.status_code == 201


@pytest.mark.parametrize(
    ("status", "content", "expected", "message"),
    [
        (422, None, 400, "n'a pas pu être converti"),
        (504, None, 400, "trop long"),
        (500, None, 502, "La conversion a échoué"),
        (200, b"<html>pas un pdf</html>", 502, "La conversion a échoué"),
    ],
)
def test_converter_failures_are_explained(
    tmp_path, mock_oidc_base_url, status, content, expected, message
):
    app, operator = setup(tmp_path, mock_oidc_base_url, FakeConverter(status, content))
    response = upload(operator, "charte.docx", docx())
    assert response.status_code == expected and message in response.text
    assert operator.get("/api/documents").json() == []  # nothing half-created


def test_what_the_converter_returns_is_checked_like_any_upload(tmp_path, mock_oidc_base_url):
    # A "PDF" with JavaScript in it, as a compromised converter might return.
    from test_documents import make_js_tainted_pdf_bytes

    app, operator = setup(
        tmp_path, mock_oidc_base_url, FakeConverter(content=make_js_tainted_pdf_bytes())
    )
    response = upload(operator, "charte.docx", docx())
    assert response.status_code == 400 and "JavaScript" in response.text


def test_deleting_a_version_deletes_its_source_too(tmp_path, mock_oidc_base_url):
    app, operator = setup(tmp_path, mock_oidc_base_url, FakeConverter())
    created = upload(operator, "charte.docx", docx()).json()
    version_id = created["versions"][0]["id"]
    assert operator.delete(f"/api/documents/versions/{version_id}").status_code == 200
    import uuid
    assert not app.state.storage.exists(SOURCES_BUCKET, uuid.UUID(version_id), ".docx")


def test_the_config_says_whether_conversion_is_available(tmp_path, mock_oidc_base_url):
    app, operator = setup(tmp_path, mock_oidc_base_url, FakeConverter())
    assert operator.get("/api/config").json()["office_conversion"] is True
    (tmp_path / "b").mkdir()
    app2, operator2 = setup(tmp_path / "b", mock_oidc_base_url, FakeConverter(), url="")
    assert operator2.get("/api/config").json()["office_conversion"] is False
