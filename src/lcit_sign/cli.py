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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lcit_sign.cli")
    parser.add_argument("command", choices=["verify-all"])
    parser.parse_args(argv)
    result = verify_all()
    print(json.dumps(result, indent=2))  # noqa: T201
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
