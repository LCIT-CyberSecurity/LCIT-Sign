# CrashTests-Sign

Scripted acceptance tests against a **running Docker stack**, using the
fictional "LCIT CrashTest" organisation (24 users, 6 groups: Direction, RH,
Comptabilité, Sales, IT, Consultants). No real personal data, no real secret:
the identities are the mock OIDC provider's.

Run them on the machine that hosts the stack (the Integrations VM):

```bash
# from the dev machine
export LCIT_SIGN_INTEGRATION_HOST=vm-integrations LCIT_SIGN_INTEGRATION_USER=cdev
ops/dev/integration-run.sh tests/crashtest/uat/run-all.sh
```

| Script | What it does |
|---|---|
| `smoke.py` | Fast deployment check (spec §86): frontend, API, PostgreSQL, filesystem, signing key, PDF upload/read, campaign, signature, verification |
| `seed.py` | Loads the CrashTests dataset: directory, roles, 2 documents, a campaign, signatures, a signed report |
| `restore-test.sh` | Backup → blank install (throwaway DB and volume) → restore → every signature verifies; also corrupts a file to prove detection (spec §116) |
| `run-all.sh` | smoke → seed → restore |

Against another stack than the default one, set `LCIT_SIGN_PROJECT` (Compose project),
`LCIT_SIGN_DATA_VOLUME`, `LCIT_SIGN_API_IMAGE`, `LCIT_SIGN_BASE_URL` and, on a CrashTest stack,
`LCIT_SIGN_DB_NAME=lcit_sign_crashtest`.

Known: the identity the smoke test and `seed.py` use as administrator (`u-direction-1`) is no longer
ADMIN on a CrashTest stack (the bootstrap administrator is empty there), so their administrator-only
checks answer 403. This predates the repository reorganisation.

Reset to a clean state (destructive, Integrations VM only):

```bash
ops/dev/integration-run.sh ops/dev/integration-reset.sh --yes --seed
```
