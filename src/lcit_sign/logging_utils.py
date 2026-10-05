from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

# Substrings matched case-insensitively against a field name. Any value whose
# key contains one of these is replaced before it can reach stdout, a log
# shipper, or a persisted audit row — components must not be trusted to
# remember this on every call site themselves.
SENSITIVE_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
    "master_key",
    "masterkey",
)

REDACTED = "***REDACTED***"

_RESERVED_LOG_RECORD_FIELDS = frozenset(logging.LogRecord(
    "", 0, "", 0, "", (), None,
).__dict__)


def redact_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively replace values whose key looks sensitive.

    Used both by the log formatter (for structured `extra=` fields) and by
    any component about to persist or emit a dict it did not fully control.
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        lowered = str(key).lower()
        if any(part in lowered for part in SENSITIVE_KEY_PARTS):
            result[key] = REDACTED
        elif isinstance(value, Mapping):
            result[key] = redact_mapping(value)
        else:
            result[key] = value
    return result


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        from lcit_sign.request_context import get_request_id

        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_LOG_RECORD_FIELDS
        }
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "component": record.name,
            "event": record.getMessage(),
            "request_id": extra.pop("request_id", None) or get_request_id(),
            **redact_mapping(extra),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # HTTP client libraries log full request URLs at INFO, and a URL can carry
    # an authorization code or other credential in its query string.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
