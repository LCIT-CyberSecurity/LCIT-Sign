"""The CrashTest dataset: a fictional company, fictional accounts, a few campaigns in every state.

Runs INSIDE the api container of the CrashTest stack (tests/crashtest/start.sh does it):

    docker compose ... exec -T api python /crashtest/seed.py

Two guards, both required, so that this can never create "Alice" and "Bob" on a real installation:
the stack must say it is CrashTest (LCIT_SIGN_CRASHTEST=true, set only by
tests/crashtest/compose.crashtest.yaml) and its database must be named *_crashtest.

The accounts are local accounts whose password is the FIRST NAME IN LOWERCASE ("Bob Dupont" =>
bob). That is only acceptable because they are fictional and exist only here; the database holds
the usual scrypt hash, never the password. The same people can also sign in through the mock SSO.
"""
from __future__ import annotations

import os
import sys
import uuid
from io import BytesIO

import httpx
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from lcit_sign.auth.cookies import SESSION_COOKIE
from lcit_sign.config import Settings
from lcit_sign.database import make_engine, make_session_factory
from lcit_sign.models.directory import Group, GroupMembership
from lcit_sign.models.user import Role, User, UserRole
from lcit_sign.services.directory_sync import sync_local_directory
from lcit_sign.services.local_auth import LOCAL_ISSUER
from lcit_sign.services.passwords import hash_password

DOMAIN = "lcit-test.local"

# People added to the 24 of the demonstration directory (services/directory_sync.py).
EXTRA_PEOPLE = [
    # email, first name, last name, group
    ("sophie.bernard", "Sophie", "Bernard", "RH"),
    ("claire.moreau", "Claire", "Moreau", "Direction"),
    ("paul.muller", "Paul", "Muller", "Direction"),
    ("admin.crash", "Admin", "Crash", "Direction"),
]

# Everyone is a SIGNER by default (the standard user: prepares, sends, signs); these come on top.
# Alice, Sophie (RH), Claire (Legal) and Diane (Sales) are plain signers who run their campaigns.
ROLES: dict[str, list[Role]] = {
    "admin.crash": [Role.ADMIN],
    "paul.muller": [Role.OPERATOR],  # business administrator: sees every campaign, not its content
}


def guard(settings: Settings) -> None:
    """Refuse unless this really is the CrashTest stack."""
    problems = []
    if not settings.crashtest:
        problems.append("LCIT_SIGN_CRASHTEST n'est pas « true »")
    if settings.environment == "production":
        problems.append("l'environnement est « production »")
    database = make_url(settings.database_url).database or ""
    if not database.endswith("_crashtest"):
        problems.append(f"la base « {database} » ne se termine pas par _crashtest")
    if problems:
        raise SystemExit(
            "Refusé : le jeu de données CrashTest ne se charge que sur la pile CrashTest ("
            + " ; ".join(problems)
            + "). Utilisez tests/crashtest/start.sh."
        )


def password_of(first_name: str) -> str:
    """The convention: first name, lowercase, accents kept out ("Bob" => "bob")."""
    return first_name.strip().lower()


# --- phase A: the accounts, straight in the database ------------------------------------------


def seed_accounts(db: Session) -> list[tuple[str, str, str, list[str]]]:
    """Create the people, their passwords, roles and groups. Returns what to tell the tester:
    (name, e-mail, password, roles)."""
    sync_local_directory(db)  # 24 people in 6 groups (directory:local)
    groups = {g.name: g for g in db.execute(select(Group)).scalars()}
    for local_part, first, last, group in EXTRA_PEOPLE:
        email = f"{local_part}@{DOMAIN}"
        if db.execute(select(User.id).where(User.email == email)).first():
            continue
        person = User(
            issuer=LOCAL_ISSUER, subject=f"crashtest:{uuid.uuid4()}", email=email,
            given_name=first, family_name=last, display_name=f"{first} {last}", active=True,
        )
        db.add(person)
        db.flush()
        if group in groups:
            db.add(GroupMembership(group_id=groups[group].id, user_id=person.id))
    db.flush()

    told = []
    for person in db.execute(
        select(User).where(User.email.like(f"%@{DOMAIN}")).order_by(User.family_name)
    ).scalars():
        password = password_of(person.given_name)
        person.password_hash = hash_password(password)
        person.must_change_password = False
        # Everyone can sign (the default); the roles above come on top.
        wanted = [Role.SIGNER, *ROLES.get(person.email.split("@")[0], [])]
        have = set(db.execute(select(UserRole.role).where(UserRole.user_id == person.id)).scalars())
        for role in wanted:
            if role not in have:
                db.add(UserRole(user_id=person.id, role=role))
        told.append((person.display_name, person.email, password, [r.value for r in wanted]))
    db.commit()
    return told


