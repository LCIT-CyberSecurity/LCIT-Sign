# LCIT Sign — Design

LCIT Sign is an internal application for collecting **signatures and
acknowledgements of reading** on documents (policies, charters, notices).
Employees sign in through SSO, read a PDF, tick a consent box, and get a
signed PDF plus a verifiable proof. Operators run campaigns and get a signed
report (procès-verbal) at the end.

This document explains how the system is built and why. It describes what is
in the repository today.

## 1. Goals and non-goals

**Goals**

- SSO only (OpenID Connect). No local accounts, no passwords.
- Documents are versioned and **immutable once published**.
- A visual, DocuSign-like signature backed by a **technical proof**
  (SHA-256 + Ed25519) that anyone with the public key can re-verify.
- A tamper-evident audit trail.
- Self-contained deployment: PostgreSQL and a filesystem volume. Nothing else.

**Non-goals (out of the MVP)**

eIDAS qualified signatures, qualified timestamping, per-user PKI or private
keys, biometric signatures, a PDF field editor, S3/MinIO storage, local
password accounts.

The signature is therefore an *attestation by an authenticated employee*,
sealed by the platform's key. It is not a legally qualified signature, and it
is not presented as one.

## 2. Architecture

```
 Browser ──HTTPS──▶ nginx (webui) ──/api──▶ FastAPI (api) ──▶ PostgreSQL
                      │  static React SPA        │
                      │  security headers        ├──▶ filesystem volume (PDFs, evidence, reports)
                      │  CSP, no-sniff           ├──▶ OIDC provider (login)
                                                 ├──▶ SMTP server (notifications)
                                                 └──▶ Entra ID / Google (directory sync, optional)
```

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 16 (SQLite in unit tests) |
| Frontend | Vite, React, TypeScript, Lucide icons, plain CSS |
| Proxy | nginx: TLS termination point, security headers, serves the SPA, proxies `/api` (BFF) |
| Deployment | Docker Compose for dev/integration; Kubernetes-compatible |
| Dev SSO | `mock_oidc/`, a small OIDC provider (compose profile `dev-sso`) |

The browser only ever talks to nginx, on a single origin. The API is never
exposed directly, so cookies stay same-site and CORS is not needed.

### Repository layout

```
src/lcit_sign/
  app.py            app factory, router wiring, notification worker loop
  config.py         Settings (env vars, prefix LCIT_SIGN_)
  deps.py           DB session, current user, role guards
  auth/             OIDC flow, cookies, session tokens
  api/              HTTP routes (one module per area)
  models/           SQLAlchemy models
  services/         business logic (crypto, audit, evidence, PDFs, mail, sync)
migrations/         Alembic revisions 0001 … 0008
web/                React SPA + nginx config
mock_oidc/          dev-only OIDC provider
docker/, docker-compose.yml
tests/              pytest suite
docs/               this folder
```

## 3. Roles and access control

Three roles, stored in `user_roles`. A user can hold several.

| Role | Can do |
|---|---|
| `SIGNER` | See their own assignments, read and sign documents, download their own proofs |
| `OPERATOR` | Upload and publish documents, create/launch/remind/close campaigns, read the directory (to pick groups), generate reports |
| `ADMIN` | Everything administrative: roles, audit, signing keys, SMTP, directory connectors and sync |

Routes are guarded by `require_roles(...)` in `deps.py`. Roles are granted by
an ADMIN. `LCIT_SIGN_BOOTSTRAP_ADMIN` gives ADMIN to one email on login so
the first administrator can exist; it should be unset once a real admin has
taken over.

## 4. Authentication and sessions

- **Protocol:** OIDC Authorization Code with PKCE (Authlib). The provider is
  generic; configure `LCIT_SIGN_OIDC_ISSUER`, `..._CLIENT_ID`,
  `..._CLIENT_SECRET`. If unset, auth endpoints return a clear configuration
  error instead of failing open.
- **Login flow:** `/api/auth/login` sets a short-lived signed cookie holding
  state, nonce and the PKCE verifier (HMAC-SHA256 with
  `LCIT_SIGN_SESSION_SECRET`), then redirects to the provider.
  `/api/auth/callback` validates everything and creates the session.
- **Identity key:** a user is identified by `(issuer, subject)`, never by
  email alone. Email and name are refreshed from the provider.
- **Sessions:** the cookie carries a random token; only its **SHA-256 hash**
  is stored in `sessions`. A stolen database cannot be replayed as cookies.
  Sessions expire on idle (default 60 min) and absolutely (default 12 h).
- **Cookie flags:** `Secure` is on by default, disabled only for plain-http
  local development (`LCIT_SIGN_COOKIE_SECURE=false`).

## 5. Documents

- A `Document` is the logical object ("IT charter"). Content lives in
  `DocumentVersion` rows: `DRAFT` → `PUBLISHED` → `SUPERSEDED` (when a newer version replaces it) or `ARCHIVED`.
