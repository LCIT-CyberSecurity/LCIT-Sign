from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter

from lcit_sign.models.document import FieldKind
from lcit_sign.services.field_stamping import (
    FieldError,
    PreparedField,
    fields_digest,
    page_sizes,
    resolve,
    stamp_fields,
    validate_layout,
)

SIGNED_AT = datetime(2026, 10, 5, 9, 59, 4, tzinfo=UTC)


def make_pdf(pages: int = 1, width: float = 612, height: float = 792, rotate: int = 0) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=width, height=height)
        if rotate:
            page.rotate(rotate)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def field(kind: FieldKind, **kw) -> PreparedField:
    values = {"id": kw.pop("id", f"f-{kind.value}"), "page": 1, "x": 0.1, "y": 0.1,
              "width": 0.3, "height": 0.05, "kind": kind}
    values.update(kw)
    return PreparedField(**values)


def resolve_all(fields, inputs=None, logo="a" * 64):
    return resolve(
        fields, signer_name="Cédric Di Cesare", signer_email="cedric@lcit.fr",
        signed_at=SIGNED_AT, inputs=inputs or {}, logo_sha256=logo,
    )


def positions(pdf: bytes, page: int = 0) -> dict[str, tuple[float, float]]:
    found: dict[str, tuple[float, float]] = {}

    def visit(text, cm, tm, font_dict, font_size):  # noqa: ANN001
        if text.strip():
            found[text.strip()] = (tm[4], tm[5])

    PdfReader(BytesIO(pdf)).pages[page].extract_text(visitor_text=visit)
    return found


def test_automatic_elements_take_their_values_from_the_signer_and_the_clock():
    fields = [field(FieldKind.DATE), field(FieldKind.FULL_NAME), field(FieldKind.EMAIL),
              field(FieldKind.SIGNATURE)]
    values = {r["kind"]: r["value"] for r in resolve_all(fields)}
    assert values == {
        "DATE": "05/10/2026",
        "FULL_NAME": "Cédric Di Cesare",
        "EMAIL": "cedric@lcit.fr",
        "SIGNATURE": "Cédric Di Cesare",
    }


def test_free_text_must_be_typed_when_required_and_may_be_left_when_optional():
    required = field(FieldKind.TEXT, id="t1", label="Fonction")
    optional = field(FieldKind.TEXT, id="t2", label="Remarque", required=False)
    with pytest.raises(FieldError, match="Fonction"):
        resolve_all([required, optional])
    resolved = resolve_all([required, optional], {"t1": "  Directeur  "})
    assert [(r["label"], r["value"]) for r in resolved] == [("Fonction", "Directeur")]


def test_inputs_for_unknown_or_automatic_elements_are_refused():
    date = field(FieldKind.DATE, id="d1")
    with pytest.raises(FieldError, match="do not exist"):
        resolve_all([date], {"nope": "x"})
    with pytest.raises(FieldError, match="automatically"):
        resolve_all([date], {"d1": "01/01/2000"})  # nobody types the date of signing


def test_a_value_typed_once_fills_every_element_of_its_group():
    a = field(FieldKind.TEXT, id="a", label="Société", group_key="societe", page=1)
    b = field(FieldKind.TEXT, id="b", label="Société", group_key="societe", page=2, y=0.5)
    resolved = resolve_all([a, b], {"a": "LCIT"})
    assert [r["value"] for r in resolved] == ["LCIT", "LCIT"]


def test_a_logo_element_needs_a_configured_logo():
    with pytest.raises(FieldError, match="logo"):
        resolve_all([field(FieldKind.LOGO)], logo=None)


def test_only_the_signers_own_role_is_resolved():
    first = field(FieldKind.DATE, id="d1", role=1)
    second = field(FieldKind.DATE, id="d2", role=2)
    assert [r["field_id"] for r in resolve_all([first, second])] == ["d1"]


