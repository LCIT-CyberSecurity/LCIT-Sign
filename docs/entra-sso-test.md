# Sign-in with Microsoft Entra ID

Goal: sign in to LCIT Sign with an existing Microsoft 365 account, **without creating an account**, giving the
application only what it needs (the name and e-mail of the person signing in). Nothing is read from the company
directory and nothing is written to Microsoft 365.

## Microsoft vocabulary

| Term | What it is | Where to find it |
|---|---|---|
| **Directory (tenant) ID** | The identifier of *your* Microsoft 365 tenant (a code like `1b2c…`) | Entra → Overview → *Tenant ID* |
| **Application (client) ID** | The identifier of the "LCIT Sign" registration you create in Entra | App registration → Overview → *Application (client) ID* |
| **Client secret** | The password of the *application* (not of a person). Shown **once**, at creation | App registration → Certificates & secrets → *New client secret* → copy the **Value** |

The two identifiers can be shared; **the secret must never be pasted in a chat, a ticket or Git**.

## Steps (by someone allowed to register applications in Entra)

1. **Entra admin center → Applications → App registrations → New registration**: name `LCIT Sign`, *accounts in this
   organizational directory only*, redirect URI of type **Web**: `<public URL>/api/auth/callback`
   (Microsoft accepts plain HTTP only for `localhost`).
2. Note the **Application (client) ID** and the **Directory (tenant) ID**.
3. **Certificates & secrets → New client secret** (short lifetime). Copy the *Value*.
4. **API permissions**: keep only Microsoft Graph *delegated* `openid`, `profile`, `email`. Add **no** application permission.
5. (Recommended) **Enterprise applications → LCIT Sign → Properties → Assignment required: Yes**, then add only the
   users who may sign in.
6. (Optional) **Token configuration → Add optional claim → ID → `email`**.

## In LCIT Sign

Easiest: *Administration → Identités & accès → Connexion → Microsoft (Entra ID)*, enter the tenant ID, client ID and
secret, **Enregistrer**. The secret is stored encrypted and never shown again; saving makes Entra the active SSO.

Alternatively, with environment variables (they then override the UI): put the secret in a file outside Git
(`install -m 600 /dev/stdin secrets/oidc_client_secret`) and in `.env`:

```text
LCIT_SIGN_OIDC_ISSUER=https://login.microsoftonline.com/<TENANT-ID>/v2.0
LCIT_SIGN_OIDC_CLIENT_ID=<APPLICATION-ID>
LCIT_SIGN_OIDC_CLIENT_SECRET_FILE=/run/secrets/lcit-sign/oidc_client_secret
LCIT_SIGN_PUBLIC_BASE_URL=<public URL>
```

then `docker compose up -d --force-recreate api webui`.

## What happens, and what does not

- On first sign-in LCIT Sign creates a profile with the name and e-mail (no password). Every new active account is a
  **SIGNER**; administrators are designated by an administrator (or `LCIT_SIGN_BOOTSTRAP_ADMIN` on a first install).
- Sign-in does not read the directory: LCIT Sign only knows people who signed in at least once.
- *Administration → Identités & accès → Annuaire → Microsoft Entra ID* is **another thing**: it *imports* users and groups,
  with another app registration and directory read permissions an administrator must consent to.

## Rolling back

Deleting the secret or the application in Entra cuts access at once.
