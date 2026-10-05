from __future__ import annotations

import json

import httpx
from sqlalchemy import select
from test_campaigns import (
    create_and_launch_campaign,
    get_user_id,
    publish_a_document,
    setup_campaign_fixture,
)

from lcit_sign.api.admin import get_mail_http_client
from lcit_sign.models.mail import Notification, NotificationStatus
from lcit_sign.services import mail_graph
from lcit_sign.services.notification_queue import process_pending_notifications

SECRET = "FAKE-GRAPH-CLIENT-SECRET-42"  # noqa: S105
MAILBOX = "lcit-sign@corp.test"


class FakeGraph:
    """Behaves like a tenant: a token endpoint and sendMail, confined (or
    not) to MAILBOX by Exchange Application RBAC."""

    def __init__(self, *, confined: bool = True, bad_secret: bool = False) -> None:
        self.confined = confined
        self.bad_secret = bad_secret
        self.tokens_issued = 0
        self.sent: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "login.microsoftonline.com":
            if self.bad_secret:
                return httpx.Response(401, json={"error": "invalid_client",
                                                 "error_description": f"secret {SECRET} bad"})
            self.tokens_issued += 1
            return httpx.Response(200, json={"access_token": "graph-token", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer graph-token"
        mailbox = url.path.split("/users/")[1].split("/")[0].replace("%40", "@")
        if self.confined and mailbox != MAILBOX:
            return httpx.Response(403, json={"error": {"code": "ErrorAccessDenied"}})
        self.sent.append({"mailbox": mailbox, **json.loads(request.content)})
        return httpx.Response(202)


def _use_graph(app, graph: FakeGraph) -> None:
    mail_graph._token_cache.clear()

    def client():
        with httpx.Client(transport=httpx.MockTransport(graph)) as c:
            yield c

    app.dependency_overrides[get_mail_http_client] = client


TENANT = "73405479-f042-45d7-8149-c90341261b65"
CLIENT = "9a8b7c6d-5e4f-4321-b0a9-8c7d6e5f4a3b"


def _configure(admin):
    response = admin.put(
        "/api/admin/mail-connector",
        json={"kind": "graph", "graph_tenant_id": TENANT, "graph_client_id": CLIENT,
              "from_address": MAILBOX, "password": SECRET},
    )
    assert response.status_code == 200, response.text
    return response


def test_graph_connector_sends_from_the_dedicated_mailbox(tmp_path, mock_oidc_base_url):
    graph = FakeGraph()
    app, admin, operator, signer1, _ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _use_graph(app, graph)
    response = _configure(admin)
    assert SECRET not in response.text
    assert response.json()["kind"] == "graph"

    sent = admin.post("/api/admin/mail-connector/send-test", json={"to": "me@corp.test"})
    assert sent.status_code == 200, sent.text
    assert graph.sent[0]["mailbox"] == MAILBOX
    assert graph.sent[0]["message"]["toRecipients"][0]["emailAddress"]["address"] == "me@corp.test"
    assert graph.sent[0]["saveToSentItems"] is False

    diag = admin.post("/api/admin/mail-connector/test-connection").json()
    assert diag == {"token": "OK"}
    assert graph.tokens_issued == 1  # the second call reused the cached token


def test_graph_bad_credentials_never_echo_the_secret(tmp_path, mock_oidc_base_url):
    graph = FakeGraph(bad_secret=True)
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _use_graph(app, graph)
    _configure(admin)
    diag = admin.post("/api/admin/mail-connector/test-connection")
    assert diag.status_code == 200
    assert "FAIL" in diag.json()["token"]
    assert SECRET not in diag.text
    sent = admin.post("/api/admin/mail-connector/send-test", json={"to": "me@corp.test"})
    assert sent.status_code == 502
    assert SECRET not in sent.text


def test_isolation_test_passes_when_tenant_confines_the_app(tmp_path, mock_oidc_base_url):
    graph = FakeGraph(confined=True)
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _use_graph(app, graph)
    _configure(admin)
    result = admin.post(
        "/api/admin/mail-connector/test-isolation",
        json={"other_mailbox": "ceo@corp.test", "to": "me@corp.test"},
    ).json()
    assert result["isolated"] is True
    assert graph.sent == []


def test_isolation_test_flags_an_unbounded_tenant(tmp_path, mock_oidc_base_url):
    graph = FakeGraph(confined=False)
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    _use_graph(app, graph)
    _configure(admin)
    result = admin.post(
        "/api/admin/mail-connector/test-isolation",
        json={"other_mailbox": "ceo@corp.test", "to": "me@corp.test"},
    ).json()
    assert result["isolated"] is False
    assert "WARNING" in result["detail"]
    # ... and probing the dedicated mailbox itself is refused as meaningless.
    same = admin.post(
        "/api/admin/mail-connector/test-isolation",
        json={"other_mailbox": MAILBOX, "to": "me@corp.test"},
    )
    assert same.status_code == 422


def test_graph_connector_requires_its_fields(tmp_path, mock_oidc_base_url):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    response = admin.put(
        "/api/admin/mail-connector", json={"kind": "graph", "from_address": MAILBOX}
    )
    assert response.status_code == 422
    smtp_without_host = admin.put("/api/admin/mail-connector", json={"from_address": MAILBOX})
    assert smtp_without_host.status_code == 422


def test_worker_delivers_notifications_through_graph(tmp_path, mock_oidc_base_url, monkeypatch):
    graph = FakeGraph()
    app, admin, operator, signer1, signer2 = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    mail_graph._token_cache.clear()
    real_client = httpx.Client
    monkeypatch.setattr(
        "lcit_sign.services.mail.httpx.Client",
        lambda *a, **k: real_client(transport=httpx.MockTransport(graph)),
    )
    _configure(admin)
    _, version_id = publish_a_document(operator)
    create_and_launch_campaign(operator, version_id, [get_user_id(signer1)])

    with app.state.session_factory() as db:
        assert process_pending_notifications(db, app.state.settings) == 1
        statuses = {n.status for n in db.execute(select(Notification)).scalars()}
    assert statuses == {NotificationStatus.SENT}
    assert graph.sent and graph.sent[0]["mailbox"] == MAILBOX


def test_graph_mail_refuses_a_secret_typed_in_the_client_id_field(tmp_path, mock_oidc_base_url):
    app, admin, *_ = setup_campaign_fixture(tmp_path, mock_oidc_base_url)
    response = admin.put(
        "/api/admin/mail-connector",
        json={"kind": "graph", "graph_tenant_id": TENANT, "graph_client_id": "abC8Q~xYzTn3kLw0pQe5",
              "from_address": MAILBOX, "password": SECRET},
    )
    assert response.status_code == 422 and "secret" in response.text
