# LCIT Sign

Internal e-signature and acknowledgement app (IT charter, security policies, house rules, amendments…).
Upload a document, say who signs and in what order, place the elements on the page, send. Everyone
signs from their own desk with their company account, and every signature comes with a proof anyone
can verify.

## Features

- **Single sign-on.** Microsoft Entra ID, Google or a generic OpenID Connect provider (one active at
  a time), plus a local sign-in. People and teams come from one directory (Entra ID, Google Workspace,
  LDAP / Active Directory).
- **Verifiable proof.** Each signature seals the signer's identity, consent, the document's SHA-256 and
  the date with an Ed25519 key; the signed PDF, proof and certificate download in one click.
- **Campaigns.** Several signers in order, mail merge for a team, external people by e-mail,
  deferred start, reminders, periodic renewal, signed campaign report.
- **Prepare in the browser.** Place signature, date, name, e-mail, logo or fill-in fields on the page.
  Word / LibreOffice files are converted to PDF in an isolated container.
- **Mail.** SMTP, Microsoft Graph or Gmail. Credentials are entered in the UI and stored encrypted
  (AES-256-GCM), never in a configuration file.
- **Security.** Chained audit log, no private key stored (signing keys are derived from the master key),
  HTTPS, rate limiting, backup / restore. The repository contains **no secret**.

> The signature is a *simple* electronic signature under eIDAS backed by a strong technical proof, not an
> advanced or qualified one. Out of scope: qualified signatures and timestamps, per-person private keys,
> biometric signatures, S3/MinIO storage.

## Roles

| Role | Who / what |
|---|---|
| **SIGNER** | The standard user, given to every active account: prepares, sends, follows and signs their own requests. Signing needs this role **and** an active signature request |
| **Campaign preparer** | One-off right on a single campaign (collaboration); not a global role |
| **OPERATOR** | Global supervision; no automatic access to confidential content |
| **ADMIN** | Technical administration of LCIT Sign |

## Quick start

```bash
cp .env.example .env         # at least set LCIT_SIGN_DB_PASSWORD
mkdir -p -m 700 certs        # before the first `up` (otherwise Docker creates it as root)
docker compose up -d --build
```

- UI: http://127.0.0.1:4180 (dev) and https://127.0.0.1:4443 (self-signed certificate until one is installed). API under `/api`, health at `/api/health`.
- HTTPS certificate: `scripts/certificate-installer.sh`. Backup / restore: `scripts/backup.sh`, `scripts/restore.sh`.
- **First access.** A fresh installation contains only the local system account `admin` with the
  documented initial password `SecretPassword`, which must be changed at first sign-in (the app reminds
  you until you do). Local sign-in only: no SSO, no directory, no fictional person, group or campaign.
  The administrator then sets up the SSO, the directory and e-mail under *Administration → Identités & accès*.
- **Production.** With `LCIT_SIGN_ENVIRONMENT=production` the app refuses to start if the session secret
  or the master key is empty, a development value or shorter than 32 characters, or if the cookie is not `Secure`.

## CrashTest (tests and demo)

```bash
./crashtest/start.sh     # separate stack: own database and volumes, mock SSO, fictional people and campaigns
./crashtest/reset.sh     # destroys only the CrashTest volumes and reloads the dataset
```

CrashTest is the **only** place with the mock SSO, the fictional directory, Alice, Bob and the other
fictional people, groups and campaigns. See [`crashtest/README.md`](crashtest/README.md).

## Development

```bash
pip install -e '.[dev]' && ruff check . && mypy src && pytest     # backend
cd web && npm ci && npm test && npm run build                     # frontend
scripts/e2e.sh                                                    # end to end, throwaway stack (Docker)
```

Stack: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL · Vite, React · Docker Compose, Kubernetes
manifests · nginx. Tests run in Docker containers on the integration VM (see `tests/UAT/CrashTests-Sign/README.md`).

## Documentation

| Document | Content |
|---|---|
| [`docs/user-guide.md`](docs/user-guide.md) | Using LCIT Sign (signers, operators, administrators) |
| [`docs/design.md`](docs/design.md) | Design, security model, known limits |
| [`docs/entra-sso-test.md`](docs/entra-sso-test.md) | Setting up Entra ID sign-in |
| [`docs/microsoft-graph-setup.md`](docs/microsoft-graph-setup.md) | Sending mail with Microsoft Graph |
| [`docs/mock-sso-real-accounts.md`](docs/mock-sso-real-accounts.md) | Mock SSO with real accounts |
