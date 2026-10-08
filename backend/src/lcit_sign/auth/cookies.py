from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

LOGIN_FLOW_COOKIE = "lcit_sign_login"
SESSION_COOKIE = "lcit_sign_session"
LOGIN_FLOW_MAX_AGE_SECONDS = 300


def sign_login_flow_cookie(payload: dict[str, Any], secret: str) -> str:
    """Pack {state, nonce, code_verifier, issued_at} into a tamper-evident cookie.

    HMAC-SHA256 over a base64 body, same shape as a JWS compact signature
    but without pulling in a JWT library for a value that is never meant to
    leave this server.
    """
    body = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    signature = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_login_flow_cookie(value: str, secret: str) -> dict[str, Any] | None:
    try:
        body, signature = value.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(body))
    except (ValueError, json.JSONDecodeError):
        return None
    issued_at = payload.get("issued_at")
    age = time.time() - issued_at if isinstance(issued_at, (int, float)) else None
    if age is None or age > LOGIN_FLOW_MAX_AGE_SECONDS:
        return None
    return payload


def generate_session_token() -> tuple[str, str]:
    """Return (raw_token_for_cookie, sha256_hash_for_storage)."""
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token, token_hash


def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