@pytest.mark.parametrize(
    "bad",
    [
        field(FieldKind.TEXT, page=2),
        field(FieldKind.TEXT, x=-0.1),
        field(FieldKind.TEXT, x=0.9, width=0.3),
        field(FieldKind.TEXT, height=0),
        field(FieldKind.TEXT, role=0),
    ],
)
def test_layout_validation_refuses_impossible_elements(bad):
    with pytest.raises(FieldError):
        validate_layout([bad], page_count=1)
    validate_layout([field(FieldKind.TEXT)], page_count=1)


def test_stamped_text_lands_where_it_was_placed():
    pdf = make_pdf(2)
    fields = [
        field(FieldKind.DATE, id="d", x=0.25, y=0.20, width=0.2, height=0.04),
        field(FieldKind.FULL_NAME, id="n", page=2, x=0.5, y=0.5, width=0.3, height=0.04),
    ]
    stamped = stamp_fields(pdf, resolve_all(fields), None)
    page1, page2 = positions(stamped, 0), positions(stamped, 1)
    assert "05/10/2026" in page1 and "Cédric Di Cesare" in page2
    # x is a fraction of the width, from the left.
    assert page1["05/10/2026"][0] == pytest.approx(0.25 * 612, abs=3)
    # y is a fraction of the height from the TOP; PDF counts from the bottom.
    assert page1["05/10/2026"][1] == pytest.approx(792 - (0.20 + 0.04) * 792, abs=14)
    assert page2["Cédric Di Cesare"][0] == pytest.approx(0.5 * 612, abs=3)


def test_the_original_is_never_modified_and_a_stamp_less_document_is_returned_as_is():
    pdf = make_pdf()
    assert stamp_fields(pdf, [], None) == pdf
    before = bytes(pdf)
    stamp_fields(pdf, resolve_all([field(FieldKind.DATE)]), None)
    assert pdf == before


def test_a_rotated_page_is_stamped_where_it_looks_to_be():
    # 612x792 rotated 90° shows as a 792x612 landscape page.
    pdf = make_pdf(rotate=90)
    assert (page_sizes(pdf)[0].width, page_sizes(pdf)[0].height) == (792, 612)
    stamped = stamp_fields(
        pdf, resolve_all([field(FieldKind.DATE, x=0.1, y=0.1, width=0.2, height=0.05)]), None
    )
    reader = PdfReader(BytesIO(stamped))
    page = reader.pages[0]
    assert int(page.get("/Rotate", 0) or 0) % 360 == 0
    assert (float(page.mediabox.width), float(page.mediabox.height)) == (792, 612)
    x, y = positions(stamped)["05/10/2026"]
    assert x == pytest.approx(0.1 * 792, abs=3)
    assert y == pytest.approx(612 - 0.15 * 612, abs=14)


def test_logo_is_drawn_and_digest_covers_what_was_stamped():
    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (40, 20), (101, 69, 155)).save(image, "PNG")
    resolved = resolve_all([field(FieldKind.LOGO, width=0.2, height=0.1)])
    stamped = stamp_fields(make_pdf(), resolved, image.getvalue())
    page = PdfReader(BytesIO(stamped)).pages[0]
    assert len(list(page.images)) == 1

    digest = fields_digest(resolved)
    moved = [{**resolved[0], "x": 0.5}]
    assert fields_digest(moved) != digest
    assert fields_digest(resolved) == digest


def test_page_sizes_report_what_the_editor_must_draw():
    sizes = page_sizes(make_pdf(pages=3, width=300, height=400))
    assert len(sizes) == 3 and (sizes[0].width, sizes[0].height) == (300, 400)


def test_a_cropped_page_is_measured_and_stamped_by_its_crop_box():
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    from pypdf.generic import RectangleObject

    page.cropbox = RectangleObject([100, 100, 500, 700])  # 400 x 600 visible
    out = BytesIO()
    writer.write(out)
    pdf = out.getvalue()
    assert (page_sizes(pdf)[0].width, page_sizes(pdf)[0].height) == (400, 600)
    date_at_origin = field(FieldKind.DATE, x=0, y=0, width=0.5, height=0.05)
    stamped = stamp_fields(pdf, resolve_all([date_at_origin]), None)
    x, _ = positions(stamped)["05/10/2026"]
    assert x == pytest.approx(100, abs=3)  # the crop's left edge, not the media box's
