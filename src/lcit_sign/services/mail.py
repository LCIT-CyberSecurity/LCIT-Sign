from __future__ import annotations

import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from lcit_sign.models.mail import MailConnector


class MailSendError(Exception):
    pass


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
        raise MailSendError(f"SMTP server rejected the message: {exc}") from exc
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
