# LCIT Sign

Internal electronic signature and acknowledgement service. A user uploads a PDF (or Word / LibreOffice) document,
chooses the signers and their order, places the signature elements, and sends it. Each signer signs while logged in
with their own account. Every signature stores a proof (signer identity, consent, SHA-256 of the document, timestamp)
sealed with an Ed25519 key, plus a certificate and the signed PDF.

The signature is a *simple* electronic signature (eIDAS). Not provided: advanced or qualified signatures, qualified
timestamps, per-user private keys, S3/MinIO storage.

## Stack

Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL · Vite, React · nginx · Docker Compose (Kubernetes manifests in `k8s/`).

## Install

```bash
cp .env.example .env         # set at least LCIT_SIGN_DB_PASSWORD
mkdir -p -m 700 certs        # before the first `up` (otherwise Docker creates it as root)
docker compose up -d --build
```

UI on http://127.0.0.1:4180 and https://127.0.0.1:4443 (self-signed certificate until you install one with
`scripts/certificate-installer.sh`); API under `/api`, health at `/api/health`. Backup and restore: `scripts/backup.sh`,
`scripts/restore.sh`.

A fresh installation contains only the local account `admin` (initial password `SecretPassword`, to be changed at first
sign-in). There is no SSO, no directory and no sample data. Configure them under *Administration → Identités & accès*:

- **Sign-in:** one active SSO provider (Microsoft Entra ID, Google or a generic OIDC provider) plus the local sign-in.
  `LCIT_SIGN_OIDC_*` variables, when set, take precedence over the UI.
- **Directory** (users and groups): one active source, Entra ID, Google Workspace or LDAP / Active Directory.
- **Mail:** SMTP, Microsoft Graph or Gmail.

Credentials entered in the UI are stored encrypted (AES-256-GCM) under `LCIT_SIGN_MASTER_KEY`; nothing secret is in the repository.
With `LCIT_SIGN_ENVIRONMENT=production` the app refuses to start if the session secret or the master key is empty, a
development value or shorter than 32 characters, or if the cookie is not `Secure`.

## Roles

| Role | Scope |
|---|---|
| `SIGNER` | Standard user, granted to every active account: prepares, sends, follows and signs. Signing requires this role **and** an active signature request |
| Campaign preparer | Per-campaign right (not a role) to work on one campaign's content |
| `OPERATOR` | Supervision of all campaigns; no access to document content unless added as preparer of a campaign |
| `ADMIN` | Administration of the platform |

## CrashTest

`./crashtest/start.sh` starts a separate stack (own database and volumes) with a mock SSO and fictional users, groups and
campaigns; `./crashtest/reset.sh` rebuilds it. These exist nowhere else. See [`crashtest/README.md`](crashtest/README.md).

## Development

```bash
pip install -e '.[dev]' && ruff check . && mypy src && pytest     # backend
cd web && npm ci && npm test && npm run build                     # frontend
scripts/e2e.sh                                                    # end to end on a throwaway stack
```

Tests run in Docker on the integration VM (see `tests/UAT/CrashTests-Sign/README.md`).

## Documentation

- [`docs/user-guide.md`](docs/user-guide.md): using LCIT Sign
- [`docs/design.md`](docs/design.md): design, security model, known limits
- [`docs/entra-sso-test.md`](docs/entra-sso-test.md): Entra ID sign-in
- [`docs/microsoft-graph-setup.md`](docs/microsoft-graph-setup.md): mail through Microsoft Graph
- [`docs/mock-sso-real-accounts.md`](docs/mock-sso-real-accounts.md): mock SSO with real accounts
