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
- Read the **[user guide](docs/user/user-guide.md)** first: it explains the roles, the signature workflow and the
  administration pages used after the first start.
- For production: a public URL with TLS, and two random secrets of at least 32 characters (session secret and master
  key).

## Deploy

```bash
git clone https://github.com/LCIT-CyberSecurity/LCIT-Sign.git && cd LCIT-Sign
cp .env.example .env            # then edit it, see below
mkdir -p -m 700 certs           # before the first start (otherwise Docker creates it as root)
docker compose up -d --build    # builds the images, starts the stack, applies the database migrations
docker compose ps               # all services should become "healthy"
```

The stack has four containers: `postgres` (database), `api` (FastAPI backend), `webui` (nginx: HTTPS, the web
interface and the `/api` proxy) and `converter` (isolated Word / LibreOffice to PDF conversion). Data lives in two
Docker volumes (database, stored documents and signed files). The UI is on `https://<host>:4443` (self-signed
certificate until you install yours with `ops/admin/certificate-installer.sh`) and on `http://127.0.0.1:4180`; health
check at `/api/health`.

### The `.env` file

`.env` holds the settings of your installation and **must never be committed**. It is read by Docker Compose; unset
variables fall back to development defaults.

| Variable | Meaning |
|---|---|
| `LCIT_SIGN_DB_PASSWORD` | Password of the PostgreSQL user. Set your own |
| `LCIT_SIGN_ENVIRONMENT` | `development` (default) or `production`. Production enforces the secret checks below |
| `LCIT_SIGN_PUBLIC_BASE_URL` | The URL users reach LCIT Sign at (e.g. `https://sign.example.org`); used for sign-in redirects and e-mail links |
| `LCIT_SIGN_COOKIE_SECURE` | `true` behind HTTPS (required in production), `false` only for plain-HTTP local tests |
| `LCIT_SIGN_SESSION_SECRET` | Random secret that signs the short-lived sign-in cookie |
| `LCIT_SIGN_MASTER_KEY` | Random secret from which the signing keys are derived and that encrypts the credentials saved in the UI. Back it up and **never change it** afterwards: signing would be refused and stored credentials unreadable |
| `LCIT_SIGN_FQDN`, `LCIT_SIGN_HTTPS_PORT`, `LCIT_SIGN_CERT_DIR` | Host name for the fallback certificate, HTTPS port (default 4443), folder of `tls.crt` / `tls.key` (default `./certs`) |
| `LCIT_SIGN_OIDC_ISSUER`, `_CLIENT_ID`, `_CLIENT_SECRET` | Optional: define the SSO from the environment (all three). Leave empty to configure it later in the UI |
| `LCIT_SIGN_BOOTSTRAP_ADMIN` | Optional e-mail given the ADMIN role at its SSO sign-in. Leave empty on a normal installation |
| `LCIT_SIGN_LOG_LEVEL` | Log level (default `INFO`) |
| `LCIT_SIGN_*_FILE` | For `MASTER_KEY`, `SESSION_SECRET` and `OIDC_CLIENT_SECRET`: path of a file (Docker / Kubernetes secret) holding the value instead of the variable |

Mail, the directory and the SSO providers are **not** set in `.env`: they are entered in the UI and stored encrypted.

### Production

```bash
LCIT_SIGN_ENVIRONMENT=production
LCIT_SIGN_PUBLIC_BASE_URL=https://sign.example.org
LCIT_SIGN_COOKIE_SECURE=true
LCIT_SIGN_SESSION_SECRET=$(openssl rand -hex 32)
LCIT_SIGN_MASTER_KEY=$(openssl rand -hex 32)
```

(write the generated values into `.env` rather than relying on the shell). In production the app refuses to start if
either secret is empty, a development value or shorter than 32 characters, or if the cookie is not `Secure`.

### First access

A fresh installation contains only the local account `admin` with the initial password `SecretPassword`, which must be
changed at first sign-in. There is no SSO, no directory and no sample data. Sign in locally, then configure
*Administration → Identities & access* (SSO, directory) and *Email*; the [user guide](docs/user/user-guide.md) walks through it.

### Update, backup

Update: `git pull && docker compose up -d --build` (migrations run at start). Backup and restore:
`ops/admin/backup.sh`, `ops/admin/restore.sh`.

## Demo and test environment

```bash
./tests/crashtest/start.sh     # separate stack (own database and volumes): mock SSO, fictional users, groups and campaigns
./tests/crashtest/reset.sh     # destroys only that stack and starts again
```

CrashTest is the only place where the mock SSO and the fictional data exist. See [`crashtest/README.md`](tests/crashtest/README.md).

## Development

```bash
pip install -e '.[dev]' && ruff check . && mypy src && pytest     # backend
cd web && npm ci && npm test && npm run build                     # frontend
ops/dev/e2e.sh                                                    # end to end on a throwaway stack
```

Stack: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Vite, React, nginx.

## Documentation

- [`docs/user/user-guide.md`](docs/user/user-guide.md): using LCIT Sign
- [`docs/architecture/design.md`](docs/architecture/design.md): design, security model, known limits
- [`docs/integrations/entra-sso-test.md`](docs/integrations/entra-sso-test.md): Entra ID sign-in
- [`docs/integrations/microsoft-graph-setup.md`](docs/integrations/microsoft-graph-setup.md): mail through Microsoft Graph
- [`docs/integrations/mock-sso-real-accounts.md`](docs/integrations/mock-sso-real-accounts.md): mock SSO with real accounts
