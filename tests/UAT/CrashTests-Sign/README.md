# CrashTests-Sign

Scripted acceptance tests against a **running Docker stack**, using the
fictional "LCIT CrashTest" organisation (24 users, 6 groups: Direction, RH,
Comptabilité, Sales, IT, Consultants). No real personal data, no real secret:
the identities are the mock OIDC provider's.

Run them on the machine that hosts the stack (the Integrations VM):

```bash
# from the dev machine
export LCIT_SIGN_INTEGRATION_HOST=vm-integrations LCIT_SIGN_INTEGRATION_USER=cdev
scripts/integration-run.sh tests/UAT/CrashTests-Sign/run-all.sh
```

| Script | What it does |
|---|---|
| `smoke.py` | Fast deployment check (spec §86): frontend, API, PostgreSQL, filesystem, signing key, PDF upload/read, campaign, signature, verification |
| `seed.py` | Loads the CrashTests dataset: directory, roles, 2 documents, a campaign, signatures, a signed report |
| `restore-test.sh` | Backup → blank install (throwaway DB and volume) → restore → every signature verifies; also corrupts a file to prove detection (spec §116) |
| `run-all.sh` | smoke → seed → restore |

Reset to a clean state (destructive, Integrations VM only):

```bash
scripts/integration-run.sh scripts/integration-reset.sh --yes --seed
```
