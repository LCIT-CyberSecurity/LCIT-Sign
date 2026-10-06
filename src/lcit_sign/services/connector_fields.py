"""How a connector's settings are described, for the admin page to draw a form with a help
bubble on every field. Shared by the directory connectors and the mail connectors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldSpec:
    """One setting of a connector, described so the admin page can show it with a help
    bubble: what it is, and an example of what to type."""

    name: str
    label: str
    help: str
    example: str = ""
    kind: str = "text"  # text | password | textarea | select | number | checkbox
    options: tuple[tuple[str, str], ...] = ()
    default: str = ""
    required: bool = True

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "help": self.help,
            "example": self.example,
            "kind": self.kind,
            "options": [{"value": v, "label": label} for v, label in self.options],
            "default": self.default,
            "required": self.required,
        }
