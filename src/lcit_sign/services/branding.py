from __future__ import annotations

import uuid
from io import BytesIO

from reportlab.lib.utils import ImageReader

from lcit_sign.services.storage import StorageService

BUCKET = "branding"
# One logo for the whole installation: a fixed object id in its own bucket.
LOGO_ID = uuid.UUID("00000000-0000-0000-0000-00000000106f")
MAX_LOGO_BYTES = 512 * 1024
_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"


class LogoError(ValueError):
    pass


def validate_logo(data: bytes) -> str:
    """Accept only a real PNG or JPEG of reasonable size; returns its suffix.
    Never trusts the declared type or file name — the bytes decide."""
    if not data:
        raise LogoError("Le fichier est vide")
    if len(data) > MAX_LOGO_BYTES:
        raise LogoError(f"Le logo dépasse {MAX_LOGO_BYTES // 1024} Ko")
    if data.startswith(_PNG):
        suffix = ".png"
    elif data.startswith(_JPEG):
        suffix = ".jpg"
    else:
        raise LogoError("Le logo doit être une image PNG ou JPEG")
    try:
        width, height = ImageReader(BytesIO(data)).getSize()
    except Exception as exc:  # a corrupt image must not reach a signed document
        raise LogoError("Image illisible") from exc
    if width < 16 or height < 16 or width > 6000 or height > 6000:
        raise LogoError("Dimensions du logo non acceptables (16 à 6000 px)")
    return suffix


def read_logo(storage: StorageService) -> tuple[bytes, str] | None:
    """(bytes, sha256) of the configured logo, or None."""
    for suffix in (".png", ".jpg"):
        if storage.exists(BUCKET, LOGO_ID, suffix):
            data = storage.read(BUCKET, LOGO_ID, suffix)
            return data, StorageService.sha256_hex(data)
    return None


def save_logo(storage: StorageService, data: bytes) -> str:
    suffix = validate_logo(data)
    delete_logo(storage)
    storage.save(BUCKET, LOGO_ID, suffix, data)
    return StorageService.sha256_hex(data)


def delete_logo(storage: StorageService) -> None:
    for suffix in (".png", ".jpg"):
        storage.delete(BUCKET, LOGO_ID, suffix)
