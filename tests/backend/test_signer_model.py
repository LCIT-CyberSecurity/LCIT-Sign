# ruff: noqa: E501
"""SIGNER is the standard user of LCIT Sign: everyone active has it by default, it lets them prepare,
send and sign, and the API checks it. One directory and one SSO are in use at a time."""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import httpx
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_auth_flow import login_as, make_app
from test_campaign_access import build, campaign_for, sign
from test_campaigns import TEST_MASTER_KEY, get_user_id
from test_directory_connectors import ENTRA_FIELDS, _entra_handler
from test_prepared_fields import element, upload

from lcit_sign import models  # noqa: F401 - registers tables
from lcit_sign.api.directory import get_directory_http_client
from lcit_sign.database import Base
from lcit_sign.models.audit import AuditEvent
from lcit_sign.models.campaign import Campaign
from lcit_sign.models.user import Role, User, UserRole
from lcit_sign.services.local_auth import ensure_builtin_admin


def roles_in_db(app, email: str) -> list[str]:
    with app.state.session_factory() as db:
        return sorted(
            r.value for r in db.execute(
                select(UserRole.role).join(User, User.id == UserRole.user_id).where(User.email == email)
            ).scalars()
        )


# --- the role is given at creation, whatever the way in ----------------------------------------


def test_a_new_sso_user_is_active_and_a_signer_at_once(tmp_path, mock_oidc_base_url):  # A
    app = make_app(tmp_path, mock_oidc_base_url)
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.engine)
        login_as(client, mock_oidc_base_url, sub="u-rh-1")
        me = client.get("/api/auth/me").json()
        assert me["roles"] == ["SIGNER"]
        with app.state.session_factory() as db:
            assert db.get(User, uuid.UUID(me["id"])).active is True


def test_a_directory_import_makes_signers_and_a_resync_never_gives_the_role_back(  # B, M
    tmp_path, mock_oidc_base_url
):
    app = make_app(tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY, crashtest=True)
    with TestClient(app) as admin:
        Base.metadata.create_all(app.state.engine)
        login_as(admin, mock_oidc_base_url, sub="u-direction-1")
        assert admin.post("/api/admin/directory/sync?source=local").json()["status"] == "SUCCESS"
        users = admin.get("/api/admin/users").json()
        imported = [u for u in users if u["email"].endswith("@lcit-test.local")]
        assert len(imported) >= 24 and all("SIGNER" in u["roles"] for u in imported)

        # An administrator takes the role from one person on purpose…
        louis = next(u for u in imported if u["email"] == "louis.bonnet@lcit-test.local")
        assert admin.delete(f"/api/admin/users/{louis['id']}/roles/SIGNER").status_code == 200
        # …and the next synchronisation (which updates that person) does not put it back.
        run = admin.post("/api/admin/directory/sync?source=local").json()
        assert run["status"] == "SUCCESS" and run["users_added"] == 0 and run["users_updated"] >= 24
        assert roles_in_db(app, "louis.bonnet@lcit-test.local") == []
        assert roles_in_db(app, "manon.faure@lcit-test.local") == ["SIGNER"]  # no duplicate either


def test_local_accounts_and_the_builtin_administrator_are_signers(  # C
    tmp_path, mock_oidc_base_url
):
    app = make_app(tmp_path, mock_oidc_base_url, local_auth_enabled=True)
    with TestClient(app) as admin:
        Base.metadata.create_all(app.state.engine)
        with app.state.session_factory() as db:
            builtin = ensure_builtin_admin(db, app.state.settings)
            assert builtin is not None
            held = set(db.execute(select(UserRole.role).where(UserRole.user_id == builtin.id)).scalars())
            assert held == {Role.ADMIN, Role.SIGNER}
            # A restart does not give a taken-away SIGNER back to the existing account.
            db.execute(sa.delete(UserRole).where(UserRole.user_id == builtin.id, UserRole.role == Role.SIGNER))
            db.commit()
            ensure_builtin_admin(db, app.state.settings)
            held = set(db.execute(select(UserRole.role).where(UserRole.user_id == builtin.id)).scalars())
            assert held == {Role.ADMIN}
        login_as(admin, mock_oidc_base_url, sub="u-direction-1")
        created = admin.post("/api/admin/users", json={
            "email": "nadia@corp.test", "auth_method": "local", "password": "un-mot-de-passe"})
        assert created.status_code == 201 and created.json()["roles"] == ["SIGNER"]
        extern = admin.post("/api/campaigns/_meta/externals", json={"email": "jean@partenaire.com"})
        assert extern.status_code == 201
        assert roles_in_db(app, "jean@partenaire.com") == ["SIGNER"]


