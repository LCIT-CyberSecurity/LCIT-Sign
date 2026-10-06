"""Each mail connector in its own module: what it describes, and the Gmail one."""
from __future__ import annotations

import base64
import json
from email import message_from_bytes

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from test_campaigns import setup_campaign_fixture

from lcit_sign.api.admin import get_mail_http_client
from lcit_sign.services.mail import MailSendError, build_sender
from lcit_sign.services.mail_gmail import GmailSender
from lcit_sign.services.mail_specs import SPECS


def service_account() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return json.dumps({"client_email": "sa@p.iam.gserviceaccount.com", "private_key": pem})


MAILBOX = "signature@corp.test"


class FakeGoogle:
    """Token endpoint and Gmail send endpoint, recording what was asked."""

    def __init__(self, token_error: str | None = None, send_status: int = 200) -> None:
        self.token_error, self.send_status = token_error, send_status
        self.sent: list[dict] = []
        self.tokens: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2.googleapis.com/token" in url:
            body = request.content.decode()
            self.tokens.append(body)
            if self.token_error:
                return httpx.Response(400, json={"error": self.token_error})
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer tok"
        assert url == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        self.sent.append(json.loads(request.content))
        return httpx.Response(self.send_status, json={"id": "m1"})


def sender(google: FakeGoogle, **kw) -> GmailSender:
    return GmailSender(
        httpx.Client(transport=httpx.MockTransport(google)),
        service_account_json=service_account(),
        mailbox=MAILBOX,
        **kw,
    )


def test_every_mail_connector_explains_each_of_its_fields():
    assert set(SPECS) == {"smtp", "graph", "gmail"}
    for kind, spec in SPECS.items():
        assert spec.label and spec.description
        for field in [*spec.fields, spec.secret]:
            assert len(field.help) > 20, (kind, field.name)
        # Everyone says who the mail comes from.
        assert "from_address" in {f.name for f in spec.fields}


def test_gmail_sends_as_the_mailbox_with_the_send_scope_only():
    google = FakeGoogle()
    sender(google, reply_to="support@corp.test").send(
        to="dest@corp.test", subject="Sujet é", body="Corps du message"
    )
    assert len(google.sent) == 1
    mime = message_from_bytes(base64.urlsafe_b64decode(google.sent[0]["raw"]))
    assert (mime["From"], mime["To"], mime["Reply-To"]) == (
        MAILBOX,
        "dest@corp.test",
        "support@corp.test",
    )
    assert mime.get_payload(decode=True).decode().strip() == "Corps du message"
    # The assertion asks for gmail.send and nothing wider, acting as the mailbox.
    assertion = google.tokens[0].split("assertion=")[1]
    claims = json.loads(base64.urlsafe_b64decode(assertion.split(".")[1] + "=="))
    assert claims["scope"] == "https://www.googleapis.com/auth/gmail.send"
    assert claims["sub"] == MAILBOX


@pytest.mark.parametrize(
    ("error", "hint"),
    [("unauthorized_client", "Délégation à l'échelle du domaine"), ("invalid_grant", MAILBOX)],
)
def test_gmail_says_what_to_fix_when_google_refuses_the_token(error, hint):
    with pytest.raises(MailSendError) as caught:
        sender(FakeGoogle(token_error=error)).send(to="a@b.test", subject="s", body="b")
    assert hint.lower() in str(caught.value).lower()
    diagnosis = sender(FakeGoogle(token_error=error)).diagnose()
    assert diagnosis["token"].startswith("FAIL")


def test_gmail_refusals_are_permanent_only_when_retrying_cannot_help():
    with pytest.raises(MailSendError) as bad_request:
        sender(FakeGoogle(send_status=400)).send(to="a@b.test", subject="s", body="b")
    assert bad_request.value.permanent is True
    with pytest.raises(MailSendError) as busy:
        sender(FakeGoogle(send_status=503)).send(to="a@b.test", subject="s", body="b")
    assert busy.value.permanent is False
    assert sender(FakeGoogle()).diagnose() == {"token": "OK"}


def test_a_broken_service_account_key_is_refused_without_echoing_it():
    with pytest.raises(MailSendError) as caught:
        GmailSender(httpx.Client(), service_account_json="{not json", mailbox=MAILBOX)
    assert "invalid Google service account" in str(caught.value)
    assert "{not json" not in str(caught.value)


def test_gmail_is_configured_tested_and_sent_through_the_admin_api(tmp_path, mock_oidc_base_url):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    google = FakeGoogle()

    def client():
        with httpx.Client(transport=httpx.MockTransport(google)) as c:
            yield c

    app.dependency_overrides[get_mail_http_client] = client

    kinds = {k["kind"]: k for k in admin.get("/api/admin/mail-connector/kinds").json()}
    assert set(kinds) == {"smtp", "graph", "gmail"} and kinds["gmail"]["secret"]["help"]

    key = service_account()
    refused = admin.put(
        "/api/admin/mail-connector",
        json={"kind": "gmail", "from_address": MAILBOX, "password": "{pas du json"},
    )
    assert refused.status_code == 422 and "JSON" in refused.text
    no_mailbox = admin.put(
        "/api/admin/mail-connector",
        json={"kind": "gmail", "from_address": "pas une adresse", "password": key},
    )
    assert no_mailbox.status_code == 422

    saved = admin.put(
        "/api/admin/mail-connector",
        json={"kind": "gmail", "from_address": MAILBOX, "password": key},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["kind"] == "gmail" and saved.json()["password_configured"] is True
    assert "private_key" not in saved.text

    assert admin.post("/api/admin/mail-connector/test-connection").json() == {"token": "OK"}
    sent = admin.post("/api/admin/mail-connector/send-test", json={"to": "me@corp.test"})
    assert sent.status_code == 200, sent.text
    assert len(google.sent) == 1


def test_build_sender_picks_the_module_of_each_kind(tmp_path, mock_oidc_base_url):
    from lcit_sign.models.mail import MailConnector
    from lcit_sign.services.mail_graph import GraphSender
    from lcit_sign.services.mail_smtp import SmtpSender

    def connector(kind):
        return MailConnector(id=1, kind=kind, from_address=MAILBOX, host="h", port=25)

    assert isinstance(build_sender(connector("smtp"), None), SmtpSender)
    assert isinstance(build_sender(connector("graph"), "s"), GraphSender)
    assert isinstance(build_sender(connector("gmail"), service_account()), GmailSender)
