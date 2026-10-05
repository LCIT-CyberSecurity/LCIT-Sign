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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lcit_sign.cli")
    parser.add_argument("command", choices=["verify-all", "reset-admin-password"])
    args = parser.parse_args(argv)
    if args.command == "reset-admin-password":
        return reset_admin_password()
    result = verify_all()
    print(json.dumps(result, indent=2))  # noqa: T201
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
