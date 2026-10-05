from __future__ import annotations

import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

import httpx

from lcit_sign.models.mail import MailConnector


class MailSendError(Exception):
    """A message could not be sent.

    `permanent` is True when retrying cannot help (an SMTP 5xx answer: the
    recipient does not exist, the policy refuses it, relaying is denied).
    Connection problems, timeouts and 4xx answers are temporary.
    """

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


def _smtp_error_is_permanent(exc: smtplib.SMTPException) -> bool:
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = [code for code, _ in exc.recipients.values()]
        return bool(codes) and all(code >= 500 for code in codes)
    code = getattr(exc, "smtp_code", None)
    return isinstance(code, int) and code >= 500


@dataclass(frozen=True)
class SmtpCredentials:
    host: str
    port: int
    use_tls: bool
    use_starttls: bool
    username: str
    password: str | None
    timeout_seconds: int


def credentials_from_connector(connector: MailConnector, password: str | None) -> SmtpCredentials:
    return SmtpCredentials(
        host=connector.host,
        port=connector.port,
        use_tls=connector.use_tls,
        use_starttls=connector.use_starttls,
        username=connector.username,
        password=password,
        timeout_seconds=connector.timeout_seconds,
    )


def _open_connection(creds: SmtpCredentials) -> smtplib.SMTP:
    context = ssl.create_default_context()
    if creds.use_tls:
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            creds.host, creds.port, timeout=creds.timeout_seconds, context=context
        )
    else:
        server = smtplib.SMTP(creds.host, creds.port, timeout=creds.timeout_seconds)
    server.ehlo()
    if creds.use_starttls and not creds.use_tls:
        server.starttls(context=context)
        server.ehlo()
    return server


def send_email(
    creds: SmtpCredentials,
    *,
    from_address: str,
    reply_to: str | None,
    to: str,
    subject: str,
    body: str,
) -> None:
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = to
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(body)

    try:
        server = _open_connection(creds)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailSendError(f"Could not connect to SMTP server: {exc}") from exc

    try:
        if creds.username:
            server.login(creds.username, creds.password or "")
        server.send_message(message)
    except smtplib.SMTPException as exc:
        raise MailSendError(
            f"SMTP server rejected the message: {exc}", permanent=_smtp_error_is_permanent(exc)
        ) from exc
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            pass


def diagnose_connection(creds: SmtpCredentials) -> dict[str, str]:
    """Step-by-step SMTP diagnostic (spec §71): each stage reports OK,
    FAIL, or SKIPPED (never reached because an earlier stage failed).
    Never includes the credential itself in any result.
    """
    results = {"dns": "SKIPPED", "tcp": "SKIPPED", "tls": "SKIPPED", "auth": "SKIPPED"}

    try:
        socket.getaddrinfo(creds.host, creds.port)
        results["dns"] = "OK"
    except OSError as exc:
        results["dns"] = f"FAIL: {exc}"
        return results

    try:
        server = _open_connection(creds)
        results["tcp"] = "OK"
        results["tls"] = "OK" if (creds.use_tls or creds.use_starttls) else "N/A"
    except (OSError, smtplib.SMTPException) as exc:
        results["tcp"] = f"FAIL: {exc}"
        return results

    try:
        if creds.username:
            server.login(creds.username, creds.password or "")
            results["auth"] = "OK"
        else:
            results["auth"] = "N/A"
    except smtplib.SMTPException as exc:
        results["auth"] = f"FAIL: {exc}"
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            pass

    return results


class MailSender(Protocol):
    kind: str

    def send(self, *, to: str, subject: str, body: str) -> None: ...

    def diagnose(self) -> dict[str, str]: ...


class SmtpSender:
    kind = "smtp"

    def __init__(self, creds: SmtpCredentials, *, from_address: str, reply_to: str | None) -> None:
        self._creds = creds
        self._from = from_address
        self._reply_to = reply_to

    def send(self, *, to: str, subject: str, body: str) -> None:
        send_email(
            self._creds,
            from_address=self._from,
            reply_to=self._reply_to,
            to=to,
            subject=subject,
            body=body,
        )

    def diagnose(self) -> dict[str, str]:
        return diagnose_connection(self._creds)


def build_sender(
    connector: MailConnector, secret: str | None, http_client: httpx.Client | None = None
) -> MailSender:
    """The one place that turns the stored connector row into something
    that can send — SMTP or Microsoft Graph (spec §53)."""
    if connector.kind == "graph":
        from lcit_sign.services.mail_graph import GraphSender

        return GraphSender(
            http_client or httpx.Client(timeout=15.0),
            tenant_id=connector.graph_tenant_id or "",
            client_id=connector.graph_client_id or "",
            client_secret=secret or "",
            mailbox=connector.from_address,
            reply_to=connector.reply_to,
        )
    return SmtpSender(
        credentials_from_connector(connector, secret),
        from_address=connector.from_address,
        reply_to=connector.reply_to,
    )
