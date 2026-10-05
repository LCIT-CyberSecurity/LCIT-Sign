from __future__ import annotations

import logging
from collections.abc import Iterator
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

logger = logging.getLogger(__name__)

PDF_MAGIC_BYTES = b"%PDF-"

# Actions a PDF can run on its own or on a click that reach beyond reading it.
# Plain navigation (GoTo, URI hyperlinks) is deliberately allowed: hyperlinks
# inside a document must keep working (spec §24).
_DANGEROUS_ACTIONS = {
    "/JavaScript": "du JavaScript",
    "/Launch": "une action de lancement de programme",
    "/SubmitForm": "un envoi de formulaire vers l'extérieur",
    "/ImportData": "une importation de données",
    "/GoToE": "un lien vers un fichier incorporé",
    "/GoToR": "un lien vers un autre fichier",
    "/Rendition": "un média intégré",
    "/Movie": "une vidéo intégrée",
    "/Sound": "un son intégré",
}
_DANGEROUS_SUBTYPES = {
    "/RichMedia": "un contenu multimédia interactif",
    "/Movie": "une vidéo intégrée",
    "/Sound": "un son intégré",
    "/3D": "un objet 3D interactif",
}
_MAX_OBJECTS = 200_000


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

    if reader.is_encrypted:
        raise DocumentValidationError(
            "Le PDF est protégé par mot de passe ou chiffré : retirez la protection puis réessayez"
        )
    found = find_active_content(reader)
    if found:
        raise DocumentValidationError(
            "Le PDF contient du contenu actif non autorisé : "
            + ", ".join(found)
            + ". Réexportez le document sans ces éléments (par exemple « Imprimer en PDF ») "
            "puis réessayez."
        )


def _name(value: object) -> str:
    return str(value) if value is not None else ""


def _dictionaries(obj: object) -> Iterator[DictionaryObject]:
    """`obj` and every dictionary written inline inside it (an /OpenAction is
    usually a direct child of the catalog, not an object of its own). Indirect
    references are not followed: each indirect object is visited on its own."""
    if isinstance(obj, DictionaryObject):
        yield obj
        for value in obj.values():
            yield from _dictionaries(value)
    elif isinstance(obj, ArrayObject):
        for value in obj:
            yield from _dictionaries(value)


def find_active_content(reader: PdfReader) -> list[str]:
    """What, structurally, in this PDF could act on its own — in plain words.

    Looks at the real objects of the file (including those packed in
    compressed object streams), not at the raw bytes: a bare `/OpenAction` that
    merely sets the initial view is ordinary and harmless, and byte patterns
    can turn up by chance inside compressed page data. Only genuinely active
    constructs are reported: JavaScript, program launches, outgoing form
    submissions, embedded media and attached files.
    """
    numbers: set[tuple[int, int]] = set()
    for generation, entries in reader.xref.items():
        numbers.update((int(n), int(generation)) for n in entries)
    for object_number in reader.xref_objStm:
        numbers.add((int(object_number), 0))

    found: list[str] = []

    def note(text: str) -> None:
        if text not in found:
            found.append(text)

    for index, (number, generation) in enumerate(sorted(numbers)):
        if index >= _MAX_OBJECTS:
            note("un nombre d'objets anormalement élevé")
            break
        try:
            obj = IndirectObject(number, generation, reader).get_object()
        except Exception:  # an unreadable object cannot be inspected; the file parsed otherwise
            logger.debug("skipping unreadable PDF object %s %s", number, generation)
            continue
        for node in _dictionaries(obj):
            action = _name(node.get("/S"))
            if action in _DANGEROUS_ACTIONS:
                note(_DANGEROUS_ACTIONS[action])
            if "/JS" in node:
                note("du JavaScript")
            subtype = _name(node.get("/Subtype"))
            if subtype in _DANGEROUS_SUBTYPES:
                note(_DANGEROUS_SUBTYPES[subtype])
            if _name(node.get("/Type")) == "/EmbeddedFile" or "/EF" in node:
                note("des fichiers joints")
    return found
