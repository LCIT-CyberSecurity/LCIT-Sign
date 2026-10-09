from __future__ import annotations

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


class MailSender(Protocol):
    kind: str

    def send(self, *, to: str, subject: str, body: str) -> None: ...

    def diagnose(self) -> dict[str, str]: ...


def build_sender(
    connector: MailConnector, secret: str | None, http_client: httpx.Client | None = None
) -> MailSender:
    """The one place that turns the stored connector row into something that can send:
    SMTP, Microsoft Graph or Google Workspace (spec §53). Each lives in its own module."""
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
    if connector.kind == "gmail":
        from lcit_sign.services.mail_gmail import GmailSender

        return GmailSender(
            http_client or httpx.Client(timeout=15.0),
            service_account_json=secret or "",
            mailbox=connector.from_address,
            reply_to=connector.reply_to,
        )
    from lcit_sign.services.mail_smtp import SmtpSender, credentials_from_connector

    return SmtpSender(
        credentials_from_connector(connector, secret),
        from_address=connector.from_address,
        reply_to=connector.reply_to,
    )