- Uploads must be PDFs: magic-bytes check, size limit
  (`LCIT_SIGN_MAX_UPLOAD_SIZE_MB`, default 25), and **rejection of PDFs with
  active content** (`/JavaScript`, `/JS`, `/OpenAction`, `/AA`).
- Each version's SHA-256 is computed at upload and stored.
- Files are saved on disk under the version's own UUID. The uploaded file name
  is display metadata only and is never used to build a path, which removes
  path-traversal risk.
- Once published, a version cannot change. A correction is a new version,
  which requires new signatures.

### Storage

`StorageService` writes to `LCIT_SIGN_STORAGE_ROOT` (a persistent volume,
default `/var/lib/lcit-sign`), organised in buckets:

| Bucket | Content |
|---|---|
| `documents` | original PDFs |
| `signed` | PDFs with the attestation page appended |
| `evidence` | `evidence.json` per signature |
| `certificates` | human-readable certificate PDF per signature |
| `reports` | campaign reports (PDF, CSV) |

Binary files never go into PostgreSQL. Back up the database **and** this
volume together.

## 6. Signature and proof

This is the core of the product.

### What happens when a signer signs

1. The signer must hold `SIGNER`, the version must be `PUBLISHED`, and the
   consent box must be ticked.
2. The platform appends **one attestation page** to the original PDF: a
   sober metadata block plus a cursive rendering of the signer's
   authenticated display name. Original pages are copied unchanged.
3. It builds the **evidence record**, a fixed set of fields (see
   `services/evidence.py`): signature, campaign, document and version ids;
   version label; SHA-256 of the original; the user's internal id, issuer,
   subject, email and display name **as they were at that moment**; consent
   text and version; UTC timestamp; SHA-256 of the signed file; application
   version; signing key id.
4. The record is serialised as canonical JSON (sorted keys, no spaces) and
   hashed with SHA-256: the **evidence hash**.
5. The evidence hash is signed with **Ed25519** using the active platform
   signing key.
6. Everything is stored: a `signatures` row, the signed PDF, `evidence.json`
   and the certificate PDF. The assignment becomes `SIGNED`, an audit event
   is written, and a confirmation email is queued.

One user can sign a given version only once (database unique constraint).

### Why the snapshot

The signature row is immutable. If the user later changes name or email, or
the consent text is edited, the stored signature does not change. That is why
identity and consent are copied into it rather than referenced.

### Verification

`GET /api/signatures/{id}/verify` recomputes the evidence hash from the stored
row and checks the Ed25519 signature against the stored public key. It also
checks the original and signed files against their recorded hashes. Because the evidence
field set is built by one function used both when signing and when verifying,
the two cannot drift apart.

### Signing keys

- There is **no private key in the database or on disk.** Each key's Ed25519
  seed is derived at runtime by HKDF from `LCIT_SIGN_MASTER_KEY` and the
  key's `key_id`. The database holds only the key id and the **public** key.
- **Rotation** (ADMIN) creates a new `key_id`. Old public keys are kept
  forever, so old signatures stay verifiable. A key can be retired or revoked.
- The key is platform-wide, not per user. This is the "no user PKI" decision.

## 7. Campaigns

A campaign asks a set of people to sign one or more document versions.

**Lifecycle:** `DRAFT` → `ACTIVE` (launch) → `CLOSED` or `CANCELLED`
(→ `ARCHIVED`).

**Targeting** combines freely:

- one or more directory **groups**,
- **extra users** added by hand,
- or **all active users**.

The population is the de-duplicated union. `target_mode` is a label computed
from what was used. A **preview** endpoint shows the resolved population
before launch.

**Assignments** (`signature_assignments`): one per person and document,
status `PENDING` → `VIEWED` → `SIGNED` (or `EXPIRED` / `CANCELLED`). Operators
can **remind** pending people; this queues emails.

## 8. Reports (procès-verbal)

An operator generates a report for a campaign:

- a **PDF** (the canonical artifact) and a **CSV** export,
- recorded in `reports` with both SHA-256 hashes,
- the PDF hash is **signed with Ed25519**, like a signature.

`GET /api/reports/{id}/verify` re-checks the hash and signature. The CSV is a
convenience copy; only its hash is recorded.

## 9. Audit trail

Every important action calls `append_audit_event`, including logins, role
changes, uploads, publications, launches, signatures, key rotations, SMTP
changes, connector changes and syncs.

- Events are **hash-chained**: each event's hash covers its canonical content
  plus the previous event's hash. Changing or deleting a past row breaks every
  hash after it.
- A singleton `audit_chain_state` row is locked with `SELECT ... FOR UPDATE`
  on each append so concurrent writers cannot fork the chain.
