from __future__ import annotations

import hashlib
import uuid
from pathlib import Path


class StorageService:
    """Thin filesystem abstraction so the rest of the app never touches a
    path directly (spec §9). Every stored object is addressed by an
    internal UUID picked by the caller — never by a user-supplied filename —
    which is what rules out path traversal by construction rather than by
    sanitizing untrusted input.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, bucket: str, object_id: uuid.UUID, suffix: str) -> Path:
        # `bucket` is always a fixed literal passed by our own code
        # (documents/signed/evidence/...), never user input.
        return self.root / bucket / f"{object_id}{suffix}"

    def save(self, bucket: str, object_id: uuid.UUID, suffix: str, data: bytes) -> Path:
        path = self._path(bucket, object_id, suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_bytes(data)
        tmp_path.replace(path)  # atomic: never leaves a half-written file at `path`
        return path

    def read(self, bucket: str, object_id: uuid.UUID, suffix: str) -> bytes:
        return self._path(bucket, object_id, suffix).read_bytes()

    def exists(self, bucket: str, object_id: uuid.UUID, suffix: str) -> bool:
        return self._path(bucket, object_id, suffix).is_file()

    def delete(self, bucket: str, object_id: uuid.UUID, suffix: str) -> None:
        self._path(bucket, object_id, suffix).unlink(missing_ok=True)

    def path_for(self, bucket: str, object_id: uuid.UUID, suffix: str) -> Path:
        return self._path(bucket, object_id, suffix)

    @staticmethod
    def sha256_hex(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()
