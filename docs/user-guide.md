# User guide — LCIT Sign

The interface is in French; button and menu names are quoted as they appear on screen.

| Profile | What they do | Chapters |
|---|---|---|
| **Signer** (everyone) | The standard user: signs what is asked of them and **prepares, sends and follows their own campaigns** | [1](#1-signing-in) · [2](#2-signing-a-document) · [3](#3-requesting-signatures) · [4](#4-follow-up) · [5](#5-the-document-library) |
| **Operator** | Global supervision: sees **every** campaign, changes owners and preparers; does not read confidential content | [4](#4-follow-up) · [4a](#4a-who-sees-what-in-a-campaign) |
| **Administrator** | Access, directory, e-mail, keys; full access | [6](#6-administration) · [7](#7-installation-and-first-access) |

One person may have several profiles. The left menu only shows what you may do.

---

## 1. Signing in

1. Open LCIT Sign and click **Continuer avec Microsoft**, **Continuer avec Google** or **Continuer avec le SSO**
   (depending on your company), then pick your company account.
2. You land on **Mes signatures**.

**Local sign-in** ("Connexion locale", identifier or e-mail + password) is for the system account and for people
an administrator gave a **local account**; they choose their own password at first sign-in. With no SSO
configured, this form is the sign-in page. A session idle for one hour is closed: just sign in again.

---

## 2. Signing a document

**Mes signatures** lists *À signer* (what you are asked to sign, with the deadline), *À venir* (yours once
someone else, e.g. the CISO, has signed; you get an e-mail then) and *Signés* (open or download the signed
PDF, see the proof and signers).

To sign: open the document (it appears as you will sign it), fill the requested fields (marked *), tick the
consent box, click **Signer**. You then see **Document signé** with an identifier like `SIG-3F9A12C0B7D4`, can
download the signed PDF and the certificate, and receive a confirmation e-mail.

**Signing needs two things:** the **SIGNER** role (given to every active account by default; without it the
signature is refused) **and** an active signature request addressed to you. There is no unasked signature:
to sign your own document, create a campaign and designate yourself.

When one request holds several documents for you, **Signer les N documents** signs them all with one consent;
common questions are asked once.

**Checking a signature.** *Preuve et signataires* shows who signed, in what order and when, the identity sealed
at signing time, the hashes of the original and signed documents and the sealing key. Any later change of the
file would be reported.

---

## 3. Requesting signatures

Menu **Faire signer**: any standard user (SIGNER) can request signatures on their own documents, including
their own. Start with a request name ("PSSI 2026"), then five screens. Everything is saved as you go; resume
from *En préparation*; an unsent request can be deleted.

1. **Signataires et planning.** Add *a specific person* (signs once for the whole request) or *each recipient* (a
   list of people who each sign their own copy, built from directory groups, people, or everyone; always last).
   Signers go **in order**: position 2 is only asked after position 1, and gets a copy bearing the previous
   signature. An **external person** (first name, last name, e-mail) is flagged *external* and never touched by a
   directory sync. Optional planning: start date (a future date schedules the sending), deadline (30 days by
   default), reminders (none by default), renewal.
2. **Documents.** Drop PDF or Word / LibreOffice files (converted to PDF), or pick from the library; a library
   document is a template and is never modified.
3. **Préparer.** The editor: choose the signer, drag **signature**, **date**, **time**, **full name**, **first
   name**, **last name**, **e-mail**, **place**, **company logo** or a **text to fill in** onto the page; move and
   resize with the mouse, fine-tune with the arrow keys, **Suppr** deletes. A fill-in field with a shared name is
   asked once across documents. Automatic elements come from the signer's **account** and the clock: nobody can
   sign under another identity.
4. **Vérifier et envoyer.** A summary; anything missing is named precisely. **Envoyer pour signature** asks for
   confirmation. A sent request can no longer be edited (cancel and recreate), except to add people or documents.
5. **Documents signés.** Signed documents arrive as they come in, with their proof.

---

## 4. Follow-up

Menu **Suivi**.

- **Campagnes**: status (scheduled, sent, closed, cancelled, archived), dashboard and filters. Open a campaign to see
  who signed and who has not, **remind** one person or everyone, **add or remove people**, **add a document** to a
  running request, **download** signed PDFs or open proofs, **close**, **cancel** (nobody can sign any more, what is
  signed stays), **archive**, generate the signed **report** (PV), or **delete** (only a campaign that never produced
  a proof; otherwise it is kept and archived).
- **Documents signés**: all signed documents for one or several campaigns, with search; **Exporter en ZIP**.

---

## 4a. Who sees what in a campaign

Each campaign has an **owner** and possibly other **preparers** (a one-off right on that single campaign). "Créée
par" shows the creator when it is someone else: history is never rewritten.

| | Owner or preparer | Signer of another campaign (or mere signer of this one) | Operator | Administrator |
|---|---|---|---|---|
| See the campaign, status, signers, progress | yes | **no** (it does not exist for them) | yes, all | yes |
| Remind, cancel, close, archive | yes | no | yes | yes |
| Change owner, add or remove a preparer | yes | no | yes | yes |
| **Read the content**: documents, signed PDFs, certificates, proofs, exports, reports | yes | **no** | **no**, unless preparer of that campaign | yes |
| Prepare, edit, send | yes | no | no | yes |

**Absence or departure.** An operator adds a colleague as preparer, then makes them owner; the previous owner stays
preparer until removed; history, signatures and audit log are kept. **Exceptional access.** An operator who must read
the content adds themselves as preparer of that campaign: it is **recorded in the audit log**. The campaign page has
an *Propriétaire et préparateurs* card to do this.

## 5. The document library

Menu **Documents**: reusable templates with title, description, category and **versions**. A **published version is
immutable**: to fix something, create a new version, so a signature always refers to the exact text the person saw.

---

## 6. Administration

Menu **Administration** (administrators).

### Users and roles

| Role | Rights |
|---|---|
| **SIGNER** | The standard user, **given to every active account by default**: prepare documents, create and run campaigns (own or as preparer), pick themselves or others as signers, and **sign**. Without it no signature is accepted, even with a pending request |
| **Campaign preparer** (not a role) | One-off right on **one** campaign: read its content and run it with its owner |
| **OPERATOR** | Global supervision: see all campaigns, change owners and preparers; **no** confidential content unless added as preparer (audited) |
| **ADMIN** | Everything administrative: users, directory, e-mail, keys, audit; full access |

Add a person by hand with an authentication method: **SSO** (no password here) or **Compte local** (mandatory initial
password, changed at first sign-in, never displayed or logged). People can be **disabled** (and re-enabled) or
**deleted**, except those who signed (their history is kept). The last active administrator can be neither disabled,
deleted nor stripped of the ADMIN role. A role taken away by an administrator is never given back by a directory sync.

### Logo

The company logo shows top left and on the sign-in page; replace it with an image file or go back to the LCIT logo.

### Identités & accès

One page, two independent sections, even when Microsoft Entra ID serves both:

- **Connexion**: **one** SSO provider is active (Microsoft Entra ID, Google or a generic OIDC provider); the sign-in
  page offers only it, plus the always-available **local sign-in**. Saving a provider activates it; "Utiliser ce
  fournisseur" switches. If the server's `LCIT_SIGN_OIDC_*` variables are set they impose the SSO (the page says so).
- **Annuaire**: **one** directory is active, the only one that syncs: **Microsoft Entra ID**, **Google Workspace** or
  **LDAP / Active Directory**. A fresh installation has **no directory** ("Aucun annuaire configuré"); the demo
  directory exists only in CrashTest. Each form has help bubbles and examples; secrets are encrypted and **never
  shown again**. The team name comes from directory groups, an attribute, or both. *Synchroniser maintenant* (or a
  schedule) runs a sync; someone who disappears from the directory is **disabled**, never deleted; people added by
  hand or external are never touched.

Anyone who authenticates may enter LCIT Sign (a disabled account stays refused); their roles say what they can do.
A new active account is SIGNER at once.

### E-mail

SMTP, Microsoft Graph or Gmail, with a connection test and a test message. See
[`microsoft-graph-setup.md`](microsoft-graph-setup.md).

### Signing keys, audit, diagnostics

Signatures are sealed by a platform key; **renewing** it keeps old signatures verifiable. The **audit** log is chained
and its integrity can be checked. **Diagnostic** shows database, storage, signing key, SSO, mail and worker, and
reminds you while the system account still has its initial password.

---

## 7. Installation and first access

See the [README](../README.md). On first start:

1. Sign in with the local system account (`admin`, via "Connexion locale"), initial password `SecretPassword`: the app
   asks you to **change it at once** (strong password required) and reminds you at every sign-in until you do. A fresh
   installation contains **only this account**: local sign-in, no SSO, no directory, no fictional person or group.
2. Set up the SSO (see [`entra-sso-test.md`](entra-sso-test.md)); the sign-in page then shows your provider's button.
3. Under **Administration**: connect the directory and e-mail, import the logo, give roles.
4. Under **Faire signer**: a first test request with two colleagues.

## FAQ

**I do not see "Faire signer".** You need the SIGNER role, given by default to every active account; an administrator can
give it back (*Administration → Utilisateurs*).

**I did not receive the "to sign" e-mail.** Check *Administration → E-mail* (send a test) and that the request is not
scheduled for a future date. The document is always in *Mes signatures*.

**"Ce document vous est demandé par plusieurs campagnes."** The same document is asked twice by two requests: open it from
the wanted request (*À signer*); each request is signed separately.

**A signature is refused with "La clé maître du serveur ne correspond pas…".** The server master key was changed without
the signing key following: tell an administrator, who can renew the signing key. Nothing is signed until this is fixed.

**Can I cancel a signature?** No, a signature is final. You can cancel the **request** for people who have not signed yet.