# --- phase B: documents and campaigns, through the API as the right people ---------------------


def pdf_bytes(size: int = 200) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=size, height=size)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def local_session(api: str, origin: str, email: str) -> httpx.Client:
    """A client signed in as `email` with the convention's password."""
    first = email.split("@")[0].split(".")[0]
    client = httpx.Client(base_url=api, headers={"Origin": origin}, timeout=60.0)
    response = client.post(
        "/api/auth/local-login", json={"username": email, "password": password_of(first)}
    )
    if response.status_code != 204:
        raise RuntimeError(f"sign-in of {email} refused (HTTP {response.status_code})")
    # The cookie may be marked Secure while this talks plain HTTP inside the container: send it
    # by hand.
    token = response.cookies.get(SESSION_COOKIE) or next(
        (c.split("=", 1)[1].split(";")[0] for c in response.headers.get_list("set-cookie")
         if c.startswith(f"{SESSION_COOKIE}=")), "")
    client.headers["Cookie"] = f"{SESSION_COOKIE}={token}"
    return client


def ok(response: httpx.Response, *statuses: int) -> httpx.Response:
    if response.status_code not in statuses:
        raise RuntimeError(
            f"{response.request.method} {response.request.url.path} -> HTTP "
            f"{response.status_code}: {response.text[:200]}"
        )
    return response


def publish(client: httpx.Client, title: str, roles: tuple[int, ...] = (1,)) -> str:
    created = ok(client.post(
        "/api/documents", data={"title": title, "version_label": "1.0"},
        files={"file": (f"{title}.pdf", pdf_bytes(), "application/pdf")}), 201).json()
    version = created["versions"][0]["id"]
    fields = [
        {"page": 1, "x": 0.1, "y": 0.2 + 0.2 * n, "width": 0.3, "height": 0.06,
         "kind": "SIGNATURE", "role": role}
        for n, role in enumerate(roles, start=1)
    ]
    ok(client.put(f"/api/documents/versions/{version}/fields", json={"fields": fields}), 200)
    ok(client.post(f"/api/documents/versions/{version}/publish"), 200)
    return version


def campaign(client: httpx.Client, name: str, versions: list[str]) -> str:
    created = ok(client.post("/api/campaigns", json={"name": name}), 201).json()["id"]
    for version in versions:
        added = client.post(
            f"/api/campaigns/{created}/documents", json={"document_version_id": version}
        )
        ok(added, 201)
    return created


def user_id(client: httpx.Client, email: str) -> str:
    users = ok(client.get("/api/campaigns/_meta/users"), 200).json()
    return next(u["id"] for u in users if u["email"] == email)