- Events store an **identity snapshot** of the actor, the source IP (where the request provides it) and a request id.
- `GET /api/admin/audit/integrity` walks the chain and reports whether it is
  intact, and where it breaks if not.

The chain proves tampering happened. It does not prevent it by itself: a
database owner could rewrite the whole chain. Keep an off-site copy of the
latest hash if that matters to you.

## 10. Directory and groups

The directory feeds the groups used for targeting. It is **read-only**
towards the upstream system.

### Connectors

| Source | How it works |
|---|---|
| `local` | Built-in fictional organisation (24 users, 6 groups) for tests and demos |
| `entra` | Microsoft Graph, app-only OAuth2 client credentials. Needs `User.Read.All`, `Group.Read.All`, `GroupMember.Read.All` application permissions with admin consent |
| `google` | Admin SDK Directory API, service account with domain-wide delegation, impersonating an admin. Read-only scopes only |

All connectors implement one small interface: `fetch()` returns a snapshot
(users, groups, memberships). One engine, `sync_directory`, applies any
snapshot.

### Sync rules

- **Idempotent.** Run it twice, get the same state.
- **Never deletes users.** A user missing upstream is **deactivated**, so
  signature history stays intact. Same for groups.
- **One person, one row.** A directory user whose email matches an existing
  SSO user adopts that row, and the other way round. There is never a
  duplicate.
- **Per-source membership.** A sync only reconciles memberships of its own
  groups.
- **Failure is safe.** If the upstream call fails, the run is recorded as
  `FAILED` with the error and **nothing else is touched**. A partial answer
  can never deactivate people.
- Every run is stored in `directory_sync_runs` (counts added/updated/
  deactivated) and audited.

### Connector credentials

Entra and Google credentials are **not in the environment, `.env` or the
compose file.** An ADMIN enters them in the UI
(`PUT /api/admin/directory/sources/{source}/config`).

| Source | Stored in clear (fields) | Stored encrypted (secret) |
|---|---|---|
| `entra` | `tenant_id`, `client_id` | client secret |
| `google` | `admin_email` | service account JSON |

The secret is encrypted with **AES-256-GCM**. The key is derived with HKDF
from `LCIT_SIGN_MASTER_KEY`, with a purpose tag that differs from the signing
key derivation. Ciphertext goes to `directory_connector_configs`. The API never
returns the secret, and sending an update without a secret keeps the stored
one.

**Decryption** happens only in the backend process, in memory, when a sync
starts (`build_remote_connector` calls `decrypt_secret`). The plaintext is
used for the outbound call and is not written anywhere. The SMTP password
follows the same scheme.

## 11. Notifications

Emails are queued, never sent inline.

- `notifications` is a PostgreSQL-backed queue. A row is created in the **same
  transaction** as the business event, so an SMTP outage never rolls back a
  signature.
- A background worker in the API process (interval
  `LCIT_SIGN_NOTIFICATION_WORKER_INTERVAL_SECONDS`, default 30 s) sends due
  items. No Redis or Celery.
- Retries use exponential backoff capped at 60 minutes. Each message is
  committed on its own, so one failure does not undo another's success.
- Types: document to sign, reminder, signature confirmation, test email.
- SMTP settings live in `mail_connectors` (single row). The password is
  encrypted like the directory secrets. ADMIN can test the connection and send
  a test mail.

## 12. Security model

