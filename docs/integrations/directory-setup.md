# Directory setup: Microsoft Entra ID, Google Workspace and LDAP

The **directory** is where LCIT Sign reads users and groups from, so that a campaign can target people and whole
teams. It is **read-only**: LCIT Sign never writes to Microsoft 365 or Google Workspace. It is separate from the
**sign-in** (SSO), which has its own app registration, see [`entra-sso-test.md`](entra-sso-test.md). Even when the
same Microsoft tenant serves both, they are two settings.

One directory is active at a time (Entra ID, Google Workspace or LDAP: OpenLDAP, Active Directory…). A fresh installation has
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
People marked external are never touched by a sync. The *Users* page no longer has a form to add someone by e-mail address: people come from the directory (import them, then give them roles). People are matched by e-mail address.

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

## LDAP: OpenLDAP and Active Directory

LCIT Sign reads the directory with a **read-only service account**, over an encrypted connection, and never writes
to it. Same behaviour as the cloud directories: a person who disappears from the search result or is disabled is
**disabled** in LCIT Sign, never deleted; people are matched by e-mail address.

### Common requirements

- **Network:** the `api` container must reach the server on **TCP 636** (`ldaps://`) or **TCP 389 with StartTLS**.
  No other port is accepted (not 3268 / 3269, the Global Catalog). Private addresses are fine.
- **Name resolution:** the container uses Docker's DNS, which forwards to the host's resolver. The server name you
  enter must resolve from the LCIT Sign host (for Active Directory, a host that uses the AD DNS servers).
- **Encryption is mandatory:** `ldap://` without StartTLS is refused, because the service account's password would
  travel in clear text.
- **The server certificate is always verified** against the CA store of the `api` container (Debian
  `ca-certificates`). A certificate issued by a **public** CA works as is. A certificate from an **internal CA**
  (Active Directory Certificate Services, your own OpenLDAP CA) is refused with "certificate not recognized" until
  that CA is trusted: put the CA certificate(s) in a PEM bundle, for example `secrets/ldap-ca.pem`, and add a
  `compose.override.yaml` next to `compose.yaml` (read by the manager script and by `docker compose`; not versioned):

  ```yaml
  services:
    api:
      environment:
        SSL_CERT_FILE: /run/secrets/lcit-sign/ldap-ca.pem
  ```

  `./secrets` is already mounted read-only at `/run/secrets/lcit-sign`. `SSL_CERT_FILE` **replaces** the default store
  of the API process, so build the bundle from the public roots plus your CA:

  ```bash
  cat /etc/ssl/certs/ca-certificates.crt my-internal-ca.crt > secrets/ldap-ca.pem
  ```

  Then recreate the container: `docker compose up -d api` (or option 1 of the manager script).
- **Check the connection first**, from the LCIT Sign host, with the same parameters (replace the values):

  ```bash
  ldapsearch -H ldaps://ldap.example.org:636 -D "cn=lcit-sign,ou=services,dc=example,dc=org" -W \
    -b "dc=example,dc=org" "(objectClass=person)" mail givenName sn
  ```

### OpenLDAP

1. **TLS on the server.** `slapd` must serve `ldaps://` (or accept StartTLS) with a certificate whose name matches
   the server name and that carries the *server authentication* usage:

   ```ldif
   dn: cn=config
   changetype: modify
   replace: olcTLSCACertificateFile
   olcTLSCACertificateFile: /etc/ldap/tls/ca.crt
   -
   replace: olcTLSCertificateFile
   olcTLSCertificateFile: /etc/ldap/tls/ldap.example.org.crt
   -
   replace: olcTLSCertificateKeyFile
   olcTLSCertificateKeyFile: /etc/ldap/tls/ldap.example.org.key
   ```

   and add `ldaps:///` to the listener URLs (`SLAPD_SERVICES` on Debian / Ubuntu).
2. **Service account**, in an OU outside the people tree:

   ```ldif
   dn: ou=services,dc=example,dc=org
   objectClass: organizationalUnit
   ou: services

   dn: cn=lcit-sign,ou=services,dc=example,dc=org
   objectClass: organizationalRole
   objectClass: simpleSecurityObject
   cn: lcit-sign
   userPassword: {SSHA}…        # generated with: slappasswd
   ```
