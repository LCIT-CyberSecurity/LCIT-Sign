"""Isolated converter: a Word / LibreOffice document in, a PDF out.

Runs in its own container with no network and no access to the database or to LCIT Sign's
files (see docker-compose.yml). It receives one file at a time, never uses the name the client
gave it, converts it with LibreOffice with macros and external links switched off, and returns
the PDF. LCIT Sign checks that PDF again as it would any upload.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response

MAX_BYTES = int(os.environ.get("CONVERTER_MAX_BYTES", 25 * 1024 * 1024))
TIMEOUT_SECONDS = int(os.environ.get("CONVERTER_TIMEOUT_SECONDS", 60))
WORKDIR = os.environ.get("CONVERTER_WORKDIR", tempfile.gettempdir())
ALLOWED = {".docx", ".odt", ".doc"}

# Two conversions at a time at most: LibreOffice is heavy, and a flood of uploads must not
# take the machine down.
_slots = asyncio.Semaphore(int(os.environ.get("CONVERTER_PARALLEL", 2)))

# A profile with macros refused outright and no automatic update of linked content.
_NS = (
    'xmlns:oor="http://openoffice.org/2001/registry" '
    'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
)


def _setting(path: str, name: str, value: str) -> str:
    return (
        f'<item oor:path="{path}"><prop oor:name="{name}" oor:op="fuse">'
        f"<value>{value}</value></prop></item>"
    )


_SCRIPTING = "/org.openoffice.Office.Common/Security/Scripting"
_PROFILE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    f"<oor:items {_NS}>\n"
    + "\n".join(
        [
            _setting(_SCRIPTING, "MacroSecurityLevel", "3"),
            _setting(_SCRIPTING, "DisableMacrosExecution", "true"),
            _setting("/org.openoffice.Office.Writer/Content/Update", "Link", "0"),
            _setting("/org.openoffice.Office.Common/Load", "UpdateDocMode", "0"),
        ]
    )
    + "\n</oor:items>\n"
)
SOFFICE = os.environ.get("SOFFICE_BIN", "/usr/bin/soffice")

app = FastAPI(title="LCIT Sign — document converter")


def run_soffice(source: Path, outdir: Path) -> None:
    """The one place LibreOffice is started (replaced by the tests)."""
    profile = outdir / "profile" / "user"
    profile.mkdir(parents=True)
    (profile / "registrymodifications.xcu").write_text(_PROFILE, encoding="utf-8")
    subprocess.run(  # noqa: S603 - fixed program, arguments built here, no shell
        [
            SOFFICE, "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nologo",
            "--nofirststartwizard", f"-env:UserInstallation=file://{outdir / 'profile'}",
            "--convert-to", "pdf", "--outdir", str(outdir), str(source),
        ],
        check=True,
        timeout=TIMEOUT_SECONDS,
        capture_output=True,
        cwd=outdir,
        env={"HOME": str(outdir), "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )


def _convert(data: bytes, extension: str) -> bytes:
    with tempfile.TemporaryDirectory(dir=WORKDIR) as work:
        outdir = Path(work)
        # Never the client's file name: nothing it says can reach a path.
        source = outdir / f"input{extension}"
        source.write_bytes(data)
        try:
            run_soffice(source, outdir)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "La conversion a pris trop de temps.") from None
        except (subprocess.CalledProcessError, OSError):
            raise HTTPException(422, "Ce document n'a pas pu être converti.") from None
        result = outdir / "input.pdf"
        if not result.exists():
            raise HTTPException(422, "Ce document n'a pas pu être converti.")
        return result.read_bytes()


@app.post("/convert")
async def convert(file: UploadFile = File(...)) -> Response:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED:
        raise HTTPException(400, "Type de fichier non pris en charge.")
    data = await file.read(MAX_BYTES + 1)
    if not data:
        raise HTTPException(400, "Fichier vide.")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Fichier trop volumineux.")
    async with _slots:
        pdf = await asyncio.to_thread(_convert, data, extension)
    return Response(content=pdf, media_type="application/pdf")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