# --- a signer prepares, sends and signs ---------------------------------------------------------


def test_a_signer_alone_prepares_sends_and_follows_a_campaign_signed_by_two_people_himself_included(
    tmp_path, mock_oidc_base_url
):  # D, E, F, G, H, I, J
    app = make_app(tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY)
    with TestClient(app) as admin:
        Base.metadata.create_all(app.state.engine)
        login_as(admin, mock_oidc_base_url, sub="u-direction-1")
        paul, julie = TestClient(app), TestClient(app)
        login_as(paul, mock_oidc_base_url, sub="u-rh-1")
        login_as(julie, mock_oidc_base_url, sub="u-compta-1")
        paul_id, julie_id = get_user_id(paul), get_user_id(julie)
        assert paul.get("/api/auth/me").json()["roles"] == ["SIGNER"]  # no OPERATOR, nothing else

        version = upload(paul, title="NDA", pages=1)  # prepares a document
        assert paul.put(f"/api/documents/versions/{version}/fields", json={
            "fields": [element("SIGNATURE", role=1, y=0.7)]}).status_code == 200
        assert paul.post(f"/api/documents/versions/{version}/publish").status_code == 200
        created = paul.post("/api/campaigns", json={"name": "NDA Acme"})  # creates the campaign
        assert created.status_code == 201
        cid = created.json()["id"]
        assert paul.post(f"/api/campaigns/{cid}/documents", json={"document_version_id": version}
                         ).status_code == 201
        # He chooses several signers, himself and somebody else.
        launched = paul.post(f"/api/campaigns/{cid}/launch", json={"user_ids": [paul_id, julie_id]})
        assert launched.status_code == 200, launched.text
        assert launched.json()["assignment_counts"]["PENDING"] == 2

        # Each signs their part.
        sign(paul, version, cid)
        shown = paul.get(f"/api/campaigns/{cid}").json()  # he follows it as its owner
        assert shown["access"] == {"operate": True, "content": True}
        assert shown["owner"]["id"] == shown["created_by"]["id"] == paul_id
        sign(julie, version, cid)
        done = paul.get(f"/api/campaigns/{cid}/assignments").json()
        assert sorted(a["status"] for a in done) == ["SIGNED", "SIGNED"]
        assert [c["name"] for c in paul.get("/api/campaigns").json()] == ["NDA Acme"]


def test_a_signature_needs_the_role_even_with_a_valid_assignment(tmp_path, mock_oidc_base_url):  # K, L
    w = build(tmp_path, mock_oidc_base_url)
    # Ghost was asked to sign (an assignment exists) but has no SIGNER role.
    cid, version = campaign_for(w.rh, w.ids["ghost"], "Pour Ghost")
    refused = w.ghost.post(f"/api/documents/versions/{version}/sign",
                           json={"consent": True, "campaign_id": cid})
    assert refused.status_code == 403
    # …and the same person, once an administrator gives the role, can sign.
    assert w.admin.post(f"/api/admin/users/{w.ids['ghost']}/roles", json={"role": "SIGNER"}
                        ).status_code == 201
    assert w.ghost.post(f"/api/documents/versions/{version}/sign",
                        json={"consent": True, "campaign_id": cid}).status_code == 201
    # Taken away again: nothing more can be signed or sent by them.
    assert w.admin.delete(f"/api/admin/users/{w.ids['ghost']}/roles/SIGNER").status_code == 200
    assert w.ghost.post("/api/campaigns", json={"name": "X"}).status_code == 403


def test_a_deactivated_account_cannot_sign_in_even_though_it_is_a_signer(tmp_path, mock_oidc_base_url):
    w = build(tmp_path, mock_oidc_base_url)
    assert w.admin.patch(f"/api/admin/users/{w.ids['bob']}", json={"active": False}).status_code == 200
    assert w.bob.get("/api/auth/me").status_code == 401
    again = TestClient(w.app)
    page = again.get("/api/auth/login", follow_redirects=False)
    assert page.status_code == 302  # authentication itself still works, the account does not
    # (the callback refuses a disabled account: see test_auth_flow)


