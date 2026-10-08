"""The CrashTest environment: it loads only on the CrashTest stack, its accounts follow the
convention (password = first name in lowercase) with a real hash in the database, and a normal
installation has no mock SSO and no fictional account."""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_auth_flow import login_as, make_app

from lcit_sign import models  # noqa: F401 - registers tables
from lcit_sign.config import Settings
from lcit_sign.database import Base
from lcit_sign.models.user import Role, User, UserRole

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("crashtest_seed", ROOT / "crashtest" / "seed.py")
assert spec and spec.loader
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def settings(**over) -> Settings:
    base = {
        "database_url": "postgresql+psycopg://u:p@db:5432/lcit_sign_crashtest",
        "crashtest": True,
        "environment": "development",
    }
    return Settings(**{**base, **over})


# --- the guard -------------------------------------------------------------------------------


def test_the_dataset_loads_on_the_crashtest_stack():
    seed.guard(settings())  # does not raise


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"crashtest": False}, "LCIT_SIGN_CRASHTEST"),
        ({"environment": "production"}, "production"),
        ({"database_url": "postgresql+psycopg://u:p@db:5432/lcit_sign"}, "_crashtest"),
        ({"database_url": "postgresql+psycopg://u:p@db/lcit_sign_crashtest_old"}, "_crashtest"),
        ({"crashtest": False, "database_url": "sqlite:///x.db"}, "LCIT_SIGN_CRASHTEST"),
    ],
)
def test_the_dataset_refuses_everything_else(over, why):
    with pytest.raises(SystemExit) as refused:
        seed.guard(settings(**over))
    assert why in str(refused.value) and "start.sh" in str(refused.value)


def test_a_normal_installation_is_not_crashtest_by_default():
    assert Settings().crashtest is False


