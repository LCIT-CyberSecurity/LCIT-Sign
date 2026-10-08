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

- SSO (OpenID Connect) for people; a built-in local administrator (and optional local accounts) as the way in
  when no SSO is set up. A fresh installation has no SSO, no directory and no fictional person.
- Documents are versioned and **immutable once published**.
- A visual signature backed by a **technical proof**
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
| Mock SSO | `mock_oidc/`, a small OIDC provider, **only in the CrashTest stack** (compose profile `crashtest`) |

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

Three roles, stored in `user_roles`. A user can hold several. **Everyone active has `SIGNER`**: it is
given when the account is created (first SSO sign-in, directory import, local account, external
signer) and by migration 0024 to every existing active user. Afterwards it is administered: a
directory sync never gives it back to someone it was taken from. The former global `PREPARER` role
no longer exists (migration 0024 turned it into `SIGNER` and removed it); do not confuse it with
**CampaignPreparer**, a right on ONE campaign (below), which stays.

| Role | Can do |
|---|---|
| `SIGNER` | The standard user. Upload and prepare documents, place the elements, create a campaign, choose the signers (themselves included), send, follow, remind, get the results — **only for the campaigns they own or prepare** — and **sign** what is asked of them. Signing needs an active account, `SIGNER` **and** an assignment; the role is checked by the API (`403 Insufficient role` without it, assignment or not) |
| `OPERATOR` | **Business administrator.** Sees every campaign, its status, owner, signers and progress; reassigns the owner and the preparers; helps unblock a campaign (remind, cancel, close, archive). Does **not** read the confidential content (documents, signed PDFs, certificates, proofs, reports, exports) unless made a preparer of that campaign |
| `ADMIN` | Technical administration (users and roles, audit, signing keys, mail, identities and access) and full access to everything |

Signing in is not a role: any successful authentication enters the application (an account an
administrator disabled stays refused). The roles decide what one can do, not whether one can open a
session.

### Identities and access

Two different questions, one administration page (*Identities & access*), two backend models:

* **Sign-in** (*Connexion*) (`login_providers`): how people authenticate. One external SSO provider is in use
  (`active`), plus the local form. If the `LCIT_SIGN_OIDC_*` variables are set they ARE the SSO
  (the page says so); otherwise it is the active provider (Microsoft Entra ID or Google). On CrashTest
  the variables point at the mock SSO, which stays the only entry point; Entra is reached through it.
* **Directory** (*Annuaire*) (`directory_connector_configs`): where users and groups come from. One directory is
  active (`active`; the bundled demonstration one when none): only it is synced, by hand or on
  schedule. Saving a connector makes it active; others are switched on explicitly.

Configuring one never changes the other.

### Who sees what in a campaign

A campaign has an **owner** (`owner_id`, who runs it now) and keeps its **creator** (`created_by`,
for the record, never rewritten). Other **preparers** are rows of `campaign_preparers`; the owner
needs none. Three levels, no finer rights (`services/access.py`, `api/campaign_access.py`):

| Level | What | Who |
|---|---|---|
| view | existence, status, owner, preparers, signers, progress | ADMIN, OPERATOR, owner, preparers |
| operate | remind, cancel, close, archive, recipients, **hand over** (owner, preparers) | ADMIN, OPERATOR, owner, preparers |
| content | documents and elements, building and sending, signed PDFs, certificates, proofs, reports, exports | ADMIN, owner, preparers |

A preparer of another campaign gets a 404 (it does not exist for them); an operator who sees it but
not its content gets a 403. An operator who must read the content is added as a preparer of that
campaign (`CAMPAIGN_PREPARER_ADDED` in the audit log). Handing a campaign over keeps the previous
owner as a preparer until someone removes them (`CAMPAIGN_OWNER_CHANGED`). Owner and preparers must
hold `SIGNER`, `OPERATOR` or `ADMIN`. Library documents follow the same idea (`can_read_document`):
the uploader, a preparer of a campaign using it, or an administrator read the file; an operator sees
that it exists. Campaigns from before this model keep their creator as owner (migration 0020).

