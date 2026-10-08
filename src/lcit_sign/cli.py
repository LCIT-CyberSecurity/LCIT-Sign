"""Offline integrity checks: `python -m lcit_sign.cli verify-all`.

Re-verifies every stored signature and report, and the audit chain, straight
from the database and the storage volume. Used after a restore (spec §116:
"toutes les anciennes signatures doivent rester vérifiables") and handy as a
periodic integrity job. Exit status 0 only when everything is valid.
"""
from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import select

from lcit_sign.config import get_settings
from lcit_sign.database import make_engine, make_session_factory
from lcit_sign.models.report import Report
from lcit_sign.models.signature import Signature
from lcit_sign.services.audit import verify_audit_chain
from lcit_sign.services.storage import StorageService
from lcit_sign.services.verification import verify_report_record, verify_signature_record


def verify_all() -> dict[str, object]:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    storage = StorageService(settings.storage_root)
    failures: list[str] = []
    with make_session_factory(engine)() as db:
        signatures = list(db.execute(select(Signature)).scalars())
        for signature in signatures:
            checks = verify_signature_record(db, storage, signature)
            if not all(checks.values()):
                bad = sorted(name for name, passed in checks.items() if not passed)
                failures.append(f"signature {signature.id}: {', '.join(bad)}")
        reports = list(db.execute(select(Report)).scalars())
        for report in reports:
            checks = verify_report_record(db, storage, report)
            if not all(checks.values()):
                bad = sorted(name for name, passed in checks.items() if not passed)
                failures.append(f"report {report.id}: {', '.join(bad)}")
        chain_ok, broken_at = verify_audit_chain(db)
        if not chain_ok:
            failures.append(f"audit chain broken at event #{broken_at}")
    engine.dispose()
    return {
        "signatures": len(signatures),
        "reports": len(reports),
        "audit_chain_ok": chain_ok,
        "failures": failures,
        "ok": not failures,
    }


def reset_admin_password() -> int:
    """Break-glass: set a new password on the built-in account (run it with
    `docker compose exec -it api python -m lcit_sign.cli reset-admin-password`).
    The password is typed at a hidden prompt, never taken from a command line."""
    import getpass
    from datetime import UTC, datetime

    from lcit_sign.models.session import Session as SessionRecord
    from lcit_sign.models.user import User
    from lcit_sign.services.audit import append_audit_event
    from lcit_sign.services.local_auth import BUILTIN_ISSUER, ensure_builtin_admin
    from lcit_sign.services.passwords import hash_password, is_acceptable_for_production

    settings = get_settings()
    first = getpass.getpass("Nouveau mot de passe du compte système : ")
    if first != getpass.getpass("Confirmez : "):
        print("Les deux saisies diffèrent.")  # noqa: T201
        return 1
    problem = is_acceptable_for_production(first)
    if problem:
        print(f"Mot de passe refusé : {problem}")  # noqa: T201
        return 1
    engine = make_engine(settings.database_url)
    with make_session_factory(engine)() as db:
        ensure_builtin_admin(db, settings)
        user = db.execute(
            select(User).where(
                User.issuer == BUILTIN_ISSUER, User.subject == settings.local_admin_username
            )
        ).scalar_one_or_none()
        if user is None:
            print("Le compte système est désactivé (LCIT_SIGN_LOCAL_AUTH_ENABLED=false).")  # noqa: T201
            return 1
        user.password_hash = hash_password(first)
        user.must_change_password = False
        for session in db.execute(
            select(SessionRecord).where(
                SessionRecord.user_id == user.id, SessionRecord.revoked_at.is_(None)
            )
        ).scalars():
            session.revoked_at = datetime.now(UTC)
        append_audit_event(
            db, action="USER_UPDATED", target_type="user", target_id=str(user.id),
            metadata={"change": "password_reset_by_cli"},
        )
        db.commit()
    print("Mot de passe du compte système mis à jour ; ses sessions ont été fermées.")  # noqa: T201
    return 0


def export_connections() -> int:
    """The sign-in providers and directory connectors as stored: client ids and the secrets still
    ENCRYPTED under the master key (useless without it). Meant for a private file outside the
    repository, to restore the same settings later instead of typing them again."""
    from lcit_sign.models.directory import DirectoryConnectorConfig
    from lcit_sign.models.login_provider import LoginProvider

    settings = get_settings()
    with make_session_factory(make_engine(settings.database_url))() as db:
        out = {
            "version": 1,
            "login_providers": [
                {"provider": r.provider, "client_id": r.client_id, "tenant_id": r.tenant_id,
                 "encrypted_secret": r.encrypted_secret, "active": r.active}
                for r in db.execute(select(LoginProvider)).scalars()
            ],
            "directory_connectors": [
                {"source": r.source, "settings_json": r.settings_json,
                 "encrypted_secret": r.encrypted_secret,
                 "sync_interval_minutes": r.sync_interval_minutes, "active": r.active}
                for r in db.execute(select(DirectoryConnectorConfig)).scalars()
                if r.source != "local"
            ],
        }
    print(json.dumps(out, indent=2))  # noqa: T201
    return 0


