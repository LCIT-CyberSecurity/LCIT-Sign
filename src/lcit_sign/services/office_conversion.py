"""Word / LibreOffice documents as input: checked here, converted to PDF by the isolated
converter (a container of its own, no network, no database), and kept as a source file with
its hash next to the PDF that gets signed.

What is signed is always the PDF: its hash is the document's hash in the proof. The source
file is kept so that what the PDF was made from is never lost.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

import httpx

OFFICE_EXTENSIONS = (".docx", ".odt", ".doc")
SOURCES_BUCKET = "sources"

_ZIP = b"PK\x03\x04"
_OLE = bytes.fromhex("D0CF11E0A1B11AE1")
MAX_ENTRIES = 5000
MAX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024
# Where a document keeps its macros: refused outright, never opened to look.
_MACRO_MARKERS = ("vbaproject.bin", "macrosheets/", "basic/", "scripts/")


class ConversionError(Exception):
    """A document that cannot be converted; the message is for the person who uploaded it."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Converted:
    pdf: bytes
    source: bytes
    extension: str


def extension_of(filename: str) -> str | None:
    lowered = filename.lower()
    return next((ext for ext in OFFICE_EXTENSIONS if lowered.endswith(ext)), None)


def check_source(extension: str, data: bytes, *, max_bytes: int) -> None:
    """What can be refused without opening the document: size, real type, a zip that would
    explode, macros."""
    if not data:
        raise ConversionError("Le fichier est vide.")
    if len(data) > max_bytes:
        raise ConversionError(f"Le fichier dépasse la limite de {max_bytes // (1024 * 1024)} Mo.")
    if extension == ".doc":
        if not data.startswith(_OLE):
            raise ConversionError("Ce fichier n'est pas un document Word (.doc) valide.")
        return
    if not data.startswith(_ZIP):
        raise ConversionError("Ce fichier n'est pas un document valide.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            total = sum(e.file_size for e in entries)
            if len(entries) > MAX_ENTRIES or total > MAX_UNCOMPRESSED_BYTES:
                raise ConversionError("Ce document est anormalement volumineux une fois ouvert.")
            names = [e.filename.lower() for e in entries]
    except zipfile.BadZipFile:
        raise ConversionError("Ce fichier n'est pas un document valide.") from None
    # The marker of a real document of this type, so a renamed archive is not taken for one.
    if extension == ".docx" and "word/document.xml" not in names:
        raise ConversionError("Ce fichier n'est pas un document Word (.docx) valide.")
    if extension == ".odt" and "content.xml" not in names:
        raise ConversionError("Ce fichier n'est pas un document LibreOffice (.odt) valide.")
    if any(marker in name for name in names for marker in _MACRO_MARKERS):
        raise ConversionError(
            "Ce document contient des macros, ce qui n'est pas autorisé : "
            "enregistrez-le sans macros, ou en PDF."
        )


def convert_to_pdf(
    client: httpx.Client, base_url: str, extension: str, data: bytes
) -> bytes:
    """Ask the isolated converter. Sent under a fixed name: the client's own is never used."""
    if not base_url:
        raise ConversionError(
            "La conversion des fichiers Word et LibreOffice n'est pas activée sur ce serveur : "
            "déposez un PDF.",
            status=503,
        )
    try:
        response = client.post(
            f"{base_url.rstrip('/')}/convert",
            files={"file": (f"document{extension}", data, "application/octet-stream")},
        )
    except httpx.HTTPError:
        raise ConversionError(
            "Le service de conversion ne répond pas pour le moment : réessayez, ou déposez un PDF.",
            status=502,
        ) from None
    if response.status_code == 200 and response.content.startswith(b"%PDF-"):
        return response.content
    if response.status_code in (422, 504):
        raise ConversionError(
            "Ce document n'a pas pu être converti en PDF (fichier abîmé, protégé par un mot de "
            "passe, ou trop long à traiter). Enregistrez-le en PDF et déposez le PDF."
        )
    raise ConversionError("La conversion a échoué : déposez un PDF.", status=502)
