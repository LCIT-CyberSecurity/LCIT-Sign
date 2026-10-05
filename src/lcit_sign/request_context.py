from __future__ import annotations

from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


_source_ip: ContextVar[str | None] = ContextVar("source_ip", default=None)


def set_source_ip(value: str | None) -> None:
    _source_ip.set(value)


def get_source_ip() -> str | None:
    return _source_ip.get()


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()
