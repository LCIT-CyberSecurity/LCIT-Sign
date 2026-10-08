# CrashTest

Le **seul** environnement qui contient le faux annuaire, Alice, Bob et les autres personnes fictives, leurs groupes et campagnes, et le Mock SSO (une installation normale n'a rien de cela). Une **pile séparée** pour tester et démontrer LCIT Sign : son propre projet Docker, sa propre base
PostgreSQL (`lcit_sign_crashtest`), ses propres volumes, le **Mock SSO** et des comptes fictifs. Elle ne
touche jamais à une installation normale.

```bash
./crashtest/start.sh    # démarre, applique les migrations, charge le jeu de données, affiche les comptes
./crashtest/reset.sh    # détruit UNIQUEMENT les conteneurs et volumes de ce projet, puis recommence
```

Il faut Docker. Rien d'autre n'est à installer.

## Les comptes

L'identifiant est l'adresse e-mail, le **mot de passe est le prénom en minuscules**.

| Personne | E-mail | Mot de passe | Rôle |
|---|---|---|---|
| Alice Martin | alice.martin@lcit-test.local | alice | Signataire (RH) |
| Sophie Bernard | sophie.bernard@lcit-test.local | sophie | Signataire (RH, préparatrice de la campagne d'Alice) |
| Claire Moreau | claire.moreau@lcit-test.local | claire | Signataire (Juridique) |
| Diane Leroy | diane.leroy@lcit-test.local | diane | Signataire (Sales, campagnes sécurité) |
| Paul Muller | paul.muller@lcit-test.local | paul | Signataire + Opérateur (administrateur métier) |
| Admin Crash | admin.crash@lcit-test.local | admin | Signataire + Administrateur |
| Bob Dupont | bob.dupont@lcit-test.local | bob | Signataire |
| Charlie Durand, Manon Faure, Nicolas Blanc, Olivia Henry, Erwan Petit, Fatima Benali… | prenom.nom@lcit-test.local | prénom | Signataires (24 personnes au total) |

Le compte système local reste `admin` / `SecretPassword`. Ces mots de passe sont volontairement simples :
les comptes sont fictifs et n'existent que dans cette pile. En base, seul le hachage est stocké.

Le **SSO de test** (Mock SSO) reste l'unique entrée de CrashTest : « Continuer avec le SSO » mène au Mock, qui
propose les mêmes personnes en un clic **et**, si vous avez importé votre configuration, le vrai Entra.

## Partir d'une installation propre, avec votre vrai Entra

```bash
git clone … && cd LCIT-Sign
# 1. une fois, depuis une pile où Entra est configuré (Administration > Identités & accès) :
./scripts/connections.sh export --crashtest      # → ~/.config/lcit-sign/connections.json (secrets chiffrés, hors Git)
# 2. à chaque repartie de zéro, avec la MÊME clé maître que celle de l'export (LCIT_SIGN_MASTER_KEY) :
./crashtest/reset.sh      # build, migrations, jeu de données, import de connections.json, Mock SSO + Entra
```

`start.sh` importe `connections.json`, puis fabrique `~/.config/lcit-sign/mock-sso/mock-oidc-providers.json`
(mode 600, hors Git, jamais affiché) à partir du fournisseur de connexion Entra/Google ou, à défaut, de
l'application de l'annuaire Entra : c'est ce fichier que le Mock lit pour proposer « Se connecter avec
Microsoft Entra ID ». Côté Microsoft, l'URI de redirection `<URL publique>/mock-oidc/callback/entra` doit être
déclarée dans l'application.

## Les données

- **Entretiens RH 2027** : propriétaire Alice, préparatrice Sophie, à signer par Bob et Manon.
- **NDA Juridique** : propriétaire Claire, à signer par Charlie.
- **Campagne sécurité 2026** : le RSSI (Erwan) a signé, une personne a signé, les autres sont sollicités.
- **Politique mots de passe 2026** : les destinataires attendent la signature du RSSI.

Pour tester les droits : Alice voit la campagne RH, pas celle du Juridique ; Paul (opérateur) voit tout
mais pas le contenu confidentiel, sauf s'il s'ajoute comme préparateur ; Bob ne voit que ce qu'on lui
demande.

## Garde-fous

- Le jeu de données ne se charge que si `LCIT_SIGN_CRASHTEST=true` (posé uniquement par
  `docker-compose.crashtest.yml`) **et** si la base se termine par `_crashtest`, et jamais en `production`.
- Les scripts refusent le nom de projet `lcit-sign` (celui d'une installation normale).
- Le `docker-compose.yml` normal n'a ni SSO, ni administrateur d'amorçage, ni personne fictive.

## Une autre instance (autre port, autre nom)

```bash
LCIT_SIGN_PREFIX=lcit-sign-feature LCIT_SIGN_HTTPS_PORT=4444 LCIT_SIGN_HTTPS_BIND=0.0.0.0 \
LCIT_SIGN_PUBLIC_BASE_URL=https://192.168.1.5:4444 LCIT_SIGN_COOKIE_SECURE=true \
LCIT_SIGN_FQDN=192.168.1.5 ./crashtest/start.sh
```

Le préfixe donne le nom du projet, des conteneurs, des réseaux et des volumes : aucune collision avec une
autre instance. Les tests de bout en bout (`scripts/e2e.sh`) utilisent la même pile avec le préfixe
`lcit-e2e`.
