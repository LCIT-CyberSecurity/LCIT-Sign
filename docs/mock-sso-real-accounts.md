# Real accounts behind the mock SSO (Entra, Google, LDAP)

For the demo and test environment only. The mock sign-in page (`/mock-oidc`) keeps its fictional
identities and can also offer **your real accounts**, so you can sign in as yourself and sign a
real document. LCIT Sign does not change: it still talks to one OpenID Connect provider and never
sees a password.

- **Entra ID** and **Google**: the person is sent to Microsoft's or Google's own login page. If
  they are already signed in there (single sign-on), they do not type anything.
- **LDAP**: a login and password are asked **on the mock page**, checked against the directory
  and forgotten. LCIT Sign never receives them.

Nothing is offered until a providers file exists, and the file is **never in Git**.

## 1. The providers file

Create `secrets/mock-oidc-providers.json` (mode 600, next to the other secrets) with only the
providers you want:

```json
{
  "entra":  {"tenant_id": "<ID du tenant>", "client_id": "<ID de l'application (client)>",
             "client_secret": "<valeur du secret>"},
  "google": {"client_id": "<id>.apps.googleusercontent.com", "client_secret": "<secret>",
             "allowed_domain": "votre-domaine.fr"},
  "ldap":   {"server_url": "ldaps://ldap.entreprise.fr:636", "bind_dn": "cn=lcit-sign,ou=services,dc=entreprise,dc=fr",
             "bind_password": "<mot de passe>", "base_dn": "dc=entreprise,dc=fr",
             "user_filter": "(&(objectClass=person)(|(mail={login})(uid={login})(sAMAccountName={login})))"}
}
```

Then put your user id in `.env` so the mock can read the private folder, and restart it:

```bash
echo "MOCK_OIDC_UID=$(id -u)" >> .env
docker compose --profile crashtest up -d --build mock-oidc
docker compose up -d --force-recreate webui
```

## 2. What to allow on the provider side

The sign-in comes back to `<LCIT_SIGN_PUBLIC_BASE_URL>/mock-oidc/callback/<provider>`.

**Entra** — in the application you already registered (Entra → Inscriptions d'applications → votre
application → Authentification → Ajouter une plateforme → Web), add the redirect URI

    https://192.168.1.5:4443/mock-oidc/callback/entra

Nothing else changes: `openid`, `profile` and `email` need no administrator consent, and no
permission is added. People sign in with their own account; no account is created in Entra.

**Google** — Google Cloud → APIs et services → Identifiants → Créer des identifiants → ID client
OAuth (application Web), with the redirect URI `…/mock-oidc/callback/google`. `allowed_domain`
restricts sign-in to your domain.

**LDAP** — a read-only service account that can search people under `base_dn`. Use `ldaps://`; the
certificate is checked (add `"insecure_skip_verify": "true"` only for a lab server with a
self-signed certificate).

## 3. How a person is recognised

LCIT Sign matches a sign-in to a person by **e-mail address**. Someone already imported from the
directory (Annuaire → Synchroniser) keeps their roles when they sign in with the same address;
otherwise a new account is created as a signer. An administrator grants more roles in
Utilisateurs.

## Safety rules built in

- Codes are only sent to the app itself (`MOCK_OIDC_ALLOWED_REDIRECTS`, set by `docker-compose.yml`).
  Without that list, real accounts are refused: a crafted link could otherwise hand someone else
  the code of a person who just signed in.
- LDAP: an empty password is refused (it would be an anonymous bind), the search text is escaped,
  an unknown login and a wrong password get the same answer, and attempts are limited
  (5 per 5 minutes per caller).
- The provider's answer is used once, within 10 minutes, and only if it is addressed to this
  application with the right nonce.
- Secrets stay in the file; they are never shown on a page.
