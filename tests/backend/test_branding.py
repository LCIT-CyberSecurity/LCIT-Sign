"""The company logo: public to look at (the sign-in page shows it), admin only to change."""
from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from test_campaigns import setup_campaign_fixture


def png(width=120, height=60) -> bytes:
    out = BytesIO()
    Image.new("RGB", (width, height), (101, 69, 155)).save(out, "PNG")
    return out.getvalue()


def test_the_logo_can_be_seen_before_signing_in_and_changed_only_by_an_admin(
    tmp_path, mock_oidc_base_url
):
    app, admin, operator, signer, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    anonymous = TestClient(app)
    assert anonymous.get("/api/branding").json() == {"has_logo": False, "logo_sha256": None}
    assert anonymous.get("/api/branding/logo").status_code == 404

    files = {"file": ("logo.png", png(), "image/png")}
    assert anonymous.put("/api/admin/branding/logo", files=files).status_code == 401
    assert operator.put("/api/admin/branding/logo", files=files).status_code == 403
    assert signer.put("/api/admin/branding/logo", files=files).status_code == 403
    assert admin.put("/api/admin/branding/logo", files=files).status_code == 200

    status = anonymous.get("/api/branding").json()
    assert status["has_logo"] is True and len(status["logo_sha256"]) == 64
    image = anonymous.get("/api/branding/logo")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.headers["x-content-type-options"] == "nosniff"
    assert image.content == png()

    assert operator.delete("/api/admin/branding/logo").status_code == 403
    assert admin.delete("/api/admin/branding/logo").status_code == 200
    assert anonymous.get("/api/branding").json()["has_logo"] is False


def test_only_a_real_image_of_reasonable_size_becomes_the_logo(tmp_path, mock_oidc_base_url):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    put = lambda name, data, kind: admin.put(  # noqa: E731
        "/api/admin/branding/logo", files={"file": (name, data, kind)}
    )
    assert put("logo.png", b"<svg onload=alert(1)>", "image/png").status_code == 422
    assert put("logo.png", b"", "image/png").status_code == 422
    assert put("logo.png", png(8, 8), "image/png").status_code == 422  # too small
    assert put("logo.png", b"\x89PNG\r\n\x1a\n" + b"x" * 600_000, "image/png").status_code == 422
    assert put("logo.png", png(), "image/png").status_code == 200
