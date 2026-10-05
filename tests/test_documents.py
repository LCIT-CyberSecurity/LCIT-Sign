from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from test_auth_flow import login_as, make_app

from lcit_sign import models  # noqa: F401 - registers tables on Base.metadata
from lcit_sign.database import Base


def make_minimal_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_js_tainted_pdf_bytes() -> bytes:
    """A structurally valid PDF with a `/JavaScript` marker in a comment —
    valid enough to parse, but must still be rejected as active content.
    """
    pdf_bytes = make_minimal_pdf_bytes()
    header_end = pdf_bytes.index(b"\n") + 1
    return pdf_bytes[:header_end] + b"%/JavaScript test marker\n" + pdf_bytes[header_end:]


def setup_operator(tmp_path, mock_oidc_base_url, **overrides):
    """Bootstrap an app, log in the ADMIN and a second OPERATOR user, and
    return (app, operator_client) ready to exercise the documents API.

    A single TestClient (`primary`) is entered as a context manager to
    trigger the app's lifespan startup exactly once — that's what populates
    `app.state.engine`/`storage` — and is deliberately left open (not
    `__exit__`-ed) for the rest of the test so that state stays valid while
    `operator_client`, a second TestClient with its own cookie jar sharing
    the same already-initialized `app`, keeps making requests.
    """
    app = make_app(tmp_path, mock_oidc_base_url, **overrides)
    primary = TestClient(app)
    primary.__enter__()
    Base.metadata.create_all(app.state.engine)

    login_as(primary, mock_oidc_base_url, sub="u-direction-1")  # bootstrap ADMIN

    operator_client = TestClient(app)
    login_as(operator_client, mock_oidc_base_url, sub="u-sales-1")  # plain user, no roles
    operator_user_id = operator_client.get("/api/auth/me").json()["id"]

    grant_response = primary.post(
        f"/api/admin/users/{operator_user_id}/roles", json={"role": "OPERATOR"}
    )
    assert grant_response.status_code == 201, grant_response.text

    return app, operator_client


def test_create_publish_and_download_document(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url)
    pdf_bytes = make_minimal_pdf_bytes()

    create_response = operator.post(
        "/api/documents",
        data={"title": "Charte informatique", "version_label": "1.0"},
        files={"file": ("charte.pdf", pdf_bytes, "application/pdf")},
    )
    assert create_response.status_code == 201, create_response.text
    document = create_response.json()
    assert document["title"] == "Charte informatique"
    assert len(document["versions"]) == 1
    version = document["versions"][0]
    assert version["status"] == "DRAFT"

    publish_response = operator.post(f"/api/documents/versions/{version['id']}/publish")
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "PUBLISHED"

    content_response = operator.get(f"/api/documents/versions/{version['id']}/content")
    assert content_response.status_code == 200
    assert content_response.content == pdf_bytes
    assert content_response.headers["content-type"] == "application/pdf"


def test_new_version_supersedes_the_previous_published_one(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url)
    pdf_bytes = make_minimal_pdf_bytes()

    document = operator.post(
        "/api/documents",
        data={"title": "Politique RH", "version_label": "1.0"},
        files={"file": ("policy.pdf", pdf_bytes, "application/pdf")},
    ).json()
    v1_id = document["versions"][0]["id"]
    operator.post(f"/api/documents/versions/{v1_id}/publish")

    v2 = operator.post(
        f"/api/documents/{document['id']}/versions",
        data={"version_label": "2.0"},
        files={"file": ("policy.pdf", pdf_bytes, "application/pdf")},
    ).json()
    operator.post(f"/api/documents/versions/{v2['id']}/publish")

    detail = operator.get(f"/api/documents/{document['id']}").json()
    statuses = {v["id"]: v["status"] for v in detail["versions"]}
    assert statuses[v1_id] == "SUPERSEDED"
    assert statuses[v2["id"]] == "PUBLISHED"


def test_publishing_a_non_draft_version_is_rejected(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url)
    pdf_bytes = make_minimal_pdf_bytes()
    document = operator.post(
        "/api/documents",
        data={"title": "Doc", "version_label": "1.0"},
        files={"file": ("doc.pdf", pdf_bytes, "application/pdf")},
    ).json()
    version_id = document["versions"][0]["id"]
    operator.post(f"/api/documents/versions/{version_id}/publish")

    second_publish = operator.post(f"/api/documents/versions/{version_id}/publish")
    assert second_publish.status_code == 409


def test_non_pdf_upload_is_rejected(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url)
    response = operator.post(
        "/api/documents",
        data={"title": "Fake", "version_label": "1.0"},
        files={"file": ("fake.pdf", b"not actually a pdf", "application/pdf")},
    )
    assert response.status_code == 400


def test_wrong_extension_is_rejected(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url)
    pdf_bytes = make_minimal_pdf_bytes()
    response = operator.post(
        "/api/documents",
        data={"title": "Doc", "version_label": "1.0"},
        files={"file": ("doc.txt", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 400


def test_oversized_upload_is_rejected(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url, max_upload_size_mb=1)
    oversized = b"%PDF-1.4\n" + (b"0" * (2 * 1024 * 1024))
    response = operator.post(
        "/api/documents",
        data={"title": "Big", "version_label": "1.0"},
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )
    assert response.status_code == 400


def test_pdf_with_javascript_marker_is_rejected(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url)
    response = operator.post(
        "/api/documents",
        data={"title": "Tainted", "version_label": "1.0"},
        files={"file": ("tainted.pdf", make_js_tainted_pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 400
    assert "active content" in response.json()["detail"]


def test_signer_without_role_cannot_manage_documents(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)
        login_as(client, mock_oidc_base_url, sub="u-rh-1")  # no roles granted

        response = client.post(
            "/api/documents",
            data={"title": "Doc", "version_label": "1.0"},
            files={"file": ("doc.pdf", make_minimal_pdf_bytes(), "application/pdf")},
        )
        assert response.status_code == 403
        assert client.get("/api/documents").status_code == 403


def test_unauthenticated_cannot_list_documents(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)
        assert client.get("/api/documents").status_code == 401


def test_document_metadata_is_stored_and_listed(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url)
    created = operator.post(
        "/api/documents",
        data={
            "title": "Charte IA",
            "version_label": "1.0",
            "description": "Usage de l'IA générative",
            "category": " Sécurité ",
        },
        files={"file": ("charte.pdf", make_minimal_pdf_bytes(), "application/pdf")},
    )
    assert created.status_code == 201, created.text
    assert created.json()["description"] == "Usage de l'IA générative"
    assert created.json()["category"] == "Sécurité"  # trimmed
    listed = operator.get("/api/documents").json()
    assert listed[0]["category"] == "Sécurité"

    bare = operator.post(
        "/api/documents",
        data={"title": "Sans métadonnées"},
        files={"file": ("a.pdf", make_minimal_pdf_bytes(), "application/pdf")},
    )
    assert bare.status_code == 201 and bare.json()["category"] == ""
    too_long = operator.post(
        "/api/documents",
        data={"title": "x", "category": "c" * 101},
        files={"file": ("a.pdf", make_minimal_pdf_bytes(), "application/pdf")},
    )
    assert too_long.status_code == 422