# --- campaigns stay private ---------------------------------------------------------------------


def test_a_signature_assignment_gives_no_access_to_the_management_of_the_campaign(
    tmp_path, mock_oidc_base_url
):
    w = build(tmp_path, mock_oidc_base_url)
    # Bob is asked to sign the HR campaign, which Alice (rh) runs. Julie (legal) is just a signer.
    seen_by_bob = w.bob.get("/api/campaigns").json()
    assert seen_by_bob == []
    for call in (
        w.bob.get(f"/api/campaigns/{w.hr}"),
        w.bob.get(f"/api/campaigns/{w.hr}/assignments"),
        w.bob.get(f"/api/campaigns/{w.hr}/reports"),
        w.bob.post(f"/api/campaigns/{w.hr}/preparers", json={"user_id": w.ids["bob"]}),
        w.bob.put(f"/api/campaigns/{w.hr}/owner", json={"user_id": w.ids["bob"]}),
        w.bob.post(f"/api/campaigns/{w.hr}/cancel"),
        w.legal.get(f"/api/campaigns/{w.hr}"),
    ):
        assert call.status_code in (403, 404), call.request.url
    # A stranger cannot read the document, the person asked to sign it can (they must, to sign).
    assert w.legal.get(f"/api/documents/versions/{w.hr_version}/content").status_code in (403, 404)
    # What was asked of him remains his to sign.
    assert sign(w.bob, w.hr_version, w.hr)


# --- campaign preparer, owner, operator ---------------------------------------------------------


def test_a_campaign_preparer_is_a_right_on_one_campaign_only(tmp_path, mock_oidc_base_url):
    w = build(tmp_path, mock_oidc_base_url)
    assert w.rh2.get(f"/api/campaigns/{w.hr}").status_code == 404
    assert w.rh2.get(f"/api/documents/versions/{w.hr_version}/content").status_code in (403, 404)
    added = w.rh.post(f"/api/campaigns/{w.hr}/preparers", json={"user_id": w.ids["rh2"]})
    assert added.status_code == 201
    assert w.rh2.get(f"/api/campaigns/{w.hr}").json()["access"] == {"operate": True, "content": True}
    assert w.rh2.get(f"/api/documents/versions/{w.hr_version}/content").status_code == 200
    # Only that campaign: Alice's other work and the legal one stay closed to Claire.
    assert w.rh2.get(f"/api/campaigns/{w.law}").status_code == 404
    assert [c["name"] for c in w.rh2.get("/api/campaigns").json()] == ["Entretiens RH 2027"]
    assert w.rh.delete(f"/api/campaigns/{w.hr}/preparers/{w.ids['rh2']}").status_code == 200
    assert w.rh2.get(f"/api/campaigns/{w.hr}").status_code == 404


def test_the_owner_changes_but_created_by_never_does_and_it_is_audited(tmp_path, mock_oidc_base_url):
    w = build(tmp_path, mock_oidc_base_url)
    before = w.rh.get(f"/api/campaigns/{w.hr}").json()
    assert before["owner"]["id"] == before["created_by"]["id"] == w.ids["rh"]
    assert w.rh.post(f"/api/campaigns/{w.hr}/preparers", json={"user_id": w.ids["rh2"]}).status_code == 201
    moved = w.operator.put(f"/api/campaigns/{w.hr}/owner", json={"user_id": w.ids["rh2"]})
    assert moved.status_code == 200
    after = w.rh2.get(f"/api/campaigns/{w.hr}").json()
    assert after["owner"]["id"] == w.ids["rh2"] and after["created_by"]["id"] == w.ids["rh"]
    with w.app.state.session_factory() as db:
        campaign = db.get(Campaign, uuid.UUID(w.hr))
        assert str(campaign.created_by) == w.ids["rh"] and str(campaign.owner_id) == w.ids["rh2"]
        event = db.execute(select(AuditEvent).where(AuditEvent.action == "CAMPAIGN_OWNER_CHANGED")).scalar_one()
        assert event.actor_id == uuid.UUID(w.ids["operator"])


