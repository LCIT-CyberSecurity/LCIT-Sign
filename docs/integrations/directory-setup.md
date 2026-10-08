# Directory setup: Microsoft Entra ID and Google Workspace

The **directory** is where LCIT Sign reads users and groups from, so that a campaign can target people and whole
teams. It is **read-only**: LCIT Sign never writes to Microsoft 365 or Google Workspace. It is separate from the
**sign-in** (SSO), which has its own app registration, see [`entra-sso-test.md`](entra-sso-test.md). Even when the
same Microsoft tenant serves both, they are two settings.

One directory is active at a time (Entra ID, Google Workspace or LDAP / Active Directory). A fresh installation has
none. Everything below is done once by a cloud administrator; LCIT Sign itself only needs the values listed in
"In LCIT Sign".

## What LCIT Sign reads

| | Microsoft Entra ID | Google Workspace |
|---|---|---|
| API | Microsoft Graph v1.0 | Admin SDK Directory API v1 |
| Authentication | Application (client credentials): tenant ID, client ID, client secret | Service account with domain-wide delegation: key (JSON) and an administrator e-mail |
| Users | `id`, `mail` (else `userPrincipalName`), `givenName`, `surname`, `displayName`, `accountEnabled`, and the attribute chosen for teams | `id`, `primaryEmail`, `name`, `suspended`, `orgUnitPath` and `organizations` |
| Groups | `displayName`, `description`, members (users and nested groups) | `name`, `email`, `description`, members (users and nested groups) |
| Account switched off | `accountEnabled = false` | `suspended = true` |

A person who disappears from the directory, or is switched off there, is **disabled** in LCIT Sign, never deleted.
People added by hand or marked external are never touched by a sync. People are matched by e-mail address.

## Microsoft Entra ID

Done by someone allowed to register applications **and** to grant admin consent (Application Administrator or
Cloud Application Administrator for the registration, Privileged Role Administrator or Global Administrator for the
consent).

1. **Entra admin center → Identity → Applications → App registrations → New registration.**
   Name `LCIT Sign directory` (or similar), *Accounts in this organizational directory only*. No redirect URI is
   needed: the directory read uses no user sign-in.
2. On the *Overview* page, note the **Application (client) ID** and the **Directory (tenant) ID**.
3. **Certificates & secrets → Client secrets → New client secret.** Choose a lifetime (and plan its renewal). Copy the
   **Value** at once: it is shown only once. The *Secret ID* is not what LCIT Sign needs.
4. **API permissions → Add a permission → Microsoft Graph → Application permissions** (not *Delegated*), and add
   exactly these three:
   - `User.Read.All`
   - `Group.Read.All`
   - `GroupMember.Read.All`
5. Click **Grant admin consent for \<your tenant\>** and check that the *Status* column shows a green tick for the
   three permissions. Without this step every sync is refused with a 403.
6. Nothing else: no role in Azure, no license, no `Directory.ReadWrite.*` permission.

Notes:

- A person without `mail` is identified by their `userPrincipalName`. Guests and accounts without a mailbox appear
  in the list too, so restrict the groups you target in campaigns rather than the permissions.
- To use the department (or another attribute) as the team name, make sure the field is filled in Entra
  (*Users → a user → Properties → Job information → Department*). Available attributes: department, office location,
  company name, job title, city.
- `Group.Read.All` covers Microsoft 365 groups, security groups and distribution groups. Dynamic groups are read
  as they are at the time of the sync.
- The secret expires. When it does, syncs fail with an authentication error: create a new secret, paste its value in
  LCIT Sign, and delete the old one.

## Google Workspace

Done by a Google Cloud project owner (steps 1 to 4) and a **super administrator** of the Workspace domain (steps 5
and 6). There is no Google Cloud role to give the service account.

1. **Google Cloud console (console.cloud.google.com):** choose or create a project (for example `lcit-sign`).
2. **APIs & Services → Library → Admin SDK API → Enable.**
3. **IAM & Admin → Service accounts → Create service account** (for example `lcit-sign-directory`). Skip the optional
   role and user-access steps.
4. Open the account → **Keys → Add key → Create new key → JSON**. The downloaded file holds `client_email` and
   `private_key`: it is the secret LCIT Sign needs. Keep it out of Git and chats. On the account's *Details* page,
   note the **Unique ID / Client ID** (a long number).
   If the key creation is refused, an organization policy (`iam.disableServiceAccountKeyCreation`) forbids it:
   ask the organization administrator to allow it for this project.
5. **Admin console (admin.google.com), signed in as a super administrator:** *Security → Access and data control →
   API controls → Manage domain-wide delegation → Add new.*
   - **Client ID:** the number noted in step 4.
   - **OAuth scopes** (comma-separated, exactly these three, all read-only):

     ```text
     https://www.googleapis.com/auth/admin.directory.user.readonly,https://www.googleapis.com/auth/admin.directory.group.readonly,https://www.googleapis.com/auth/admin.directory.group.member.readonly
     ```
6. Choose the **administrator e-mail** the service account will act as (it reads the directory on that person's
   behalf). A dedicated administrator account is preferable to a personal one. It must be an administrator allowed
   to list users and groups.

Notes:

- The delegation can take a few minutes to apply. An `unauthorized_client` answer means it is not active yet, or a
  scope is mistyped.
- Only users and groups of the domain (`my_customer`) are read.
- For teams, LCIT Sign can use either the Google groups, or each person's **organizational unit** (path with
  ` / `) or their **Department** field (*Directory → Users → a user → Organization*).

## In LCIT Sign

*Administration → Identities & access → Directory*, then the Microsoft Entra ID or Google Workspace card
(*Configure*):

| Field | Entra ID | Google Workspace |
|---|---|---|
| Identifiers | Tenant ID, Application (client) ID | E-mail of an administrator |
| Secret (encrypted, never shown again) | Client secret value | Content of the service account JSON key |
| Team name from | Directory groups, an attribute, or both | Directory groups, organizational unit / department, or both |

Save, then **Sync now**. The result (users added, updated, disabled; groups; memberships) is shown under the card.
You can also choose a schedule (manual, every 15 minutes, hourly, every 6 hours, daily). Saving a directory makes it
the active one (only one at a time); *Use this directory* switches back to another configured one. The secret is stored encrypted with the master key, so keep
`LCIT_SIGN_MASTER_KEY` unchanged (see the README).

## Quick checks if a sync fails

| Symptom | Likely cause |
|---|---|
| Entra: 401 / `invalid_client` | Wrong secret (Secret ID pasted instead of the Value), expired secret, wrong tenant or client ID |
| Entra: 403 / `Authorization_RequestDenied` | Admin consent not granted, or a permission is *Delegated* instead of *Application* |
| Google: `unauthorized_client` | Domain-wide delegation missing, not yet propagated, wrong Client ID, or a scope mistyped |
| Google: 403 on listing | The administrator e-mail is not an administrator allowed to read users and groups |
| Google: 403 `accessNotConfigured` | Admin SDK API not enabled in the project of the service account |
| Nobody appears | The sync never ran, or another directory is the active one |
| Teams are empty | Entra / Google attribute not filled for the users, or "groups" selected while groups are empty |