| Concern | Measure |
|---|---|
| Authentication | SSO only, PKCE, no password storage |
| Session theft | Only token hashes in DB, idle and absolute timeouts, `Secure` cookies |
| Secrets in the database | AES-256-GCM under the master key |
| Signing keys | Derived at runtime, private material never stored |
| Malicious PDFs | Magic-bytes check, size cap, active-content rejection |
| Path traversal | Storage paths built from UUIDs only |
| Tampering | Immutable published versions, immutable signatures, hash-chained audit, signed evidence and reports |
| Web hardening | nginx sets CSP (`default-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `nosniff`, referrer and permissions policies |
| Authorisation | Role checks on every route |

### `LCIT_SIGN_MASTER_KEY` is the crown jewel

It is the only secret that must live in the environment. It protects the
signing keys and every encrypted credential.

- Someone with the **database only** gets ciphertext and public keys: no usable
  secrets.
- Someone with the **database and the master key** can decrypt connector and
  SMTP credentials, and can derive signing keys.
- **Changing or losing it** makes stored credentials unreadable (admins must
  re-enter them) and breaks signing with existing keys. Back it up separately
  from database backups.
- Inject it from a secrets manager or a Kubernetes Secret in production. Never
  commit it. `.env` is git-ignored; only `.env.example` with placeholders is
  versioned.

## 13. Data model

```
users ─< user_roles
users ─< sessions
users >─< groups            (group_memberships)
documents ─< document_versions
campaigns ─< campaign_documents >─ document_versions
campaigns ─< campaign_target_users / campaign_target_groups
campaigns ─< signature_assignments ─ users
signatures                  (user, version, campaign; evidence snapshot)
reports                     (campaign)
signing_keys
audit_events, audit_chain_state
mail_connectors, notifications
directory_connector_configs, directory_sync_runs
```

Schema changes go through Alembic (`migrations/versions/0001`–`0008`). The
container entrypoint runs migrations at start.

## 14. API overview

All routes sit under `/api`.

| Area | Routes (summary) |
|---|---|
| Health/config | `GET /health`, `/ready`, `/config` |
| Auth | `GET /auth/login`, `/auth/callback`, `POST /auth/logout`, `GET /auth/me` |
| Documents | `POST /documents`, `POST /documents/{id}/versions`, `POST /documents/versions/{id}/publish`, `GET /documents`, `GET /documents/{id}`, `GET /documents/versions/{id}/content` |
| Signing | `POST /documents/versions/{id}/sign`, `GET /signatures/me`, `/signatures/{id}`, `/signed-pdf`, `/certificate`, `/evidence`, `/verify` |
| Campaigns | `POST /campaigns`, `/{id}/documents`, `/{id}/targets/preview`, `/{id}/launch`, `/{id}/remind`, `/{id}/close`, `/{id}/cancel`, `GET /campaigns`, `/{id}`, `/{id}/assignments` |
| Reports | `POST /campaigns/{id}/reports`, `GET /campaigns/{id}/reports`, `GET /reports/{id}/pdf`, `/csv`, `/verify` |
| Admin | users and roles, audit and audit integrity, signing keys and rotation, mail connector (get, put, test, send-test), notifications |
| Directory (admin) | `GET /admin/directory/sources`, `PUT`/`DELETE /admin/directory/sources/{source}/config`, `POST /admin/directory/sync?source=`, `GET /sync-runs`, `/groups`, `/groups/{id}/members` (groups and members are also readable by OPERATOR) |

## 15. Frontend

A single-page React app, role-aware:

- **Signer:** list of assignments, a detail page with PDF viewer, consent and
  sign button, and access to their proofs.
- **Operator:** documents and versions, campaigns (create, target, launch,
  remind, close), reports.
- **Admin:** users and roles, audit log and integrity check, signing keys,
  SMTP, directory (source selector, sync history, connector credential forms).

Secret fields are write-only: the forms send them and clear them, and show
only whether a secret is set.

## 16. Configuration reference

All variables use the prefix `LCIT_SIGN_`.

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `development`, `test` or `production` |
| `DATABASE_URL` | PostgreSQL connection (compose builds it from `DB_PASSWORD`) |
| `SESSION_SECRET` | Signs the login-flow cookie |
| `COOKIE_SECURE` | `true` everywhere except plain-http dev |
| `SESSION_IDLE_TIMEOUT_MINUTES`, `SESSION_ABSOLUTE_TIMEOUT_HOURS` | Session lifetimes |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | SSO provider |
| `PUBLIC_BASE_URL` | Builds the OIDC redirect URI |
| `BOOTSTRAP_ADMIN` | Email granted ADMIN on login (temporary) |
| `MASTER_KEY` | Signing-key derivation and credential encryption |
| `STORAGE_ROOT`, `MAX_UPLOAD_SIZE_MB` | File storage |
| `CONSENT_TEXT`, `CONSENT_VERSION` | Consent wording, recorded in each signature |
| `NOTIFICATION_WORKER_ENABLED`, `NOTIFICATION_WORKER_INTERVAL_SECONDS` | Mail worker |

Directory connector and SMTP credentials are intentionally **not** variables;
they are entered in the admin UI and stored encrypted.

## 17. Running and testing

```bash
cp .env.example .env            # edit at least the DB password and master key
docker compose up -d --build    # UI on http://127.0.0.1:4180
docker compose --profile dev-sso up -d   # adds the mock OIDC provider

pip install -e '.[dev]'
ruff check . && mypy src && pytest --cov
cd web && npm install && npm test && npm run build
```

Tests run against SQLite and a real local mock OIDC server. Directory
connectors are tested with mocked HTTP transports: they have not been run
against a real Entra or Google tenant.

## 18. Known limits and open points

- **Not eIDAS.** The proof is internal and verifiable with the platform's
  public keys. It is not a qualified signature or timestamp.
- **One platform key, one master key.** Compromise of the master key
  compromises signing and stored credentials. An external vault or KMS would
  be the next step.
- **No `*_FILE` secret loading** yet for the master key.
- **Remote connectors untested on real tenants.** Validate against a test
  tenant before relying on them.
- **Audit chain is tamper-evident, not tamper-proof.**
- **Migration 0008** (and 0006) must be applied on the real PostgreSQL; tests
  use SQLite.
