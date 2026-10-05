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


def _pdf_with(mutate) -> bytes:
    """A PDF built with pypdf, then altered by `mutate(writer)`."""
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    mutate(writer)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_js_tainted_pdf_bytes() -> bytes:
    """A PDF whose document-level JavaScript runs when it is opened."""
    return _pdf_with(lambda w: w.add_js("app.alert('hello');"))


def make_pdf_with_open_action_view() -> bytes:
    """What Acrobat and other tools write routinely: an /OpenAction that only
    sets the initial view. Harmless, and must be accepted."""
    def mutate(writer: PdfWriter) -> None:
        from pypdf.generic import ArrayObject, NameObject

        page = writer.pages[0].indirect_reference
        writer._root_object[NameObject("/OpenAction")] = ArrayObject([page, NameObject("/Fit")])

    return _pdf_with(mutate)


def make_pdf_with_attachment() -> bytes:
    return _pdf_with(lambda w: w.add_attachment("payload.exe", b"MZ not really"))


def make_pdf_with_launch_action() -> bytes:
    def mutate(writer: PdfWriter) -> None:
        from pypdf.generic import DictionaryObject, NameObject, TextStringObject

        writer._root_object[NameObject("/OpenAction")] = DictionaryObject(
            {
                NameObject("/S"): NameObject("/Launch"),
                NameObject("/F"): TextStringObject("cmd.exe"),
            }
        )

    return _pdf_with(mutate)


def make_pdf_with_hyperlink_and_false_markers() -> bytes:
    """A normal PDF: a clickable link, and page data that happens to contain
    the byte patterns the old raw-bytes check mistook for scripts."""
    def mutate(writer: PdfWriter) -> None:
        from pypdf.annotations import Link

        writer.add_annotation(0, Link(rect=(5, 5, 60, 20), url="https://www.lcit.fr"))
        writer.pages[0][NameObject("/Note")] = TextStringObject("x /AA y /JS z /OpenAction w")

    from pypdf.generic import NameObject, TextStringObject  # noqa: F811

    return _pdf_with(mutate)


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


def _upload_status(operator, pdf: bytes):
    return operator.post(
        "/api/documents",
        data={"title": "Essai", "version_label": "1.0"},
        files={"file": ("essai.pdf", pdf, "application/pdf")},
    )


def test_pdf_with_javascript_is_rejected_and_the_reason_is_explained(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url)
    response = _upload_status(operator, make_js_tainted_pdf_bytes())
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "JavaScript" in detail and "Réexportez" in detail  # says what, and how to fix it


def test_other_active_constructs_are_rejected_too(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url)
    attached = _upload_status(operator, make_pdf_with_attachment())
    assert attached.status_code == 400 and "fichiers joints" in attached.json()["detail"]
    launch = _upload_status(operator, make_pdf_with_launch_action())
    assert launch.status_code == 400 and "lancement" in launch.json()["detail"]


def test_ordinary_pdfs_are_not_mistaken_for_scripts(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url)
    # An /OpenAction that only sets the initial view is routine.
    assert _upload_status(operator, make_pdf_with_open_action_view()).status_code == 201
    # Hyperlinks work, and the literal words /AA /JS /OpenAction in data are not code.
    assert _upload_status(operator, make_pdf_with_hyperlink_and_false_markers()).status_code == 201


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


def _upload(operator, title="À effacer", publish=False):
    created = operator.post(
        "/api/documents",
        data={"title": title, "version_label": "1.0"},
        files={"file": ("a.pdf", make_minimal_pdf_bytes(), "application/pdf")},
    ).json()
    version_id = created["versions"][0]["id"]
    if publish:
        assert operator.post(f"/api/documents/versions/{version_id}/publish").status_code == 200
    return created["id"], version_id


def test_an_unused_document_can_be_deleted_for_good(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url)
    document_id, version_id = _upload(operator)
    listed = operator.get("/api/documents").json()
    assert listed[0]["can_delete"] is True
    assert listed[0]["versions"][0]["can_delete"] is True

    import uuid as _uuid

    path = app.state.storage.path_for("documents", _uuid.UUID(version_id), ".pdf")
    assert path.exists()
    deleted = operator.delete(f"/api/documents/{document_id}")
    assert deleted.status_code == 200, deleted.text
    assert operator.get("/api/documents").json() == []
    assert not path.exists()  # the file goes too
    assert operator.get(f"/api/documents/{document_id}").status_code == 404
    audit = operator.get("/api/documents").status_code  # still reachable
    assert audit == 200


def test_deleting_the_last_version_removes_its_document(tmp_path, mock_oidc_base_url):
    app, operator = setup_operator(tmp_path, mock_oidc_base_url)
    document_id, version_id = _upload(operator, publish=True)
    result = operator.delete(f"/api/documents/versions/{version_id}")
    assert result.status_code == 200 and result.json()["document_removed"] is True
    assert operator.get(f"/api/documents/{document_id}").status_code == 404


def test_a_signed_version_cannot_be_deleted_only_archived(tmp_path, mock_oidc_base_url):
    from test_signatures import setup_operator_and_signer

    app, operator, signer, admin = setup_operator_and_signer(
        tmp_path, mock_oidc_base_url, master_key="test-master-key-not-for-production-use"
    )
    document_id, version_id = _upload(operator, "Signé", publish=True)
    assert signer.post(
        f"/api/documents/versions/{version_id}/sign", json={"consent": True}
    ).status_code == 201

    listed = operator.get("/api/documents").json()
    assert listed[0]["can_delete"] is False
    assert "signature" in listed[0]["versions"][0]["delete_blockers"][0]
    refused = operator.delete(f"/api/documents/versions/{version_id}")
    assert refused.status_code == 409 and "Archivez" in refused.text
    assert operator.delete(f"/api/documents/{document_id}").status_code == 409
    # The document and its proof are intact; archiving is the way out.
    assert operator.post(f"/api/documents/versions/{version_id}/archive").status_code == 200


def test_a_version_used_by_a_campaign_cannot_be_deleted_until_removed_from_it(
    tmp_path, mock_oidc_base_url
):
    from test_campaigns import setup_campaign_fixture

    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _, version_id = _upload(operator, "En campagne", publish=True)
    campaign = operator.post("/api/campaigns", json={"name": "Brouillon de campagne"}).json()
    operator.post(
        f"/api/campaigns/{campaign['id']}/documents", json={"document_version_id": version_id}
    )
    refused = operator.delete(f"/api/documents/versions/{version_id}")
    assert refused.status_code == 409 and "Brouillon de campagne" in refused.text

    removed = operator.delete(f"/api/campaigns/{campaign['id']}/documents/{version_id}")
    assert removed.status_code == 200 and removed.json()["document_version_ids"] == []
    assert operator.delete(f"/api/documents/versions/{version_id}").status_code == 200
    again = operator.delete(f"/api/campaigns/{campaign['id']}/documents/{version_id}")
    assert again.status_code == 404


def test_only_operators_and_admins_can_delete(tmp_path, mock_oidc_base_url):
    from test_campaigns import setup_campaign_fixture

    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    document_id, _ = _upload(operator, "Protégé")
    assert signer1.delete(f"/api/documents/{document_id}").status_code == 403
    assert admin.delete(f"/api/documents/{document_id}").status_code == 200