3. **Read-only access** to people and groups only, never to `userPassword`: add to the database ACLs, before the
   catch-all rule:

   ```ldif
   dn: olcDatabase={1}mdb,cn=config
   changetype: modify
   add: olcAccess
   olcAccess: {0}to attrs=userPassword,shadowLastChange by * none
   olcAccess: {1}to dn.subtree="dc=example,dc=org" by dn.exact="cn=lcit-sign,ou=services,dc=example,dc=org" read by * break
   ```
4. **Directory shape expected by the defaults:** people are `inetOrgPerson` (or `person`) with `mail`, `givenName`,
   `sn`; groups are `groupOfNames` with `member` attributes holding the members' DNs (a `groupOfNames` must have at
   least one `member`); `entryUUID` is maintained by OpenLDAP and is used as the stable identifier.

Fields in LCIT Sign:

| Field | Value |
|---|---|
| Server address | `ldaps://ldap.example.org:636` (or `ldap://ldap.example.org:389` with StartTLS = Yes) |
| Bind account (DN) | `cn=lcit-sign,ou=services,dc=example,dc=org` |
| Search base (DN) | `dc=example,dc=org` (or `ou=people,dc=example,dc=org` to restrict) |
| People filter | `(objectClass=inetOrgPerson)` |
| E-mail / first name / last name attribute | `mail` / `givenName` / `sn` |
| Stable identifier attribute | `entryUUID` |
| Groups filter | `(objectClass=groupOfNames)` |
| Members attribute | `member` |
| Team name from | Groups, an attribute (for example `departmentNumber` or `ou`), or the OU holding the person |
| Bind password | the password given to `cn=lcit-sign` |

Lock state: LCIT Sign reads `nsAccountLock` (389 Directory Server) and `userAccountControl` (Active Directory) but
**not** OpenLDAP's `pwdAccountLockedTime` (ppolicy). To treat locked accounts as gone, exclude them in the filter:
`(&(objectClass=inetOrgPerson)(!(pwdAccountLockedTime=*)))`.

### Active Directory (Windows Server 2025 domain controller)

1. **LDAPS on the domain controller.** The DC needs a certificate with the *Server Authentication* usage whose
   subject or SAN contains the DC's DNS name (the one you will enter in LCIT Sign). With Active Directory
   Certificate Services, the *Domain Controller Authentication* / *Kerberos Authentication* templates with
   auto-enrollment do this; the DC then answers on **636** by itself. Check with
   `openssl s_client -connect dc01.corp.example.com:636` from the LCIT Sign host.
2. **Signing and channel binding.** Recent domain controllers, Windows Server 2025 included, are hardened by default:
   LDAP signing is required and simple binds in clear text are refused (check the policy of your domain). LCIT Sign
   always binds through TLS (LDAPS, or StartTLS), which meets this
   requirement; do **not** lower the "LDAP server signing requirements" policy for LCIT Sign. It uses a simple bind
   (DN and password), not NTLM / Kerberos / GSSAPI.
3. **Service account.** In *Active Directory Users and Computers*, create a dedicated user, for example
   `svc-lcit-sign` in `OU=Service Accounts,DC=corp,DC=example,DC=com`, member of **Domain Users only**. Set a long
   random password, *Password never expires* and *User cannot change password*. No delegation and no admin group
   are needed: by default any authenticated domain account can read users, groups and their membership.
   (If your forest restricts it with a *List object* / read deny on some OUs, grant `Read` on the OUs to read.)
4. **Bind account format:** a full DN is required (`CN=svc-lcit-sign,OU=Service Accounts,DC=corp,DC=example,DC=com`).
   The `user@domain` form is rejected by the form's check.
5. **Fields in LCIT Sign:**

