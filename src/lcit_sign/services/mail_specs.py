"""The mail connectors, one module each, listed in one place."""
from __future__ import annotations

from lcit_sign.services import mail_gmail, mail_graph, mail_smtp
from lcit_sign.services.mail_spec import MailSpec

SPECS: dict[str, MailSpec] = {
    spec.kind: spec for spec in (mail_smtp.SPEC, mail_graph.SPEC, mail_gmail.SPEC)
}
