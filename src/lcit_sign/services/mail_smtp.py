"""Plain SMTP: any relay (Postfix, Exchange, a provider's SMTP service)."""
from __future__ import annotations

import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from lcit_sign.models.mail import MailConnector
from lcit_sign.services.connector_fields import FieldSpec
from lcit_sign.services.mail import MailSendError
from lcit_sign.services.mail_spec import MailSpec


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




def validate(fields: dict[str, str], secret: str | None) -> None:
    if not fields.get("host", "").strip():
        raise ValueError("Indiquez l'adresse du serveur SMTP (par exemple smtp.entreprise.fr).")
    port = fields.get("port", "")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("Le port est un nombre entre 1 et 65535 (587 en général).")
    if "@" not in fields.get("from_address", ""):
        raise ValueError("L'adresse d'expédition doit être une adresse e-mail complète.")


SPEC = MailSpec(
    kind="smtp",
    label="SMTP",
    description=(
        "Envoie par n'importe quel serveur SMTP : un relais interne (Postfix, Exchange…) ou le "
        "service SMTP d'un fournisseur. La connexion peut être chiffrée (TLS ou STARTTLS)."
    ),
    fields=(
        FieldSpec(
            "host",
            "Serveur SMTP",
            "L'adresse du serveur qui envoie les e-mails.",
            "smtp.entreprise.fr",
        ),
        FieldSpec(
            "port",
            "Port",
            "Le port du serveur : 587 (STARTTLS, le plus courant), 465 (TLS implicite) ou 25.",
            "587",
            kind="number",
            default="587",
        ),
        FieldSpec(
            "use_starttls",
            "STARTTLS",
            "Chiffre la connexion après l'avoir ouverte (port 587). À cocher sauf si le serveur "
            "ne le permet pas.",
            kind="checkbox",
            default="true",
            required=False,
        ),
        FieldSpec(
            "use_tls",
            "TLS implicite",
            "Chiffre la connexion dès l'ouverture (port 465). Ne se combine pas avec STARTTLS.",
            kind="checkbox",
            default="false",
            required=False,
        ),
        FieldSpec(
            "username",
            "Utilisateur",
            "Le compte qui s'identifie auprès du serveur. Laissez vide si le serveur n'exige pas "
            "d'identification (relais interne).",
            "lcit-sign@entreprise.fr",
            required=False,
        ),
        FieldSpec(
            "from_address",
            "Adresse d'expédition",
            "L'adresse qui apparaît comme expéditeur des e-mails de signature.",
            "signature@entreprise.fr",
        ),
        FieldSpec(
            "reply_to",
            "Répondre à",
            "Facultatif : l'adresse qui reçoit les réponses (l'expéditeur n'est souvent pas lu).",
            "support@entreprise.fr",
            required=False,
        ),
    ),
    secret=FieldSpec(
        "password",
        "Mot de passe SMTP",
        "Le mot de passe du compte ci-dessus. Chiffré ici, jamais réaffiché. Laissez vide si "
        "le serveur n'exige pas d'identification.",
        kind="password",
        required=False,
    ),
    validate=validate,
)