| Field | Value |
|---|---|
| Server address | `ldaps://dc01.corp.example.com:636` (the DC's DNS name, matching its certificate) |
| Bind account (DN) | `CN=svc-lcit-sign,OU=Service Accounts,DC=corp,DC=example,DC=com` |
| Search base (DN) | `DC=corp,DC=example,DC=com`, or an OU such as `OU=Employees,DC=corp,DC=example,DC=com` |
| People filter | `(&(objectCategory=person)(objectClass=user))` (computer accounts are excluded) |
| E-mail / first name / last name attribute | `mail` / `givenName` / `sn` |
| Stable identifier attribute | `objectGUID` |
| Groups filter | `(objectClass=group)` |
| Members attribute | `member` |
| Team name from | Groups, an attribute (for example `department`), or the OU holding the person |
| Bind password | the password of `svc-lcit-sign` |

Behaviour specific to Active Directory:

- **Disabled accounts** (`userAccountControl` bit 2) are synced as inactive. People without a `mail` attribute are
  skipped, so fill it in (or use another attribute in *E-mail attribute*, for example `userPrincipalName`).
- **`objectGUID`** is binary. LCIT Sign stores it as an opaque, stable text value; it is not human readable. It
  survives renames and moves between OUs, unlike the DN. (I have not validated this against a real Windows Server
  2025 domain; run a first sync and check the result before relying on it.)
- **Large groups:** Active Directory returns at most 1500 values of `member` per group in one answer, and LCIT Sign
  does not follow the range continuation. Members beyond the 1500th of a group are not seen. Split very large groups
  or target a smaller one.
- **Primary group:** a person's *primary* group (usually *Domain Users*) is not listed in `member`, so it cannot be
  used as a team.
- **Nested groups** are recorded (a group inside a group); *Team name from → Groups* then follows the structure.
- Reads are paged (500 entries per page), well below the default server limit of 1000.

### Quick checks if an LDAP sync fails

| Symptom | Likely cause |
|---|---|
| "The bind account is refused" | Wrong DN or password, account disabled or locked, `user@domain` used instead of a DN |
| "The LDAP server does not answer" | Wrong name or port, firewall, name not resolvable from the container |
| "The secure connection failed … certificate not recognized" | Internal CA not trusted by the `api` container (see above), expired certificate, or no server-authentication usage |
| "Server refused: port …" | Only 389 and 636 are allowed |
| Zero users | Base DN too narrow, filter that matches nothing, or no `mail` on the entries |
| Duplicate-looking people after a move | The identifier attribute is the DN (empty attribute): use `entryUUID` / `objectGUID` |
| Empty teams | Group filter empty while "Groups" is selected, or attribute not filled |

## In LCIT Sign

For LDAP, the fields are listed in the OpenLDAP and Active Directory tables above. For the cloud directories:

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

## Testing the connection

On each configured connector (*Administration → Identities & access → Directory*), **Test the connection** checks
that the saved settings really work, *before* you synchronise. It is read-only: it asks for one user, one group and one
member, writes nothing to the directory or to LCIT Sign's users, groups and memberships (only an audit line,
`DIRECTORY_CONNECTION_TESTED`, with the source, the status and the error codes), and is not a synchronisation. **Synchronise
now** is the separate button that updates users and groups.

Each step is shown on its own, so a partial result tells you what to fix:

| Connector | Steps |
|---|---|
| Microsoft Entra ID | authentication (token), access to Microsoft Graph, users, groups, memberships |
| Google Workspace | service account key, signed assertion, access token, domain-wide delegation, users, groups, memberships |
| LDAP / Active Directory | network, TLS, bind, search base, users query, groups query |

A failed step carries our own code (`INSUFFICIENT_PERMISSIONS`, `SECRET_EXPIRED`, `TIMEOUT`, `TLS_ERROR`, `BASE_DN_ERROR`…),
the provider's own code when it helps (`AADSTS7000222`, `unauthorized_client`, `HTTP 403`…) and a recommended action. A
warning means the step works but returned nothing (for example a user filter that matches nobody).

Nothing a provider answers is shown as it came: no secret, token, private key, JWT, `Authorization` header or raw
response body ever reaches the page, the logs or the audit. The server log has one line per step
(`source=… operation=… status=… provider_code=…`).

In the synchronisation history, a **failed** run has a *View detail* button: the date, the source, the error, the
provider's code and the recommended action when the message contains them. Older runs only show their error sentence.

### Testing the sign-in provider

*Administration → Identities & access → Connexion* has the same **Test the connection** button on a saved Microsoft or
Google sign-in provider. It is read-only and nobody signs in: it checks that the provider is reachable (`discovery`) and
that it accepts the saved application ID and secret (`credentials`). For Microsoft it requests a token with the
application's own credentials, so the usual `AADSTS…` codes appear. For Google it sends the secret with a deliberately
invalid authorisation code: `invalid_client` means the ID or the secret is wrong, `invalid_grant` means the client was
accepted. Only an audit line (`LOGIN_PROVIDER_TESTED`) is written. The redirect address cannot be checked without a
real sign-in.

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
