"""SMTP scenarios against the test Postfix (spec §58).

Runs inside the lcit-sign-api image so it exercises the real
`lcit_sign.services.mail` code. Driven by run-smtp-scenarios.sh, which
supplies the throwaway credentials and certificate the Postfix container
generated at start. Nothing secret is in this file or in Git.
"""
from __future__ import annotations

import os
import sys
import time

from lcit_sign.services.mail import MailSendError
from lcit_sign.services.mail_smtp import SmtpCredentials, diagnose_connection, send_email

HOST = os.environ.get("TEST_SMTP_HOST", "127.0.0.1")
USER = os.environ["TEST_SMTP_USER"]
PASSWORD = os.environ["TEST_SMTP_PASSWORD"]
CA_FILE = os.environ["TEST_SMTP_CA_FILE"]
PORT_PLAIN, PORT_STARTTLS, PORT_TLS, PORT_BLACKHOLE, PORT_CLOSED = 2525, 2587, 2465, 2526, 2599

FROM = "lcit-sign@lcit-test.local"
MAILBOX = "alice.martin@lcit-test.local"

failures: list[str] = []


def creds(port: int, *, tls=False, starttls=False, auth=False, password=PASSWORD, timeout=5):
    return SmtpCredentials(
        host=HOST, port=port, use_tls=tls, use_starttls=starttls,
        username=USER if auth else "", password=password if auth else None,
        timeout_seconds=timeout,
    )


def send(c: SmtpCredentials, to: str) -> None:
    send_email(c, from_address=FROM, reply_to=None, to=to,
               subject="LCIT Sign scenario", body="test message")


def trust_server_certificate(trusted: bool) -> None:
    if trusted:
        os.environ["SSL_CERT_FILE"] = CA_FILE
    else:
        os.environ.pop("SSL_CERT_FILE", None)


def scenario(name: str):
    def decorate(fn):
        try:
            fn()
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL  {name}  ({exc})")
        except Exception as exc:  # noqa: BLE001
            failures.append(name)
            print(f"FAIL  {name}  ({type(exc).__name__}: {exc})")
        else:
            print(f"PASS  {name}")
        return fn
    return decorate


def refused(c: SmtpCredentials, to: str) -> MailSendError:
    try:
        send(c, to)
    except MailSendError as exc:
        return exc
    raise AssertionError("the message was accepted but should have been refused")


trust_server_certificate(True)


@scenario("SMTP OK: plain delivery to a local mailbox")
def _():
    send(creds(PORT_PLAIN), MAILBOX)


@scenario("SMTP OK: STARTTLS + AUTH, diagnostics all green")
def _():
    c = creds(PORT_STARTTLS, starttls=True, auth=True)
    send(c, MAILBOX)
    diag = diagnose_connection(c)
    assert diag == {"dns": "OK", "tcp": "OK", "tls": "OK", "auth": "OK"}, diag


@scenario("SMTP OK: implicit TLS + AUTH")
def _():
    send(creds(PORT_TLS, tls=True, auth=True), MAILBOX)


@scenario("AUTH KO: wrong password is refused, reported without the secret")
def _():
    c = creds(PORT_STARTTLS, starttls=True, auth=True, password="definitely-wrong-password")
    diag = diagnose_connection(c)
    assert diag["auth"].startswith("FAIL"), diag
    assert "definitely-wrong-password" not in str(diag)
    error = refused(c, MAILBOX)
    assert "definitely-wrong-password" not in str(error)


@scenario("TLS KO: untrusted certificate is refused")
def _():
    trust_server_certificate(False)
    try:
        error = refused(creds(PORT_STARTTLS, starttls=True, auth=True), MAILBOX)
        assert "certificate" in str(error).lower() or "ssl" in str(error).lower(), error
    finally:
        trust_server_certificate(True)


@scenario("TLS KO: STARTTLS demanded from a server that does not offer it")
def _():
    error = refused(creds(PORT_PLAIN, starttls=True), MAILBOX)
    assert not error.permanent


@scenario("Relay denied: an external recipient is refused permanently")
def _():
    error = refused(creds(PORT_PLAIN), "someone@example.org")
    assert error.permanent and "relay" in str(error).lower(), error


@scenario("Mailbox unknown: refused permanently")
def _():
    error = refused(creds(PORT_PLAIN), "nobody.here@lcit-test.local")
    assert error.permanent, error


@scenario("4xx: temporary refusal is retryable")
def _():
    error = refused(creds(PORT_PLAIN), "anyone@defer.lcit-test.local")
    assert not error.permanent, error


@scenario("5xx: policy rejection is permanent")
def _():
    error = refused(creds(PORT_PLAIN), "anyone@reject.lcit-test.local")
    assert error.permanent, error


@scenario("Timeout: a server that never answers fails fast and is retryable")
def _():
    started = time.monotonic()
    error = refused(creds(PORT_BLACKHOLE, timeout=2), MAILBOX)
    assert time.monotonic() - started < 8
    assert not error.permanent


@scenario("Connection refused: retryable")
def _():
    error = refused(creds(PORT_CLOSED), MAILBOX)
    assert not error.permanent


if failures:
    print(f"\n{len(failures)} scenario(s) failed")
    sys.exit(1)
print("\nAll SMTP scenarios passed.")
