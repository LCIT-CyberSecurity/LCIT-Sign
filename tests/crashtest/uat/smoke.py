"""Fast smoke test (spec §86): is a freshly deployed stack actually usable?

Frontend, API health and readiness, database/filesystem/signing key (through
the admin diagnostics), PDF upload and read, campaign creation, a signature
and its verification — every step through the real HTTP stack and SSO.
"""
from __future__ import annotations

import os
import uuid

import httpx
from crashlib import (
    ADMIN,
    BASE_URL,
    OPERATOR,
    SIGNERS,
    Smoke,
    expect,
    login,
    main_guard,
    me,
    pdf_bytes,
)


def run() -> int:
    smoke = Smoke()
    anonymous = httpx.Client(base_url=BASE_URL, timeout=20.0)

    smoke.check(
        "frontend is served",
        lambda: expect(anonymous.get("/"), 200).text.__contains__('id="root"') or 1 / 0,
    )
    smoke.check("API liveness", lambda: expect(anonymous.get("/api/health"), 200))
    smoke.check("API readiness (PostgreSQL)", lambda: expect(anonymous.get("/api/ready"), 200))
    smoke.check(
        "unauthenticated API is refused", lambda: expect(anonymous.get("/api/documents"), 401)
    )

    admin = smoke.check("SSO login as ADMIN", lambda: login(ADMIN))
    operator = smoke.check("SSO login as OPERATOR", lambda: login(OPERATOR))
    signer = smoke.check("SSO login as SIGNER", lambda: login(SIGNERS[0]))
    if not (admin and operator and signer):
        return smoke.finish()

    # Roles are idempotent to grant; ignore "already granted".
    def grant(client, role):  # type: ignore[no-untyped-def]
        expect(admin.post(f"/api/admin/users/{me(client)['id']}/roles", json={"role": role}),
               201, 200, 409)

    smoke.check("grant OPERATOR", lambda: grant(operator, "OPERATOR"))
    smoke.check("grant SIGNER", lambda: grant(signer, "SIGNER"))

    def diagnostics() -> None:
        body = expect(admin.get("/api/admin/diagnostics"), 200).json()
        by_name = {c["name"]: c["status"] for c in body["checks"]}
        for required in ("database", "filesystem", "signing_key"):
            assert by_name[required] in ("OK", "WARN"), f"{required}: {by_name[required]}"

    smoke.check("diagnostics: database, filesystem, signing key", diagnostics)
    smoke.check(
        "audit chain intact",
        lambda: expect(admin.get("/api/admin/audit/integrity"), 200).json()["valid"] or 1 / 0,
    )

    title = f"Smoke {uuid.uuid4().hex[:8]}"

    def upload() -> str:
        response = expect(
            operator.post(
                "/api/documents",
                data={"title": title, "version_label": "1.0"},
                files={"file": ("smoke.pdf", pdf_bytes(), "application/pdf")},
            ),
            201,
        ).json()
        version_id = response["versions"][0]["id"]
        expect(operator.post(f"/api/documents/versions/{version_id}/publish"), 200)
        return str(version_id)

    version_id = smoke.check("PDF upload and publish", upload)
    if not version_id:
        return smoke.finish()
    smoke.check(
        "PDF read back",
        lambda: expect(operator.get(f"/api/documents/versions/{version_id}/content"), 200)
        .content.startswith(b"%PDF-") or 1 / 0,
    )

    def campaign() -> str:
        created = expect(operator.post("/api/campaigns", json={"name": title}), 201).json()
        expect(
            operator.post(
                f"/api/campaigns/{created['id']}/documents",
                json={"document_version_id": version_id},
            ),
            201,
        )
        expect(
            operator.post(
                f"/api/campaigns/{created['id']}/launch", json={"user_ids": [me(signer)["id"]]}
            ),
            200,
        )
        return str(created["id"])

    smoke.check("campaign creation and launch", campaign)

    def sign() -> str:
        response = expect(
            signer.post(f"/api/documents/versions/{version_id}/sign", json={"consent": True}), 201
        ).json()
        return str(response["id"])

    signature_id = smoke.check("signature", sign)
    if signature_id:
        smoke.check(
            "signature verification",
            lambda: expect(signer.get(f"/api/signatures/{signature_id}/verify"), 200).json()[
                "valid"
            ] or 1 / 0,
        )

    def double_click() -> None:
        """Two simultaneous signature requests (double click, two tabs): the
        database constraint must let exactly one through (spec §39, §118)."""
        from concurrent.futures import ThreadPoolExecutor

        race_title = f"Race {uuid.uuid4().hex[:8]}"
        created = expect(
            operator.post(
                "/api/documents",
                data={"title": race_title, "version_label": "1.0"},
                files={"file": ("race.pdf", pdf_bytes(210, 210), "application/pdf")},
            ),
            201,
        ).json()
        race_version = created["versions"][0]["id"]
        expect(operator.post(f"/api/documents/versions/{race_version}/publish"), 200)
        race_campaign = expect(
            operator.post("/api/campaigns", json={"name": race_title}), 201
        ).json()
        expect(
            operator.post(
                f"/api/campaigns/{race_campaign['id']}/documents",
                json={"document_version_id": race_version},
            ),
            201,
        )
        expect(
            operator.post(
                f"/api/campaigns/{race_campaign['id']}/launch",
                json={"user_ids": [me(signer)["id"]]},
            ),
            200,
        )

        def attempt(_: int) -> int:
            return signer.post(
                f"/api/documents/versions/{race_version}/sign", json={"consent": True}
            ).status_code

        with ThreadPoolExecutor(max_workers=4) as pool:
            codes = sorted(pool.map(attempt, range(4)))
        assert codes.count(201) == 1, f"expected exactly one signature, got {codes}"
        assert all(code in (201, 409) for code in codes), codes

    smoke.check("simultaneous signatures create exactly one", double_click)

    if os.environ.get("LCIT_SIGN_SMOKE_SMTP"):
        # The test Postfix (compose.test.yaml) is on the stack's network
        # as `postfix-test`: plain port 25, fictional local mailboxes only.
        def configure_smtp() -> None:
            expect(
                admin.put(
                    "/api/admin/mail-connector",
                    json={
                        "host": "postfix-test", "port": 25, "use_tls": False,
                        "use_starttls": False, "username": "",
                        "from_address": "lcit-sign@lcit-test.local",
                    },
                ),
                200,
            )

        def smtp_diagnostics() -> None:
            diag = expect(admin.post("/api/admin/mail-connector/test-connection"), 200).json()
            assert diag["dns"] == "OK" and diag["tcp"] == "OK", diag

        smoke.check("SMTP connector configured (test Postfix)", configure_smtp)
        smoke.check("SMTP connection diagnostics", smtp_diagnostics)
        smoke.check(
            "SMTP test e-mail accepted",
            lambda: expect(
                admin.post(
                    "/api/admin/mail-connector/send-test",
                    json={"to": "alice.martin@lcit-test.local"},
                ),
                200,
            ),
        )
    else:
        smoke.skip("SMTP / Postfix", "set LCIT_SIGN_SMOKE_SMTP=1 with the test Postfix running")
    return smoke.finish()


if __name__ == "__main__":
    main_guard(run)
