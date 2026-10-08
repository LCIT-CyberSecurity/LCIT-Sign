from __future__ import annotations

from fastapi.testclient import TestClient

from lcit_sign.app import create_app
from lcit_sign.config import Settings


def make_client() -> TestClient:
    settings = Settings(database_url="sqlite:///:memory:")
    return TestClient(create_app(settings))


def test_health_does_not_require_database() -> None:
    with make_client() as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_database_connectivity() -> None:
    with make_client() as client:
        response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_security_headers_are_present() -> None:
    with make_client() as client:
        response = client.get("/api/health")
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_secrets_can_be_read_from_files(tmp_path) -> None:
    from lcit_sign.config import Settings

    key_file = tmp_path / "master_key"
    key_file.write_text("key-from-file\n")
    settings = Settings(master_key="from-env", master_key_file=str(key_file))
    assert settings.master_key == "key-from-file"
    assert Settings(master_key="from-env").master_key == "from-env"
