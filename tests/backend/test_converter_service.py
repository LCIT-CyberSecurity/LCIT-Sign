"""The isolated converter's own rules: what it accepts, never the client's file name, one
conversion's failure never leaves files behind."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# backend/converter/app.py shares its name with the mock SSO's app.py: loaded by path, under
# its own name.
_spec = importlib.util.spec_from_file_location(
    "converter_app", Path(__file__).resolve().parents[2] / "backend" / "converter" / "app.py"
)
converter_app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(converter_app)


@pytest.fixture
def service(monkeypatch, tmp_path):
    monkeypatch.setattr(converter_app, "WORKDIR", str(tmp_path))
    seen: dict = {}

    def fake_soffice(source: Path, outdir: Path) -> None:
        seen["source"] = source.name
        seen["data"] = source.read_bytes()
        (outdir / "input.pdf").write_bytes(b"%PDF-1.4 converted")

    monkeypatch.setattr(converter_app, "run_soffice", fake_soffice)
    return TestClient(converter_app.app), seen, tmp_path


def post(client, name, data=b"contenu"):
    return client.post("/convert", files={"file": (name, data, "application/octet-stream")})


def test_it_returns_the_pdf_and_never_uses_the_clients_file_name(service):
    client, seen, tmp_path = service
    response = post(client, "../../etc/passwd.docx")
    assert response.status_code == 200 and response.content.startswith(b"%PDF-")
    assert seen["source"] == "input.docx" and seen["data"] == b"contenu"
    assert list(tmp_path.iterdir()) == []  # the work folder is gone, whatever happened


@pytest.mark.parametrize("name", ["a.exe", "a.pdf", "a.docm", "a.xlsx", "a"])
def test_it_only_converts_the_three_document_types(service, name):
    client, seen, _ = service
    assert post(client, name).status_code == 400
    assert "source" not in seen


def test_empty_and_oversized_files_are_refused(service, monkeypatch):
    client, _, _ = service
    assert post(client, "a.docx", b"").status_code == 400
    monkeypatch.setattr(converter_app, "MAX_BYTES", 10)
    assert post(client, "a.docx", b"x" * 11).status_code == 413


def test_a_failed_or_slow_conversion_is_reported_and_cleaned_up(service, monkeypatch):
    client, _, tmp_path = service

    def fails(source, outdir):
        raise subprocess.CalledProcessError(1, "soffice")

    monkeypatch.setattr(converter_app, "run_soffice", fails)
    assert post(client, "a.docx").status_code == 422

    def too_slow(source, outdir):
        raise subprocess.TimeoutExpired("soffice", 60)

    monkeypatch.setattr(converter_app, "run_soffice", too_slow)
    assert post(client, "a.docx").status_code == 504

    monkeypatch.setattr(converter_app, "run_soffice", lambda source, outdir: None)  # no PDF made
    assert post(client, "a.docx").status_code == 422
    assert list(tmp_path.iterdir()) == []


def test_libreoffice_is_started_with_macros_off_and_no_shell(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"], captured["kwargs"] = command, kwargs
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(converter_app.subprocess, "run", fake_run)
    source = tmp_path / "input.docx"
    source.write_bytes(b"x")
    converter_app.run_soffice(source, tmp_path)
    assert captured["command"][0].endswith("soffice") and "--headless" in captured["command"]
    assert captured["kwargs"].get("shell") is not True and captured["kwargs"]["timeout"] > 0
    assert "HOME" in captured["kwargs"]["env"] and "DATABASE" not in str(captured["kwargs"]["env"])
    profile = (tmp_path / "profile" / "user" / "registrymodifications.xcu").read_text()
    assert "MacroSecurityLevel" in profile and "DisableMacrosExecution" in profile