def import_connections() -> int:
    """Put back what `export-connections` wrote (JSON on stdin). Refuses secrets that this
    installation's master key cannot read."""
    from lcit_sign.models.directory import DirectoryConnectorConfig
    from lcit_sign.models.login_provider import LoginProvider
    from lcit_sign.services.crypto import decrypt_secret

    settings = get_settings()
    data = json.load(sys.stdin)
    rows = [*data.get("login_providers", []), *data.get("directory_connectors", [])]
    for row in rows:
        if row.get("encrypted_secret"):
            try:
                decrypt_secret(settings.master_key, row["encrypted_secret"])
            except Exception:  # noqa: BLE001 - wrong key or damaged file
                name = row.get("provider") or row.get("source")
                print(f"« {name} » : le secret ne se déchiffre pas avec la clé maître de cette "  # noqa: T201
                      "installation (ce n'est pas la même que celle de l'export).")
                return 1
    with make_session_factory(make_engine(settings.database_url))() as db:
        for r in data.get("login_providers", []):
            row = db.get(LoginProvider, r["provider"]) or LoginProvider(provider=r["provider"])
            row.client_id, row.tenant_id = r["client_id"], r.get("tenant_id")
            row.encrypted_secret = r["encrypted_secret"]
            row.active = False  # decided below: one at a time
            db.add(row)
        for r in data.get("directory_connectors", []):
            cfg = db.get(DirectoryConnectorConfig, r["source"]) or DirectoryConnectorConfig(
                source=r["source"]
            )
            cfg.settings_json = r["settings_json"]
            cfg.encrypted_secret = r.get("encrypted_secret")
            cfg.sync_interval_minutes = r.get("sync_interval_minutes")
            cfg.active = False
            db.add(cfg)
        db.flush()
        # One sign-in provider and one directory at a time: the exported file says which (an old
        # file without it: the first provider, the first remote connector).
        providers = data.get("login_providers", [])
        if providers:
            chosen = next((p for p in providers if p.get("active")), providers[0])
            db.get(LoginProvider, chosen["provider"]).active = True  # type: ignore[union-attr]
        remotes = [c for c in data.get("directory_connectors", []) if c["source"] != "local"]
        if remotes:
            chosen = next((c for c in remotes if c.get("active")), remotes[0])
            db.get(DirectoryConnectorConfig, chosen["source"]).active = True  # type: ignore[union-attr]
        db.commit()
    print(f"{len(rows)} connexion(s) restaurée(s).")  # noqa: T201
    return 0


def export_mock_providers() -> int:
    """The real accounts the CrashTest mock SSO may offer (Entra, Google), as the JSON file the
    mock reads, built from the connections already stored in this installation:
      * a sign-in provider set up under Identités & accès (Microsoft / Google), else
      * for Entra only, the application of the Entra directory connector (same registration).
    The secrets are decrypted here and go to STDOUT for crashtest/start.sh to write into a
    private file (mode 600) outside the repository; nothing is logged."""
    from lcit_sign.models.directory import DirectoryConnectorConfig
    from lcit_sign.models.login_provider import LoginProvider
    from lcit_sign.services.crypto import decrypt_secret

    settings = get_settings()
    out: dict[str, dict[str, str]] = {}
    with make_session_factory(make_engine(settings.database_url))() as db:
        for row in db.execute(select(LoginProvider)).scalars():
            secret = decrypt_secret(settings.master_key, row.encrypted_secret)
            if row.provider == "entra" and row.tenant_id:
                out["entra"] = {"tenant_id": row.tenant_id, "client_id": row.client_id,
                                "client_secret": secret}
            elif row.provider == "google":
                out["google"] = {"client_id": row.client_id, "client_secret": secret}
        directory = db.get(DirectoryConnectorConfig, "entra")
        if "entra" not in out and directory is not None and directory.encrypted_secret:
            fields = json.loads(directory.settings_json)
            if fields.get("tenant_id") and fields.get("client_id"):
                out["entra"] = {
                    "tenant_id": fields["tenant_id"], "client_id": fields["client_id"],
                    "client_secret": decrypt_secret(
                        settings.master_key, directory.encrypted_secret
                    ),
                }
    print(json.dumps(out))  # noqa: T201
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lcit_sign.cli")
    parser.add_argument(
        "command",
        choices=[
            "verify-all", "reset-admin-password", "export-connections", "import-connections",
            "export-mock-providers",
        ],
    )
    args = parser.parse_args(argv)
    if args.command == "reset-admin-password":
        return reset_admin_password()
    if args.command == "export-connections":
        return export_connections()
    if args.command == "import-connections":
        return import_connections()
    if args.command == "export-mock-providers":
        return export_mock_providers()
    result = verify_all()
    print(json.dumps(result, indent=2))  # noqa: T201
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
