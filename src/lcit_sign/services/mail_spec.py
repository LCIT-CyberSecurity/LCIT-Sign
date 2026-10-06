"""How a mail connector describes itself (its settings, with help for each, and its checks),
so the admin page can draw its form."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lcit_sign.services.connector_fields import FieldSpec


@dataclass(frozen=True)
class MailSpec:
    kind: str
    label: str
    description: str
    fields: tuple[FieldSpec, ...]
    secret: FieldSpec
    # Raises ValueError(message in the admin's words) when what was typed cannot work.
    validate: Callable[[dict[str, str], str | None], None]

    def payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "description": self.description,
            "fields": [f.payload() for f in self.fields],
            "secret": self.secret.payload(),
        }