def test_an_operator_supervises_every_campaign_but_reads_none_until_made_preparer(
    tmp_path, mock_oidc_base_url
):
    w = build(tmp_path, mock_oidc_base_url)
    listed = {c["name"] for c in w.operator.get("/api/campaigns").json()}
    assert listed == {"Entretiens RH 2027", "NDA Juridique"}
    dashboard = w.operator.get("/api/campaigns/_meta/dashboard").json()
    assert dashboard["campaigns"]["active"] == 2 and dashboard["assignments"]["expected"] == 2
    signature = sign(w.bob, w.hr_version, w.hr)
    for url in (
        f"/api/documents/versions/{w.hr_version}/content",
        f"/api/signatures/{signature}/signed-pdf",
        f"/api/signatures/{signature}/evidence",
        f"/api/signatures/{signature}/certificate",
    ):
        assert w.operator.get(url).status_code in (403, 404), url
    assert w.operator.get(f"/api/campaigns/{w.hr}/assignments").status_code == 200  # progress
    # Made a preparer of THIS campaign, explicitly and with a trace, it opens up — for it only.
    assert w.operator.post(f"/api/campaigns/{w.hr}/preparers", json={"user_id": w.ids["operator"]}
                           ).status_code == 201
    assert w.operator.get(f"/api/signatures/{signature}/signed-pdf").status_code == 200
    assert w.operator.get(f"/api/documents/versions/{w.law_version}/content").status_code in (403, 404)
    with w.app.state.session_factory() as db:
        assert db.execute(select(AuditEvent).where(
            AuditEvent.action == "CAMPAIGN_PREPARER_ADDED")).scalar_one().actor_id == uuid.UUID(
            w.ids["operator"])


# --- one directory, one SSO ---------------------------------------------------------------------


def test_one_directory_is_active_and_only_it_is_synced(tmp_path, mock_oidc_base_url):
    app = make_app(tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY, crashtest=True)

    def client():
        with httpx.Client(transport=httpx.MockTransport(_entra_handler)) as c:
            yield c

    app.dependency_overrides[get_directory_http_client] = client
    with TestClient(app) as admin:
        Base.metadata.create_all(app.state.engine)
        login_as(admin, mock_oidc_base_url, sub="u-direction-1")
        active = lambda: [s["source"] for s in admin.get("/api/admin/directory/sources").json() if s["active"]]  # noqa: E731
        assert active() == ["local"]  # nothing configured: the bundled demonstration directory
        assert admin.put("/api/admin/directory/sources/entra/config", json={
            "fields": ENTRA_FIELDS, "secret": "s3cr3t-value~Xyz"}).status_code == 200
        assert active() == ["entra"]
        refused = admin.post("/api/admin/directory/sync?source=local")
        assert refused.status_code == 409 and "Un seul annuaire est actif" in refused.json()["detail"]
        assert admin.post("/api/admin/directory/sync?source=entra").json()["status"] == "SUCCESS"
        # Switching back is explicit; users already imported stay where they are.
        assert admin.post("/api/admin/directory/sources/local/activate").status_code == 200
        assert active() == ["local"]
        assert admin.post("/api/admin/directory/sync?source=entra").status_code == 409
        assert admin.post("/api/admin/directory/sources/google/activate").status_code == 409  # not set up
        assert admin.post("/api/admin/directory/sources/entra/activate").status_code == 200
        assert active() == ["entra"]
        # Removing the active connector leaves the bundled directory in use.
        assert admin.delete("/api/admin/directory/sources/entra/config").status_code == 204
        assert active() == ["local"]


