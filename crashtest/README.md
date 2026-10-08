# CrashTest

A **separate stack** to test and demo LCIT Sign: its own Docker project, its own PostgreSQL database
(`lcit_sign_crashtest`), its own volumes, the **mock SSO** and fictional accounts. It never touches a normal
installation, which has none of this: CrashTest is the **only** environment with the fictional directory, Alice,
Bob and the other fictional people, their groups and campaigns, and the mock SSO.

```bash
./crashtest/start.sh    # starts, applies migrations, loads the dataset, prints the accounts
./crashtest/reset.sh    # destroys ONLY this project's containers and volumes, then starts again
```

Docker is the only requirement.

## Accounts

The identifier is the e-mail address, the **password is the first name in lowercase**.

| Person | E-mail | Password | Role |
|---|---|---|---|
| Alice Martin | alice.martin@lcit-test.local | alice | SIGNER (HR) |
| Sophie Bernard | sophie.bernard@lcit-test.local | sophie | SIGNER (HR, preparer of Alice's campaign) |
| Claire Moreau | claire.moreau@lcit-test.local | claire | SIGNER (Legal) |
| Diane Leroy | diane.leroy@lcit-test.local | diane | SIGNER (Sales, security campaigns) |
| Paul Muller | paul.muller@lcit-test.local | paul | SIGNER + OPERATOR |
| Admin Crash | admin.crash@lcit-test.local | admin | SIGNER + ADMIN |
| Bob Dupont | bob.dupont@lcit-test.local | bob | SIGNER |
| Charlie Durand, Manon Faure, Nicolas Blanc, Olivia Henry, Erwan Petit, Fatima Benali… | first.last@lcit-test.local | first name | SIGNER (24 people in all) |

The local system account is still `admin` / `SecretPassword` (change it at first sign-in). These passwords are
deliberately simple: the accounts are fictional and exist only in this stack. Only the hash is stored.

The **mock SSO** is CrashTest's only entry point: "Continuer avec le SSO" leads to the mock, which offers the same
people in one click **and**, if you imported your configuration, the real Entra.

## Starting clean, with your real Entra

```bash
git clone … && cd LCIT-Sign
# 1. once, from a stack where Entra is configured (Administration > Identités & accès):
./scripts/connections.sh export --crashtest      # -> ~/.config/lcit-sign/connections.json (encrypted secrets, outside Git)
# 2. every time you start from scratch, with the SAME master key as the export (LCIT_SIGN_MASTER_KEY):
./crashtest/reset.sh      # build, migrations, dataset, import of connections.json, mock SSO + Entra
```

`start.sh` imports `connections.json`, then builds `~/.config/lcit-sign/mock-sso/mock-oidc-providers.json` (mode 600,
outside Git, never printed) from the Entra/Google sign-in provider or, failing that, the Entra directory application:
the mock reads this file to offer "Se connecter avec Microsoft Entra ID". On Microsoft's side the redirect URI
`<public URL>/mock-oidc/callback/entra` must be declared in the application.

## The data

- **Entretiens RH 2027**: owner Alice, preparer Sophie, to be signed by Bob and Manon.
- **NDA Juridique**: owner Claire, to be signed by Charlie.
- **Campagne sécurité 2026**: the CISO (Erwan) and one other person have signed, the rest are asked.
- **Politique mots de passe 2026**: recipients wait for the CISO's signature.

To test rights: Alice sees the HR campaign, not the Legal one; Paul (operator) sees everything but not the confidential
content unless he adds himself as preparer; Bob only sees what he is asked to sign.

## Safeguards

- The dataset loads only if `LCIT_SIGN_CRASHTEST=true` (set only by `docker-compose.crashtest.yml`) **and** the database
  name ends with `_crashtest`, and never in `production`.
- The scripts refuse the project name `lcit-sign` (a normal installation's).
- The normal `docker-compose.yml` has no SSO, no bootstrap administrator and no fictional person.

## Another instance (other port, other name)

```bash
LCIT_SIGN_PREFIX=lcit-sign-feature LCIT_SIGN_HTTPS_PORT=4444 LCIT_SIGN_HTTPS_BIND=0.0.0.0 \
LCIT_SIGN_PUBLIC_BASE_URL=https://192.168.1.5:4444 LCIT_SIGN_COOKIE_SECURE=true \
LCIT_SIGN_FQDN=192.168.1.5 ./crashtest/start.sh
```

The prefix names the project, containers, networks and volumes, so there is no collision with another instance. The
end-to-end tests (`scripts/e2e.sh`) use the same stack with the prefix `lcit-e2e`.