@pytest.mark.parametrize("script", ["start.sh", "reset.sh"])
def test_the_scripts_refuse_the_name_of_a_normal_installation(script):
    result = subprocess.run(  # noqa: S603 - our own script, a fixed argument list
        ["/bin/bash", str(ROOT / "crashtest" / script)],
        env={"PATH": "/usr/bin:/bin", "LCIT_SIGN_PREFIX": "lcit-sign"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "installation normale" in result.stderr


# --- the accounts ----------------------------------------------------------------------------


def started(tmp_path, oidc):
    app = make_app(tmp_path, oidc)
    client = TestClient(app)
    client.__enter__()
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as db:
        told = seed.seed_accounts(db)
    return app, client, told


def local_login(client, email, password):
    return client.post("/api/auth/local-login", json={"username": email, "password": password})


def test_each_fictional_person_signs_in_with_their_first_name_in_lowercase(
    tmp_path, mock_oidc_base_url
):
    app, client, told = started(tmp_path, mock_oidc_base_url)
    assert local_login(client, "bob.dupont@lcit-test.local", "bob").status_code == 204
    assert local_login(client, "alice.martin@lcit-test.local", "alice").status_code == 204
    assert local_login(client, "manon.faure@lcit-test.local", "manon").status_code == 204
    assert local_login(client, "bob.dupont@lcit-test.local", "alice").status_code == 401
    # Everyone listed has the convention's password, and it never needs changing.
    for name, _email, password, _roles in told:
        assert password == name.split(" ")[0].lower(), name
    me = TestClient(app)
    local_login(me, "bob.dupont@lcit-test.local", "bob")
    shown = me.get("/api/auth/me").json()
    assert shown["must_change_password"] is False and shown["source"] == "local"



def test_only_the_hash_is_in_the_database(tmp_path, mock_oidc_base_url):
    app, _, told = started(tmp_path, mock_oidc_base_url)
    with app.state.session_factory() as db:
        bob = db.execute(
            select(User).where(User.email == "bob.dupont@lcit-test.local")
        ).scalar_one()
        assert bob.password_hash and bob.password_hash.startswith("scrypt$")
        assert "bob" not in bob.password_hash.split("$")[0]
        assert all("scrypt" not in repr(person) for person in told)


def test_roles_follow_the_dataset_and_seeding_twice_changes_nothing(tmp_path, mock_oidc_base_url):
    app, _, _ = started(tmp_path, mock_oidc_base_url)
    with app.state.session_factory() as db:
        first = seed.seed_accounts(db)

    def roles_of(email: str) -> set[Role]:
        with app.state.session_factory() as db:
            return set(db.execute(select(UserRole.role).join(User, User.id == UserRole.user_id)
                                  .where(User.email == email)).scalars())

    assert roles_of("alice.martin@lcit-test.local") == {Role.SIGNER}
    assert roles_of("sophie.bernard@lcit-test.local") == {Role.SIGNER}
    assert roles_of("claire.moreau@lcit-test.local") == {Role.SIGNER}
    assert roles_of("paul.muller@lcit-test.local") == {Role.SIGNER, Role.OPERATOR}
    assert roles_of("admin.crash@lcit-test.local") == {Role.SIGNER, Role.ADMIN}
    assert roles_of("bob.dupont@lcit-test.local") == {Role.SIGNER}  # everyone can sign
    with app.state.session_factory() as db:
        emails = [e for (e,) in db.execute(select(User.email)).all()]
    assert len(emails) == len(set(emails)) and len(first) == len(emails)


def test_the_same_person_through_the_mock_sso_is_the_same_account(tmp_path, mock_oidc_base_url):
    """The tester can use either: the SSO finds the account by its e-mail address (Sophie is a
    local account of the dataset), keeps the roles, and the password still works."""
    app, client, _ = started(tmp_path, mock_oidc_base_url)
    sso = TestClient(app)
    login_as(sso, mock_oidc_base_url, sub="u-rh-2")  # Sophie Bernard
    me = sso.get("/api/auth/me").json()
    assert me["email"] == "sophie.bernard@lcit-test.local"
    assert sorted(me["roles"]) == ["SIGNER"]
    assert local_login(client, "sophie.bernard@lcit-test.local", "sophie").status_code == 204


# --- a normal installation has no mock SSO ----------------------------------------------------


def test_the_normal_compose_has_no_mock_sso_and_no_default_identity():
    compose = (ROOT / "docker-compose.yml").read_text()
    # The SSO is empty unless the installation sets it; nobody is administrator by default.
    assert "LCIT_SIGN_OIDC_ISSUER: ${LCIT_SIGN_OIDC_ISSUER:-}\n" in compose
    assert "LCIT_SIGN_OIDC_CLIENT_SECRET: ${LCIT_SIGN_OIDC_CLIENT_SECRET:-}\n" in compose
    assert "LCIT_SIGN_BOOTSTRAP_ADMIN: ${LCIT_SIGN_BOOTSTRAP_ADMIN:-}\n" in compose
    assert "alice" not in compose.lower().replace("alice@", "")  # no fictional person
    # The mock SSO only starts under an explicit profile.
    for service in ("mock-oidc",):
        block = re.search(rf"\n  {service}:\n(.*?)(?=\n  [a-z-]+:\n|\nnetworks:)", compose, re.S)
        assert block and 'profiles: ["crashtest", "dev-sso"]' in block.group(1), service


def test_word_and_libreoffice_are_accepted_by_default_everywhere():
    """The isolated converter is part of every stack, and the API points at it unless told
    otherwise; the Kubernetes manifests have it too, with no way out."""
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "LCIT_SIGN_CONVERTER_URL: ${LCIT_SIGN_CONVERTER_URL-http://converter:8090}" in compose
    block = re.search(r"\n  converter:\n(.*?)(?=\n  [a-z-]+:\n|\nnetworks:)", compose, re.S)
    assert block and "profiles:" not in block.group(1)  # no profile to forget
    assert "read_only: true" in block.group(1) and "networks: [converter-net]" in block.group(1)
    k8s = ROOT / "k8s"
    assert "converter.yaml" in (k8s / "kustomization.yaml").read_text()
    config = (k8s / "config.yaml").read_text()
    assert "LCIT_SIGN_CONVERTER_URL: http://lcit-sign-converter:8090" in config
    policy = (k8s / "networkpolicy.yaml").read_text()
    assert "converter-no-egress" in policy and "egress: []" in policy
    assert "readOnlyRootFilesystem: true" in (k8s / "converter.yaml").read_text()


def test_crashtest_wires_the_mock_sso_and_its_own_database():
    override = (ROOT / "crashtest" / "docker-compose.crashtest.yml").read_text()
    assert 'LCIT_SIGN_CRASHTEST: "true"' in override
    assert "http://mock-oidc:8080" in override
    assert "lcit_sign_crashtest" in override
    env = (ROOT / "crashtest" / "crashtest.env").read_text()
    assert re.search(r"^LCIT_SIGN_PREFIX=lcit-sign-crashtest$", env, re.M)  # never "lcit-sign"
