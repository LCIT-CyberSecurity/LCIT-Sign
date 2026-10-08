"""Shared helpers for the CrashTests-Sign scripts.

Runs inside the lcit-sign-api image (httpx and pypdf are already there), on
the machine that hosts the Docker stack, e.g.:

    docker run --rm --network host -v "$PWD/tests/crashtest/uat:/uat:ro" \
        --entrypoint python lcit-sign-api:latest /uat/smoke.py

No secret lives here: identities are the mock OIDC provider's fictional
CrashTest users.
"""
from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import httpx
from pypdf import PdfWriter

BASE_URL = os.environ.get("LCIT_SIGN_BASE_URL", "http://localhost:4180")

# The mock OIDC provider's identities (tests/crashtest/mock_oidc/app.py).
ADMIN = "u-direction-1"
OPERATOR = "u-sales-1"
SIGNERS = ("u-it-1", "u-rh-1", "u-compta-1", "u-compta-2", "u-compta-3", "u-compta-4")


def login(sub: str, base_url: str = BASE_URL) -> httpx.Client:
    """Drive the real Authorization Code + PKCE flow against the mock OIDC
    provider (browser-facing URLs, through nginx) and return a logged-in client."""
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=30.0)
    first = client.get("/api/auth/login")
    if first.status_code != 302:
        raise RuntimeError(f"login did not redirect (HTTP {first.status_code})")
    authorize_url = first.headers["location"]
    choose_url = authorize_url.replace("/authorize?", "/authorize/choose?", 1) + f"&sub={sub}"
    chosen = httpx.get(choose_url, follow_redirects=False, timeout=30.0)
    if chosen.status_code not in (302, 307):
        raise RuntimeError(f"identity {sub!r} refused by the mock provider")
    query = parse_qs(urlparse(chosen.headers["location"]).query)
    done = client.get(
        "/api/auth/callback", params={"code": query["code"][0], "state": query["state"][0]}
    )
    if done.status_code not in (302, 307):
        raise RuntimeError(f"callback failed (HTTP {done.status_code})")
    return client


def pdf_bytes(width: int = 200, height: int = 200) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def me(client: httpx.Client) -> dict:
    response = client.get("/api/auth/me")
    response.raise_for_status()
    data: dict = response.json()
    return data


class Smoke:
    """Runs named checks, prints PASS/FAIL/SKIP, remembers failures."""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, name: str, fn: Callable[[], object]) -> object:
        started = time.monotonic()
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - a smoke test reports, never raises
            self.failures.append(name)
            print(f"FAIL  {name}  ({type(exc).__name__}: {exc})")  # noqa: T201
            return None
        print(f"PASS  {name}  ({time.monotonic() - started:.2f}s)")  # noqa: T201
        return result

    def skip(self, name: str, why: str) -> None:
        print(f"SKIP  {name}  ({why})")  # noqa: T201

    def finish(self) -> int:
        if self.failures:
            print(f"\n{len(self.failures)} check(s) failed: {', '.join(self.failures)}")  # noqa: T201
            return 1
        print("\nAll smoke checks passed.")  # noqa: T201
        return 0


def expect(response: httpx.Response, *statuses: int) -> httpx.Response:
    if response.status_code not in statuses:
        raise AssertionError(
            f"{response.request.method} {response.request.url.path} -> "
            f"HTTP {response.status_code} (wanted {statuses})"
        )
    return response


def main_guard(fn: Callable[[], int]) -> None:
    try:
        code = fn()
    except Exception as exc:  # noqa: BLE001
        print(f"ABORT {type(exc).__name__}: {exc}")  # noqa: T201
        code = 2
    sys.exit(code)
