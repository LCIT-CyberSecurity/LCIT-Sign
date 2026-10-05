from __future__ import annotations

import re
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

PDF_MAGIC_BYTES = b"%PDF-"
_ACTIVE_CONTENT_PATTERN = re.compile(rb"/(JavaScript|JS|OpenAction|AA)\b")


class DocumentValidationError(ValueError):
    """Raised with a message safe to show the uploader directly."""


def validate_pdf_upload(filename: str, content_type: str, data: bytes, *, max_bytes: int) -> None:
    """Reject anything that is not a genuine, inert PDF (spec §40, §42).

    Checks run cheapest-first so an obviously wrong upload (bad extension)
    never pays for a full parse.
    """
    if not filename.lower().endswith(".pdf"):
        raise DocumentValidationError("Only .pdf files are accepted")

    if content_type != "application/pdf":
        raise DocumentValidationError("Only application/pdf uploads are accepted")

    if len(data) == 0:
        raise DocumentValidationError("Uploaded file is empty")
    if len(data) > max_bytes:
        raise DocumentValidationError(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")

    if not data.startswith(PDF_MAGIC_BYTES):
        raise DocumentValidationError("File does not have a valid PDF signature")

    try:
        reader = PdfReader(BytesIO(data))
        page_count = len(reader.pages)
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        raise DocumentValidationError("File is not a valid or readable PDF") from exc
    if page_count < 1:
        raise DocumentValidationError("PDF has no pages")

    if _ACTIVE_CONTENT_PATTERN.search(data):
        raise DocumentValidationError(
            "PDF contains active content (JavaScript or auto-run actions), which is not allowed"
        )