def seed_campaigns(api: str, origin: str) -> None:
    alice = local_session(api, origin, f"alice.martin@{DOMAIN}")
    if any(c["name"] == "Entretiens RH 2027" for c in ok(alice.get("/api/campaigns"), 200).json()):
        print("Les campagnes de démonstration existent déjà.")  # noqa: T201
        return
    claire = local_session(api, origin, f"claire.moreau@{DOMAIN}")
    paul = local_session(api, origin, f"paul.muller@{DOMAIN}")
    diane = local_session(api, origin, f"diane.leroy@{DOMAIN}")
    erwan = local_session(api, origin, f"erwan.petit@{DOMAIN}")
    valerie = local_session(api, origin, f"valerie.andre@{DOMAIN}")

    # RH: Alice owns it; the operator adds Sophie as a preparer (a colleague covering).
    rh_version = publish(alice, "Entretiens annuels 2027")
    rh = campaign(alice, "Entretiens RH 2027", [rh_version])
    ok(alice.post(f"/api/campaigns/{rh}/launch", json={"user_ids": [
        user_id(alice, f"bob.dupont@{DOMAIN}"), user_id(alice, f"manon.faure@{DOMAIN}")]}), 200)
    sophie_id = user_id(paul, f"sophie.bernard@{DOMAIN}")
    ok(paul.post(f"/api/campaigns/{rh}/preparers", json={"user_id": sophie_id}), 201)

    # Juridique: Claire only.
    law_version = publish(claire, "NDA prestataire")
    law = campaign(claire, "NDA Juridique", [law_version])
    ok(claire.post(f"/api/campaigns/{law}/launch", json={"user_ids": [
        user_id(claire, f"charlie.durand@{DOMAIN}")]}), 200)

    # Sécurité: the RSSI (Erwan) signs first, then every person of IT and RH. Erwan has signed, one
    # recipient too, the others are asked.
    groups = {g["name"]: g["id"] for g in ok(diane.get("/api/admin/directory/groups"), 200).json()}
    charter = publish(diane, "Charte informatique 2026", roles=(1, 2))
    byod = publish(diane, "Politique BYOD", roles=(1, 2))
    security = campaign(diane, "Campagne sécurité 2026", [charter, byod])
    ok(diane.put(f"/api/campaigns/{security}/signers", json={"signers": [
        {"role": 1, "mode": "FIXED", "user_id": user_id(diane, f"erwan.petit@{DOMAIN}")},
        {"role": 2, "mode": "EACH"}]}), 200)
    ok(diane.post(f"/api/campaigns/{security}/launch",
                  json={"group_ids": [groups["IT"], groups["RH"]]}), 200)
    for version in (charter, byod):
        ok(erwan.post(f"/api/documents/versions/{version}/sign",
                      json={"consent": True, "campaign_id": security}), 201)
    ok(valerie.post(f"/api/documents/versions/{charter}/sign",
                    json={"consent": True, "campaign_id": security}), 201)

    # Mots de passe: the RSSI has not signed yet, so the recipients are still waiting their turn.
    passwords = publish(diane, "Politique mots de passe", roles=(1, 2))
    waiting = campaign(diane, "Politique mots de passe 2026", [passwords])
    ok(diane.put(f"/api/campaigns/{waiting}/signers", json={"signers": [
        {"role": 1, "mode": "FIXED", "user_id": user_id(diane, f"erwan.petit@{DOMAIN}")},
        {"role": 2, "mode": "EACH"}]}), 200)
    ok(diane.post(f"/api/campaigns/{waiting}/launch", json={"group_ids": [groups["Sales"]]}), 200)
    print("Campagnes créées : RH (pending), Juridique (pending), Sécurité (signed + pending), "  # noqa: T201
          "Mots de passe (waiting).")
    # The co-preparer really sees it.
    sophie = local_session(api, origin, f"sophie.bernard@{DOMAIN}")
    ok(sophie.get(f"/api/campaigns/{rh}"), 200)


def main() -> int:
    settings = Settings()
    guard(settings)
    engine = make_engine(settings.database_url)
    with make_session_factory(engine)() as db:
        accounts = seed_accounts(db)
    seed_campaigns(
        os.environ.get("CRASHTEST_API", "http://127.0.0.1:8000"), settings.public_base_url
    )

    print("\nComptes fictifs (identifiant = e-mail, mot de passe = prénom en minuscules) :")  # noqa: T201
    for name, email, password, roles in accounts:
        label = ", ".join(roles) if roles else "utilisateur"
        print(f"  {name:<20} {email:<34} mot de passe : {password:<10} [{label}]")  # noqa: T201
    print("\nCompte système : admin / SecretPassword (à changer à la première connexion).")  # noqa: T201
    print("Le SSO de test propose les mêmes personnes (un clic).")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
