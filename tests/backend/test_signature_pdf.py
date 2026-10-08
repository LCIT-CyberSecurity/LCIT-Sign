from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter

from lcit_sign.services.signature_pdf import append_signature_page, render_certificate_pdf

SIGNED_AT = datetime(2026, 10, 5, 9, 59, 4, tzinfo=UTC)
A4_WIDTH, A4_HEIGHT = 595.28, 841.89


def pdf_with_page(width: float, height: float) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def signed(original: bytes, **overrides):
    values = {
        "document_title": "Politique de signature",
        "version_label": "1.0",
        "display_name": "Cédric Di Cesare",
        "email": "cedric.dicesare@lcit.fr",
        "signed_at": SIGNED_AT,
        "consent_text": "J'atteste avoir pris connaissance de ce document.",
        "display_id": "SIG-64164F709501",
        "original_sha256": "a" * 64,
        **overrides,
    }
    return append_signature_page(original, **values)


@pytest.mark.parametrize("size", [(72, 72), (200, 200), (595, 842), (842, 595), (1200, 1700)])
def test_attestation_page_is_a_full_a4_whatever_the_document_size(size):
    result = PdfReader(BytesIO(signed(pdf_with_page(*size))))
    assert len(result.pages) == 2
    # The original page is untouched...
    assert float(result.pages[0].mediabox.width) == pytest.approx(size[0])
    assert float(result.pages[0].mediabox.height) == pytest.approx(size[1])
    # ... and the attestation is a proper A4 page, not a clipped copy of it.
    last = result.pages[-1]
    assert float(last.mediabox.width) == pytest.approx(A4_WIDTH, abs=1)
    assert float(last.mediabox.height) == pytest.approx(A4_HEIGHT, abs=1)


def test_attestation_page_carries_every_field_in_full():
    text = PdfReader(BytesIO(signed(pdf_with_page(72, 72)))).pages[-1].extract_text()
    for expected in (
        "Attestation de signature",
        "Politique de signature",
        "Cédric Di Cesare",
        "cedric.dicesare@lcit.fr",
        "05/10/2026",
        "SIG-64164F709501",
        "J'atteste avoir pris connaissance de ce document.",
    ):
        assert expected in text, expected
    # The 64-hex digest is wrapped, never cut: all of it is on the page.
    assert "a" * 64 in text.replace("\n", "").replace(" ", "")


def test_long_values_wrap_instead_of_running_off_the_page():
    title = "Politique de sécurité des systèmes d'information et de signature électronique " * 3
    consent = "Je soussigné atteste avoir lu, compris et accepté l'ensemble des clauses. " * 6
    name = "Anne-Sophie de la Tour d'Auvergne-Lauraguais-Montmorency"
    reader = PdfReader(BytesIO(signed(
        pdf_with_page(72, 72), document_title=title.strip(), consent_text=consent.strip(),
        display_name=name,
    )))
    text = " ".join(reader.pages[-1].extract_text().split())
    assert len(reader.pages) == 2
    # Every word of the long title and of the long consent text is present.
    for word in title.split() + consent.split():
        assert word in text, word
    assert name.split()[0] in text and name.split()[-1] in text

    # Nothing is drawn beyond the page: every glyph position stays inside the box.
    xs: list[float] = []
    def record(text: str, cm, tm, font_dict, font_size) -> None:  # noqa: ANN001
        if text.strip():
            xs.append(tm[4])

    reader.pages[-1].extract_text(visitor_text=record)
    assert xs and max(xs) < A4_WIDTH and min(xs) >= 0


def test_certificate_is_the_same_page_standalone():
    pdf = render_certificate_pdf(
        document_title="Charte", version_label="2.1", display_name="Alice Martin",
        email="alice@lcit-test.local", signed_at=SIGNED_AT,
        consent_text="J'atteste.", display_id="SIG-0000000001AB",
    )
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 1
    assert float(reader.pages[0].mediabox.width) == pytest.approx(A4_WIDTH, abs=1)
    assert "Alice Martin" in reader.pages[0].extract_text()
