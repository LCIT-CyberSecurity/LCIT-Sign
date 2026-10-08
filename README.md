# LCIT Sign

LCIT Sign is a self-hosted electronic signature and acknowledgement service for internal documents: IT charters,
security policies, house rules, amendments, procedures. A document is uploaded, the signers and their order are
chosen, the signature elements are placed on the page, and the request is sent. Each person signs from their own
browser with their company account, and every signature comes with a proof that can be verified at any time.

## Features

- **Company sign-in.** One active SSO provider (Microsoft Entra ID, Google or any OpenID Connect provider) plus a local
  sign-in. Users and groups are read from one directory: Entra ID, Google Workspace or LDAP / Active Directory.
- **Verifiable signatures.** Each signature seals the signer's identity, consent, the SHA-256 of the document and the
  date with an Ed25519 key. The signed PDF, the proof and a certificate can be downloaded and re-verified. No private
  key is stored: signing keys are derived from the master key.
- **Document preparation in the browser.** Place the signature, date, name, e-mail, company logo or fill-in fields on
  the pages. Word and LibreOffice files are converted to PDF in an isolated container with no network access.
- **Campaigns.** Several signers in a fixed order, a copy per recipient for a whole team (by directory group),
  external people invited by e-mail, deferred start, reminders, periodic renewal, one-click signing of several
  documents, signed campaign report, ZIP export.
- **Roles.** Every active user is a `SIGNER` and can prepare, send, follow and sign their own requests. Campaign
  preparers share one campaign; `OPERATOR` supervises all campaigns without reading their content; `ADMIN` runs the
  platform.
- **Operations.** E-mail through SMTP, Microsoft Graph or Gmail; credentials entered in the UI and stored encrypted
  (AES-256-GCM); chained audit log; diagnostics page; HTTPS with a certificate installer; backup and restore;
  Kubernetes manifests.

The signature is a *simple* electronic signature (eIDAS) backed by a technical proof. Advanced or qualified signatures
and qualified timestamps are out of scope.

## Prerequisites

- A Linux host with **Docker** and the **Docker Compose** plugin. The whole application (API, web server, PostgreSQL,
  document converter) runs as containers; nothing else has to be installed.
- Read the **[user guide](docs/user-guide.md)** first: it explains the roles, the signature workflow and the
  administration pages used after the first start.
- For production: a public URL with TLS, and two random secrets of at least 32 characters (session secret and master
  key).

## Deploy

```bash
git clone https://github.com/LCIT-CyberSecurity/LCIT-Sign.git && cd LCIT-Sign
cp .env.example .env            # set LCIT_SIGN_DB_PASSWORD, and for production the values below
mkdir -p -m 700 certs           # before the first start (otherwise Docker creates it as root)
docker compose up -d --build    # builds and starts the stack, applies the database migrations
docker compose ps               # all services should become "healthy"
```

The UI is then on `https://<host>:4443` (self-signed certificate until you install yours with
`scripts/certificate-installer.sh`) and on `http://127.0.0.1:4180` for local use. Health check: `/api/health`.

For production, set in `.env`:

```bash
LCIT_SIGN_ENVIRONMENT=production
LCIT_SIGN_PUBLIC_BASE_URL=https://sign.example.org
LCIT_SIGN_COOKIE_SECURE=true
LCIT_SIGN_SESSION_SECRET=$(openssl rand -hex 32)
LCIT_SIGN_MASTER_KEY=$(openssl rand -hex 32)     # keep it safe: it protects stored credentials and signing keys
```

In production the app refuses to start if either secret is empty, a development value or shorter than 32 characters, or
if the cookie is not `Secure`. Secrets can also be given as files (`LCIT_SIGN_*_FILE`).

**First access.** A fresh installation contains only the local account `admin`, with the initial password
`SecretPassword`, which must be changed at first sign-in. There is no SSO, no directory and no sample data. Sign in
locally, then configure *Administration → Identities & access* (SSO, directory) and *Email*.

Update: `git pull && docker compose up -d --build`. Backup and restore: `scripts/backup.sh`, `scripts/restore.sh`.

## Demo and test environment

```bash
./crashtest/start.sh     # separate stack (own database and volumes): mock SSO, fictional users, groups and campaigns
./crashtest/reset.sh     # destroys only that stack and starts again
```

CrashTest is the only place where the mock SSO and the fictional data exist. See [`crashtest/README.md`](crashtest/README.md).

## Development

```bash
pip install -e '.[dev]' && ruff check . && mypy src && pytest     # backend
cd web && npm ci && npm test && npm run build                     # frontend
scripts/e2e.sh                                                    # end to end on a throwaway stack
```

Stack: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Vite, React, nginx.

## Documentation

- [`docs/user-guide.md`](docs/user-guide.md): using LCIT Sign
- [`docs/design.md`](docs/design.md): design, security model, known limits
- [`docs/entra-sso-test.md`](docs/entra-sso-test.md): Entra ID sign-in
- [`docs/microsoft-graph-setup.md`](docs/microsoft-graph-setup.md): mail through Microsoft Graph
- [`docs/mock-sso-real-accounts.md`](docs/mock-sso-real-accounts.md): mock SSO with real accounts
