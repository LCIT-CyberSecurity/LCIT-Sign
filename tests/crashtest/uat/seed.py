"""Seed the CrashTests dataset (fictional "LCIT CrashTest" organisation).

Directory of 24 users / 6 groups, three roles, two published documents, a
campaign targeting the IT and RH groups, and a few real signatures plus a
signed report — enough to exercise the dashboards and the restore test.
"""
from __future__ import annotations

from crashlib import ADMIN, OPERATOR, SIGNERS, expect, login, main_guard, me, pdf_bytes


def run() -> int:
    admin = login(ADMIN)
    operator = login(OPERATOR)
    signers = [login(sub) for sub in SIGNERS]

    expect(admin.post("/api/admin/directory/sync"), 200)

    # Roles first: reading the groups is for operators, who have none on a fresh stack.
    for client, role in [(operator, "OPERATOR"), *[(s, "SIGNER") for s in signers]]:
        expect(admin.post(f"/api/admin/users/{me(client)['id']}/roles", json={"role": role}),
               200, 201, 409)
    groups = {g["name"]: g["id"] for g in operator.get("/api/admin/directory/groups").json()}

    versions = []
    for title, size in (("Charte informatique 2026", 200), ("Politique BYOD", 300)):
        document = expect(
            operator.post(
                "/api/documents",
                data={"title": title, "version_label": "1.0"},
                files={"file": (f"{title}.pdf", pdf_bytes(size, size), "application/pdf")},
            ),
            201,
        ).json()
        version_id = document["versions"][0]["id"]
        expect(operator.post(f"/api/documents/versions/{version_id}/publish"), 200)
        versions.append(version_id)

    campaign = expect(
        operator.post("/api/campaigns", json={"name": "Campagne sécurité 2026"}), 201
    ).json()
    for version_id in versions:
        expect(
            operator.post(
                f"/api/campaigns/{campaign['id']}/documents",
                json={"document_version_id": version_id},
            ),
            201,
        )
    expect(
        operator.post(
            f"/api/campaigns/{campaign['id']}/launch",
            json={
                "group_ids": [groups["IT"], groups["RH"]],
                "reminder_first_days": 7,
                "reminder_interval_days": 7,
                "reminder_max_count": 3,
            },
        ),
        200,
    )

    signed = 0
    for client in signers[:2]:  # it-1 and rh-1 are in the targeted groups
        for version_id in versions:
            response = client.post(
                f"/api/documents/versions/{version_id}/sign", json={"consent": True}
            )
            expect(response, 201, 409)
            signed += response.status_code == 201

    expect(operator.post(f"/api/campaigns/{campaign['id']}/reports"), 201)
    print(  # noqa: T201
        f"Seeded: 24 directory users, 2 documents, 1 campaign, {signed} new signature(s), 1 report."
    )
    return 0


if __name__ == "__main__":
    main_guard(run)