def test_setting_the_sso_leaves_the_directory_alone_and_the_other_way_round(
    tmp_path, mock_oidc_base_url
):
    app = make_app(tmp_path, mock_oidc_base_url, master_key=TEST_MASTER_KEY)
    tenant = "73405479-f042-45d7-8149-c90341261b65"
    client_id = "333a1a3e-1d45-4661-9c9e-2c91d7b0c5d3"
    with TestClient(app) as admin:
        Base.metadata.create_all(app.state.engine)
        login_as(admin, mock_oidc_base_url, sub="u-direction-1")
        assert admin.put("/api/admin/directory/sources/entra/config", json={
            "fields": ENTRA_FIELDS, "secret": "s3cr3t-value~Xyz"}).status_code == 200
        assert admin.put("/api/admin/login-providers/entra", json={
            "client_id": client_id, "tenant_id": tenant, "client_secret": "another-secret-1"}
        ).status_code == 200
        sources = {s["source"]: s for s in admin.get("/api/admin/directory/sources").json()}
        assert sources["entra"]["configured"] and sources["entra"]["active"]
        assert sources["entra"]["fields"]["client_id"] == ENTRA_FIELDS["client_id"]  # not the SSO's
        assert admin.delete("/api/admin/login-providers/entra").status_code == 204
        sources = {s["source"]: s for s in admin.get("/api/admin/directory/sources").json()}
        assert sources["entra"]["configured"] and sources["entra"]["active"]
        assert admin.put("/api/admin/directory/sources/google/config", json={
            "fields": {"admin_email": "a@corp.test"}, "secret": "{}"}).status_code in (200, 422)
        assert admin.get("/api/admin/login-providers").json()[0]["configured"] is False


# --- the migration ------------------------------------------------------------------------------


def _migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "backend" / "migrations" / "versions" / "0024_identity_access_model.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0024", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_gives_everyone_active_signer_and_retires_preparer(tmp_path):  # N
    engine = sa.create_engine(f"sqlite:///{tmp_path}/m.db")
    ids = {name: str(uuid.uuid4()) for name in ("plain", "admin", "operator", "prep", "off", "had")}
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id CHAR(32) PRIMARY KEY, active BOOLEAN)"))
        conn.execute(sa.text(
            "CREATE TABLE user_roles (user_id CHAR(32), role VARCHAR(20), granted_at TIMESTAMP,"
            " PRIMARY KEY (user_id, role))"))
        conn.execute(sa.text(
            "CREATE TABLE login_providers (provider VARCHAR(20) PRIMARY KEY, client_id VARCHAR(255))"))
        conn.execute(sa.text(
            "CREATE TABLE directory_connector_configs (source VARCHAR(50) PRIMARY KEY,"
            " encrypted_secret VARCHAR(10000), updated_at TIMESTAMP)"))
        for name, active in (("plain", 1), ("admin", 1), ("operator", 1), ("prep", 1), ("off", 0), ("had", 1)):
            conn.execute(sa.text("INSERT INTO users VALUES (:i, :a)"), {"i": ids[name], "a": active})
        for name, role in (("admin", "ADMIN"), ("operator", "OPERATOR"), ("prep", "PREPARER"),
                           ("off", "PREPARER"), ("had", "SIGNER"), ("had", "PREPARER")):
            conn.execute(sa.text("INSERT INTO user_roles VALUES (:i, :r, CURRENT_TIMESTAMP)"),
                         {"i": ids[name], "r": role})
        conn.execute(sa.text("INSERT INTO login_providers VALUES ('google', 'g'), ('entra', 'e')"))
        conn.execute(sa.text(
            "INSERT INTO directory_connector_configs VALUES"
            " ('local', NULL, '2026-01-01'), ('google', 'x', '2026-01-02'), ('entra', 'y', '2026-02-01')"))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            _migration().upgrade()
        roles = {name: sorted(r for (r,) in conn.execute(
            sa.text("SELECT role FROM user_roles WHERE user_id = :i"), {"i": ids[name]}))
            for name in ids}
        assert roles == {
            "plain": ["SIGNER"],                  # nothing before: SIGNER
            "admin": ["ADMIN", "SIGNER"],         # ADMIN kept, SIGNER added
            "operator": ["OPERATOR", "SIGNER"],
            "prep": ["SIGNER"],                   # PREPARER → SIGNER, PREPARER gone
            "off": ["SIGNER"],                    # even inactive: what they could do stays possible
            "had": ["SIGNER"],                    # no duplicate
        }
        assert conn.execute(sa.text("SELECT COUNT(*) FROM user_roles WHERE role='PREPARER'")).scalar() == 0
        assert conn.execute(sa.text("SELECT provider FROM login_providers WHERE active")).scalars().all() == ["entra"]
        assert conn.execute(sa.text(
            "SELECT source FROM directory_connector_configs WHERE active")).scalars().all() == ["entra"]