**Signing needs both.** An active account, the `SIGNER` role **and** a valid
`SignatureAssignment` (`PENDING` or `VIEWED`): `SIGNER` alone is not enough (409 « Aucune demande de
signature active »), and an assignment without `SIGNER` gets a 403. There is no signature without a
request: someone who wants to sign their own document creates a campaign and designates themselves.

Routes are guarded by `require_roles(...)` in `deps.py`. Roles are granted by
an ADMIN. `LCIT_SIGN_BOOTSTRAP_ADMIN` gives ADMIN to one email on login so
the first administrator can exist; it should be unset once a real admin has
taken over.

## 4. Authentication and sessions

- **Protocol:** OIDC Authorization Code with PKCE (Authlib). The provider is
  generic; configure `LCIT_SIGN_OIDC_ISSUER`, `..._CLIENT_ID`,
  `..._CLIENT_SECRET`. If unset, there is no SSO (only the local sign-in) and the auth
  endpoints return a clear configuration error instead of failing open. `GET /api/auth/options`
  tells the sign-in page `{sso, provider, local, crashtest}`: `provider` is `entra`, `google`
  or `generic` (from `LCIT_SIGN_OIDC_PROVIDER`, else read from the issuer's address) and only
  changes the button's logo and wording.
- **Two kinds of account.** *SSO accounts* have an (issuer, subject) and no password here.
  *Local accounts* have a password (scrypt hash, `must_change_password` at first sign-in): the
  built-in administrator and the people an administrator creates with "Compte local". The local
  form (`POST /api/auth/local-login`, identifier = built-in name or e-mail) only matches an
  active account that has a password, so an SSO account never signs in with it. Same throttle,
  audit and sessions. A local account whose person later signs in through the SSO is adopted (by
  e-mail), keeps its roles, and its password keeps working.
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
  (`LCIT_SIGN_MAX_UPLOAD_SIZE_MB`, default 25).
- Each version's SHA-256 is computed at upload and stored.
- Files are saved on disk under the version's own UUID. The uploaded file name
  is display metadata only and is never used to build a path, which removes
  path-traversal risk.
- Once published, a version cannot change. A correction is a new version,
  which requires new signatures.

### Word and LibreOffice as input

A `.docx`, `.odt` or `.doc` can be dropped like a PDF. It is checked before anything else (real
type, a zip that would explode, macros → refused), then converted by an **isolated converter**
(`converter/`, part of every stack: Compose and Kubernetes): its own container, no network, no database, no access to
LCIT Sign's files, read-only, one file at a time under a fixed name, LibreOffice with macros and
external links off. What comes back is checked again like any upload. What is signed is the PDF; the
source is kept (`sources` bucket) with its hash (`document_versions.source_sha256`). Without
`LCIT_SIGN_CONVERTER_URL` (set by default to the converter; empty disables it), only PDFs are
accepted, and the message says so. In Kubernetes (`k8s/converter.yaml`) it is a pod of its own,
read-only, with a network policy that lets only the API in and nothing out.

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

1. The signer must hold `SIGNER` **and** have an outstanding assignment, the version
   must be `PUBLISHED`, and the consent box must be ticked.
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

### One signature answers one campaign

When the same version is asked of the same person by several campaigns, a signature
closes **only the assignment of the campaign it answers**. The signer page names the
campaign (`campaign_id` in the sign request, and `sign-all` always passes its own). A
request with no campaign named while several are outstanding is refused (409) rather
than guessed; signing one never closes the other.

### The master key must match the signing key

Before any proof is signed (or a report), the service derives the public key from
`LCIT_SIGN_MASTER_KEY` and the active key's id and compares it with the public key recorded
in the database. A mismatch (a replaced or mistyped master key) stops the signature with a 503
and a message that names no secret: nothing is created and no assignment is closed. Existing
signatures stay verifiable (they rely on the recorded public keys). Key rotation skips the
check, so an administrator can recover by rotating to a key the current master key derives.

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
status `WAITING` → `PENDING` → `VIEWED` → `SIGNED` (or `EXPIRED` / `CANCELLED`). Operators
can **remind** pending people; this queues emails.

### Several signers: roles, order and mail merge

The editor numbers the signer roles of a document and lets the preparer name
each one ("RSSI", "Collaborateur") — a name says what the role is, never who.
At launch each role is given its people (`campaign_roles`):

- **FIXED** — one named person (the RSSI). They sign once; their stamp is on
  every copy.
- **EACH** — the campaign's list of people (groups, users, everyone), chosen
  and edited before launch. Each person gets their own copy (mail merge).
  When used, EACH is always the **last** role, so what precedes it is common.

Roles sign **in order**. Only the first role of a document is asked at launch;
the next ones are `WAITING` and are notified by email the moment the previous
role has signed (`release_next_role`). A person who tries to sign too early is
told who must sign first. A fixed signer who is also in the list is asked once,
as the fixed role. Cancelling or closing ends the waiting copies too.

A copy carries the stamps of the earlier signers: the new signature's stored
`field_values` are cumulative (each element has its `role`), and its evidence
lists `prior_signatures` (id and evidence hash of each earlier signature).
Verification checks that those signatures still exist with the same hash.
A renewal keeps the same roles and fixed people. Documents with a single
signer launch exactly as before (role 1 = everyone targeted).

### The flow, the follow-up and changes after sending

**Faire signer** is five screens: signers and planning, documents, *Préparer* (the editor itself,
inside the flow, one tab per document), review and send (with a confirmation), and the signed
documents, live. **Suivi** is the reporting: campaigns, the signed documents of one or several
campaigns (PDFs, proof, ZIP export — `GET /api/signed/export.zip`, one folder per campaign plus
CSV indexes), manual reminders by person, cancel / archive / delete.

A campaign already sent can still **get more people or more documents**, and stop asking someone;
what was signed is never touched (`services/campaign_changes.py`). A document added later is
prepared, then sent on its own. Fixed signers are not changed after the launch.

A **start date** in the future schedules the campaign: the request is checked now and kept, and the
worker starts it on its date (status `SCHEDULED`); one that can no longer start goes back to draft
with the reason in the audit trail.

### Signing everything at once

`GET/POST /api/sign-all/{campaign}`: a signer asked for several documents of one campaign (the
RSSI with twenty policies) signs them with one consent. An answer asked on several documents is
typed once (it shares a group key). Everything is checked first — one missing answer refuses the
whole batch — then each document gets its own signature and proof.

### People from outside the company

An operator adds someone by e-mail address (`POST /api/campaigns/_meta/externals`), in the flow
(as a signer, or among the recipients). No account is created anywhere and no password exists:
they sign in with their own account (an Entra guest, a Google account) and are recognised by that
address on first sign-in, like any person added by hand. They are marked `external`, are signers
only, are never touched by a directory sync, and the e-mail they receive says they have nothing to
create. The identity provider must accept them (an Entra guest invitation is a tenant-side step this
application never performs). Not offered by default to unknown accounts: only addresses added this
way, or imported from the directory, match.

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
| `local` | Fictional organisation (24 users, 6 groups): **CrashTest only** (`LCIT_SIGN_CRASHTEST=true`); absent from a normal installation, which has no directory until an administrator configures one (`active_source` is `None`) |
| `entra` | Microsoft Graph, app-only OAuth2 client credentials. Needs `User.Read.All`, `Group.Read.All`, `GroupMember.Read.All` application permissions with admin consent |
| `google` | Admin SDK Directory API, service account with domain-wide delegation, impersonating an admin. Read-only scopes only |
| `ldap` | LDAP / Active Directory with a read-only bind account. `ldaps://`, or `ldap://` only with StartTLS (the bind password never travels in clear); the server certificate is always verified; a disabled account (AD `userAccountControl`, 389 DS `nsAccountLock`) is read as inactive |

Each connector is its own module (`services/directory/entra.py`, `google.py`, `ldap.py`) over a
shared base (`base.py`: the snapshot, nested-group flattening, the description of settings).
A connector describes itself (`SPEC`: its settings, a help text and an example for each, its
checks, how to build it) and `GET /api/admin/directory/sources` serves that description: the
admin page draws each form from it. `registry.py` is the only place that lists them.

All connectors implement one small interface: `fetch()` returns a snapshot
(users, groups, memberships). One engine, `sync_directory`, applies any
snapshot.

### Where the team name comes from

Teams (compta, RH, achats…) are what a campaign is aimed at in one click. Each connector has a
**selector**: the directory's own *groups*, an *attribute* of each person, or *both*.

- Entra: groups, or one user property from a fixed list (`department`, `officeLocation`,
  `companyName`, `jobTitle`, `city`) — a fixed list, so nothing typed ends up in a Graph query.
- Google: groups, the person's organisational unit (OU), or their department.
- LDAP: groups (filter and member attribute), any attribute named by the admin (`department`),
  or the folder (OU) holding the person's entry.

An attribute gives one synthetic team per distinct value (everyone with `department =
Comptabilité` is the team « Comptabilité »), next to the real groups when *both* is chosen.

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

## 11b. Scheduled work: reminders, renewal, directory sync

The notification worker (in the API process, every
`LCIT_SIGN_NOTIFICATION_WORKER_INTERVAL_SECONDS`) also runs three idempotent
jobs, each in its own transaction (`services/scheduler.py`):

- **Reminders** (spec §50). A campaign launched with a policy — first
  reminder after N days, then every M days, at most K times, optionally one
  more N days before the deadline — gets its due reminders queued. Each queued
  reminder advances `last_reminder_at`, so re-running changes nothing. Signed
  people are never reminded; inactive users are skipped.
- **Renewal** (spec §51). A campaign with `renewal_every` + `renewal_unit`
  (`DAYS`/`MONTHS`) opens a follow-up campaign when due: same still-published
  document versions, the still-active people of the old population, the same
  policies. It happens once (`renewed_at`). The old campaign and its
  signatures are untouched.
- **Directory sync** (spec §15). A source with `sync_interval_minutes` runs
  automatically when that interval has elapsed since its last run (a failed run
  counts, so an upstream outage is retried at the normal cadence).

Because renewal asks for the *same version* again, signing is idempotent **per
campaign**, not per version: a signature records its campaign
(`signatures.campaign_id`, also inside the signed evidence), at most one exists
per (user, version, campaign), and earlier signatures are never altered.

## 11c. Mail connectors: SMTP, Microsoft Graph and Google Workspace

Each connector is its own module and implements one `MailSender` interface
(`services/mail.py`); `build_sender` is the only place that picks one. Each module also
describes itself (`SPEC`: its settings, a help text and an example per setting, and its own
checks), and `GET /api/admin/mail-connector/kinds` serves those descriptions: the admin page
draws every form from them, with a help bubble on each field. Adding a connector means adding
one module and listing it in `services/mail_specs.py`.

- **SMTP** (`services/mail_smtp.py`): host/port, TLS or STARTTLS, optional auth. SMTP 5xx
  answers are *permanent* (the notification fails at once); 4xx, timeouts and connection
  errors are retried with backoff.
- **Microsoft Graph** (`services/mail_graph.py`): app-only OAuth2 client
  credentials, sending from **one dedicated mailbox**. The access token lives
  only in process memory and is renewed on demand; the client secret is stored
  encrypted like the SMTP password. The tenant must confine the application to
  that mailbox with Exchange Online Application RBAC. `POST
  /api/admin/mail-connector/test-isolation` is the mandatory negative test: it
  tries to send as another mailbox and reports whether Exchange refused. The
  step-by-step tenant procedure is in `docs/microsoft-graph-setup.md`; nothing
  in this repository modifies a tenant.
- **Google Workspace** (`services/mail_gmail.py`): a service account authorised by
  domain-wide delegation, for the single scope `gmail.send`, acting as the sender mailbox
  (`from_address`) through the Gmail API. The key (JSON) is stored encrypted like the other
  secrets. A refused token says what to fix (delegation not authorised for that scope, mailbox
  unknown). The service-account sign-in is shared with the directory connector
  (`services/google_auth.py`).

## 11d. HTTPS and the certificate installer

nginx serves TLS 1.2/1.3 with HSTS on port 443 (plain HTTP on 80 remains for
development, the container healthcheck and integration tests). It reads
`tls.crt`/`tls.key` from a **read-only** mount and, if none is mounted,
generates a self-signed certificate at container start (inside the container,
never in an image layer).

`scripts/certificate-installer.sh` manages that certificate (menu or
`--test-command`): it validates the PEM files, the key/certificate match, the
validity window, the SAN and FQDN coverage (standard single-label wildcard
rules), warns about a missing intermediate, keeps a single restricted rollback
copy, writes atomically with strict permissions (dir 700, key 600, cert 644),
validates `docker compose config`, recreates the proxy, then compares the
SHA-256 fingerprint **actually presented over TLS** with the expected one,
rolling back automatically on any failure. It never prints or logs key
material. On Kubernetes TLS ends at the Ingress instead (`k8s/README.md`).

## 11e. Backup and restore

`scripts/backup.sh` writes a PostgreSQL dump and a tar of the storage volume
with checksums. **The master key is deliberately not included**; keep it
elsewhere. Existing signatures stay verifiable without it (they need only the
public keys in the database); signing again and reading stored credentials need
it. `scripts/restore.sh` replaces the data of a stack and must be confirmed with
`--yes`. `python -m lcit_sign.cli verify-all` re-verifies every signature,
report and the audit chain from the database and the volume.
`tests/UAT/CrashTests-Sign/restore-test.sh` restores a backup into a throwaway
PostgreSQL and volume and requires all signatures to verify (and a deliberately
corrupted file to be detected).

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
| CSRF | State-changing `/api` requests must come from the same origin (`Origin`/`Sec-Fetch-Site` check) on top of `SameSite` cookies |
| Abuse | Per-IP sliding-window rate limits (login, sync, connector tests, signing); the real peer address is the last `X-Forwarded-For` entry |
| SSRF | Admin-supplied SMTP targets are resolved and refused if link-local/metadata/unspecified/multicast or on non-mail service ports; connectivity tests have timeouts |
| Errors | Unhandled errors return an opaque message with a request id; the trace stays in the server log |
| Log hygiene | Sensitive keys are redacted; HTTP client URL logging is silenced; tests assert known secrets never reach logs or the audit trail |

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
- In production, mount it from a secrets manager or a Kubernetes Secret and point `LCIT_SIGN_MASTER_KEY_FILE` at the file. Never
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
directory_connector_configs (+ sync schedule), directory_sync_runs
```

Schema changes go through Alembic (`migrations/versions/0001`–`0011`). The
container entrypoint runs migrations at start.

## 14. API overview

All routes sit under `/api`.

| Area | Routes (summary) |
|---|---|
| Health/config | `GET /health`, `/ready`, `/config` |
| Auth | `GET /auth/login`, `/auth/callback`, `POST /auth/logout`, `GET /auth/me` |
| Documents | `POST /documents`, `POST /documents/{id}/versions`, `POST /documents/versions/{id}/publish`, `POST /documents/versions/{id}/archive`, `GET /documents` (title, description, category), `GET /documents/{id}`, `GET /documents/versions/{id}/content` |
| Signing | `POST /documents/versions/{id}/sign`, `GET /signatures/me`, `/signatures/{id}`, `/signed-pdf`, `/certificate`, `/evidence`, `/verify` |
| Campaigns | `GET /campaigns/_meta/dashboard` (overview figures), `POST /campaigns`, `/{id}/documents`, `/{id}/targets/preview`, `/{id}/launch`, `/{id}/remind`, `/{id}/close`, `/{id}/cancel`, `GET /campaigns`, `/{id}`, `/{id}/assignments` (filters: status, document, group, viewed, overdue) |
| Reports | `POST /campaigns/{id}/reports`, `GET /campaigns/{id}/reports`, `GET /reports/{id}/pdf`, `/csv`, `/verify` |
| Admin | users and roles, audit and audit integrity, signing keys (rotate, revoke), mail connector (get, put, test-connection, send-test, test-isolation), notifications |
| Diagnostics (admin) | `GET /admin/diagnostics` — application, database, filesystem, signing key, OIDC, directory, SMTP, worker; fixed phrases only |
| Directory (admin) | `GET /admin/directory/sources`, `PUT`/`DELETE /admin/directory/sources/{source}/config`, `POST /admin/directory/sync?source=`, `GET /sync-runs`, `/groups`, `/groups/{id}/members` (groups and members are also readable by OPERATOR) |

## 15. Frontend

A single-page React app, role-aware:

- **Signer:** one page, **Mes signatures** (to sign, coming up, signed with the signed PDF one
  click away), a detail page that shows the document as it will be signed (earlier signers'
  stamps and their own elements in place), consent and sign button, and their proofs and chain
  of signers.
- **Operator:** *Documents* (library), *Faire signer* (the five-screen flow: signers and
  planning, documents, preparing in the PDF.js editor, review and send, signed documents) and
  *Suivi* (campaigns, signed documents, reminders, changes after sending), reports.
- **Admin:** users and roles, company logo, audit log and integrity check, signing keys,
  diagnostics, mail (SMTP, Microsoft Graph, Gmail) and directory (Entra ID, Google Workspace,
  LDAP: forms drawn from each connector's description, with help bubbles and a step-by-step
  guide).

The user guide is [user-guide.md](user-guide.md).

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
| `MASTER_KEY_FILE`, `SESSION_SECRET_FILE`, `OIDC_CLIENT_SECRET_FILE` | Path to a file holding the secret (Docker/Kubernetes secrets); wins over the plain variable |
| `STORAGE_ROOT`, `MAX_UPLOAD_SIZE_MB` | File storage |
| `CONSENT_TEXT`, `CONSENT_VERSION` | Consent wording, recorded in each signature |
| `NOTIFICATION_WORKER_ENABLED`, `NOTIFICATION_WORKER_INTERVAL_SECONDS` | Background worker (mail, reminders, renewals, scheduled sync) |
| `RATE_LIMIT_ENABLED` | Per-IP rate limiting (default on) |
| `FQDN`, `HTTPS_PORT`, `CERT_DIR` (compose/installer, not app settings) | HTTPS name, published port, certificate directory |

Directory connector and SMTP credentials are intentionally **not** variables;
they are entered in the admin UI and stored encrypted.

## 17. Running and testing

```bash
cp .env.example .env            # edit at least the DB password and master key
mkdir -p -m 700 certs           # before the first `up` (else Docker creates it as root)
docker compose up -d --build    # UI on http://127.0.0.1:4180 and https://127.0.0.1:4443
./crashtest/start.sh            # CrashTest: a separate stack with the mock SSO and fictional accounts
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d postfix-test
```

Where each kind of test runs (spec §95):

| Level | Where | What |
|---|---|---|
| Lint, types, unit and API tests | dev machine or CI | `ruff`, `mypy`, `pytest` (SQLite + a real mock OIDC + scripted SMTP servers), `vitest` |
| Integration, smoke, CrashTests | the Integrations VM, in Docker | `tests/UAT/CrashTests-Sign/run-all.sh`: smoke (real PostgreSQL, nginx, SSO, Postfix), SMTP scenarios, seed, Playwright in a real browser, restore test |
| End-to-end in a browser | the Integrations VM, on a **throwaway CrashTest stack** | `scripts/e2e.sh` (via `scripts/integration-run.sh`): its own containers, ports and volumes (prefix `lcit-e2e`, see `docker/e2e.env`), the CrashTest dataset, the mock SSO, Playwright; everything is removed at the end, the real stack and its data are never touched |
| Destructive reset | the Integrations VM only | `scripts/integration-reset.sh --yes --seed` |

### CrashTest

`crashtest/` is a **separate stack** for tests and demonstrations: `./crashtest/start.sh` starts it
(own Compose project named after `LCIT_SIGN_PREFIX`, never `lcit-sign`; own PostgreSQL named
`lcit_sign_crashtest`; own volumes), applies the migrations and loads the dataset;
`./crashtest/reset.sh` destroys **only that project's** containers and volumes and starts again.
It is the only place the mock SSO exists (profile `crashtest`; the normal `docker-compose.yml`
has no SSO, no bootstrap administrator and no fictional person by default — a clean installation
starts with the built-in local administrator alone).

The dataset (`crashtest/seed.py`, run inside the api container) refuses to load unless **both**
`LCIT_SIGN_CRASHTEST=true` (set only by `crashtest/docker-compose.crashtest.yml`) and a database
name ending in `_crashtest` hold, and never in `production`. It creates the 24 people of the
demonstration directory plus Sophie Bernard, Claire Moreau, Paul Muller and Admin Crash as local
accounts whose **password is the first name in lowercase** (`bob.dupont@lcit-test.local` / `bob`),
stored as the usual scrypt hash, and the same people are available through the mock SSO. Roles:
Everyone is a `SIGNER`; Paul Muller is also `OPERATOR` and Admin Crash `ADMIN`. Campaigns: *Entretiens RH 2027* (owner Alice, preparer
Sophie, pending), *NDA Juridique* (owner Claire, pending), *Campagne sécurité 2026* (the RSSI Erwan
signed, someone signed, others pending) and *Politique mots de passe 2026* (recipients waiting).

`scripts/integration-run.sh` runs a repository script on the VM over SSH (host
key verified, never `StrictHostKeyChecking=no`; the key stays in `~/.ssh`). The
working tree is the source of truth, the VM never is.

The test Postfix (`docker/postfix-test`) accepts only fictional
`lcit-test.local` mailboxes, denies every other destination, has outbound
delivery disabled, and generates its certificate and SASL password at start.
Twelve scenarios run against it: OK (plain, STARTTLS+AUTH, implicit TLS), AUTH
KO, TLS KO (two ways), relay denied, unknown mailbox, 4xx, 5xx, timeout,
connection refused.

CI (`.github/workflows/ci.yml`): backend and frontend checks, `pip-audit`,
`npm audit`, `shellcheck`, compose and `kubeconform` validation, `gitleaks` on
the full history, weekly. Real Microsoft 365 tests are the last step and are
deliberately not automated.

## 18. Known limits, deviations from the specification, open points

Deliberate deviations (design choices):

- **Signing keys are derived, not stored in `/var/lib/lcit-sign/keys/`.** Each
  Ed25519 key comes from `LCIT_SIGN_MASTER_KEY` + a key id (HKDF); the database
  keeps only public keys. Same goal as spec §44 (no private key in Git, images,
  PostgreSQL or logs), different mechanism. Consequence: the master key is the
  single secret to protect and back up.
- **Signers read the document in the browser's native PDF viewer (an `<iframe>`).**
  Only the element editor uses PDF.js. Uploads are validated, but hyperlink opening (`noopener`, "you are
  leaving LCIT Sign" notice, spec §24) is the browser's behaviour, not LCIT Sign's.
- **SSO and security settings are environment-driven, not editable in the UI.**
  The `OIDC_CONFIGURATION_CHANGED` and `SECURITY_CONFIGURATION_CHANGED` audit
  events therefore never occur, and the admin menu has no SSO/General/Security
  pages.
- **No automatic expiry of overdue assignments**: they stay pending past their
  deadline rather than becoming `EXPIRED` (a late signature is still accepted).

Not implemented:

- Per-document periodicity and consent-text override (spec §26): documents
  carry a title, description and category, renewal is a campaign property, and
  one consent text is configured globally.
- Reports cover one campaign, not an arbitrary document / period / population
  selection (spec §67).

Untested against the real world:

- **The Entra ID directory and the Microsoft Graph mailer have been verified on the real
  LCIT tenant.** The **Google Workspace directory and Gmail, and LDAP, have only been
  exercised against mocked HTTP transports / a fake LDAP**, never a real domain or server.
  The Graph procedure (`docs/microsoft-graph-setup.md`) must be followed by a tenant
  administrator, including the mandatory isolation test.
- After someone has signed in with SSO, their identity (issuer, subject) is the SSO's, and
  nothing in the row says which directory they came from: a directory sync finds them again by
  e-mail, and a person who leaves the directory after that is not deactivated. Fixing this
  needs a source marker on the user (an additive migration) and is deliberately not done yet.
- Kubernetes manifests are schema-validated (`kubeconform`), not applied to a
  live cluster.

Inherent limits:

- **Not eIDAS.** The proof is internal and verifiable with the platform's public
  keys; it is not a qualified signature or timestamp.
- **The master key is a single point of compromise** for signing and stored
  credentials; an external vault/KMS is not integrated (it can be mounted as a
  file via `LCIT_SIGN_MASTER_KEY_FILE`).
- **The audit chain is tamper-evident, not tamper-proof**: a database owner could
  rewrite all of it. Keep an off-site copy of the latest hash if that matters.
- The rate limiter is in memory (one API process); the API runs the background
  worker and applies migrations, so it is deployed as a single replica.

