# LCIT Sign

**Faites signer vos documents en quelques clics — avec une preuve que personne ne peut contester.**

LCIT Sign est l'application interne de signature et d'attestation de prise de connaissance
(charte informatique, PSSI, règlement intérieur, avenants, procédures…). Elle remplace les
relances par e-mail et les tableaux de suivi : on dépose un document, on dit qui signe et dans quel
ordre, on place les éléments sur la page, on envoie. Chacun signe depuis son poste, avec son compte
d'entreprise.

## Pourquoi LCIT Sign

- **Aucun mot de passe de plus.** Connexion unique avec le compte de l'entreprise (SSO OpenID
  Connect : Microsoft Entra ID, Google, LDAP/Active Directory…). Personne ne crée de compte.
- **Un parcours qui se comprend sans formation.** « Faire signer » se fait en cinq écrans :
  signataires, documents, préparation, vérification, documents signés.
- **Une preuve solide, vérifiable à tout moment.** Chaque signature fige l'identité du signataire,
  son consentement, l'empreinte du document (SHA-256) et la date, puis les scelle avec une clé de
  signature (Ed25519). Le document signé, la preuve et le certificat se téléchargent en un clic.
- **Du sur-mesure sans effort.** Placez la signature, la date, le nom, l'e-mail, le logo ou un
  champ à remplir à l'endroit voulu, comme sur les outils du marché, directement dans le navigateur.
- **Plusieurs signataires, dans l'ordre.** Le RSSI signe d'abord, puis chaque collaborateur reçoit
  sa copie qui porte déjà la signature précédente. Un publipostage pour toute une équipe.
- **Un suivi sans tableur.** Qui a signé, qui doit encore signer, relances en un clic ou
  automatiques, renouvellement périodique, procès-verbal signé de la campagne.
- **Les personnes extérieures aussi.** Ajoutez un prestataire par son adresse e-mail : il est
  indiqué comme externe et n'est jamais touché par une synchronisation d'annuaire.
- **Vos annuaires, vos messageries.** Équipes lues depuis Entra ID, Google Workspace ou LDAP ;
  e-mails envoyés par SMTP, Microsoft Graph ou Gmail. Les identifiants sont saisis dans l'interface
  et chiffrés (AES-256-GCM), jamais dans un fichier de configuration.
- **Word et LibreOffice acceptés.** Les documents Office sont convertis en PDF dans un conteneur
  isolé (sans réseau, sans accès à vos données).

## En un coup d'œil

| Pour… | On fait… |
|---|---|
| Signer ce qu'on m'a demandé | **Mes signatures** : à signer, à venir, signés — un clic pour ouvrir ou télécharger le PDF signé |
| Faire signer un document | **Faire signer** : 1 signataires et planning · 2 documents · 3 préparer · 4 vérifier et envoyer · 5 documents signés |
| Suivre, relancer, récupérer | **Suivi** : campagnes, documents signés (export ZIP), relances, ajout de personnes ou de documents en cours de route |
| Gérer la plateforme | **Administration** : utilisateurs et rôles, logo, identités & accès (un SSO, un annuaire, connexion locale), e-mail, clés de signature, audit, diagnostic |

Le guide complet est dans [`docs/guide-utilisateur.md`](docs/guide-utilisateur.md).

## Sécurité en bref

- SSO uniquement ; les sessions ne stockent que l'empreinte du jeton (une base volée ne rejoue pas
  une session).
- Documents versionnés et **immuables** une fois publiés ; PDF avec JavaScript refusés ; fichiers
  Office convertis en isolation.
- Aucune clé privée en base ni sur disque : les clés de signature sont dérivées de la clé maître au
  moment d'utiliser. Une signature est **refusée** si la clé maître ne correspond plus à la clé
  enregistrée.
- Journal d'audit chaîné, sauvegarde et test de restauration, HTTPS avec installateur de
  certificat, limitation de débit, en-têtes de sécurité.
- Public par conception : le dépôt ne contient **aucun secret**.

> **Niveau de signature.** La signature de LCIT Sign est une signature électronique *simple* au sens
> d'eIDAS, adossée à une preuve technique robuste. Ce n'est ni une signature avancée ni qualifiée ;
> pour un contrat à fort enjeu, il faudra un prestataire qualifié.

## Stack

- Backend : Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL
- Frontend : Vite, React, Lucide React, CSS maison
- Déploiement : Docker Compose (dev, intégration), Kubernetes (manifestes fournis)
- Reverse proxy : nginx (HTTPS, en-têtes de sécurité, BFF)

## Démarrage

```bash
cp .env.example .env
# éditer .env (au minimum LCIT_SIGN_DB_PASSWORD)
mkdir -p -m 700 certs        # avant le premier `up` (sinon Docker le crée en root)
docker compose up -d --build
```

- Interface : http://127.0.0.1:4180 (dev) et https://127.0.0.1:4443 (certificat auto-signé tant qu'aucun n'est installé)
- API : proxyée par nginx sous `/api`, santé sur `/api/health`
- Certificat HTTPS : `scripts/certificate-installer.sh` · Sauvegarde / restauration : `scripts/backup.sh`, `scripts/restore.sh`
- **Premier accès** : un compte administrateur système local existe pour amorcer la plateforme (identifiant
  `admin`). Son mot de passe initial est `SecretPassword` ; il est **à changer dès la première connexion**
  (l'application le rappelle à chaque connexion, et la page Diagnostic le signale tant que ce n'est
  pas fait). Une installation neuve ne contient **que ce compte** : connexion locale seulement, aucun SSO,
  aucun annuaire, aucune personne, aucun groupe ni campagne fictifs. L'administrateur configure ensuite le
  SSO, l'annuaire et l'e-mail dans Administration (Identités & accès). En production
  (`LCIT_SIGN_ENVIRONMENT=production`), l'application refuse de démarrer avec une clé de session ou une clé
  maître vide ou de développement, ou un cookie non `Secure`.
- **Brancher le vrai SSO** : renseigner `LCIT_SIGN_OIDC_ISSUER`, `..._CLIENT_ID` et `..._CLIENT_SECRET` dans
  `.env` (Microsoft Entra ID, Google ou tout fournisseur OpenID Connect). La page de connexion affiche alors
  « Continuer avec Microsoft », « Continuer avec Google » ou « Continuer avec le SSO », et garde une
  « Connexion locale » discrète. Sans SSO, la connexion locale est la page de connexion.
- **Comptes locaux** : dans Administration → Utilisateurs, choisir « Compte local » pour créer une personne
  avec un mot de passe (obligatoire, haché, à changer à sa première connexion) au lieu du SSO.

### Rôles

| Rôle | Pour qui |
|---|---|
| **Signataire** | l'utilisateur standard, donné à tout compte actif : prépare, envoie, suit et signe ses propres demandes |
| **Préparateur de campagne** | droit ponctuel sur UNE campagne (collaboration), pas un rôle global |
| **Opérateur** | supervision globale ; pas d'accès automatique au contenu confidentiel |
| **Administrateur** | administration technique de LCIT Sign |

### Environnement CrashTest (tests et démonstration)

```bash
./crashtest/start.sh     # pile séparée : base, volumes, SSO de test, comptes et campagnes fictifs
./crashtest/reset.sh     # détruit uniquement les volumes CrashTest et recharge le jeu de données
```

CrashTest est le **seul** endroit où existent le Mock SSO, le faux annuaire, Alice, Bob et les autres personnes, groupes et campagnes fictifs (le compte `admin` / `SecretPassword` y existe aussi). Les comptes fictifs ont pour mot de passe leur
**prénom en minuscules** (`bob.dupont@lcit-test.local` / `bob`) et peuvent aussi se connecter en un clic par
le SSO de test. Le jeu de données refuse de se charger hors d'une pile CrashTest. Détails :
[`crashtest/README.md`](crashtest/README.md).

## Développement et tests

```bash
# backend
pip install -e '.[dev]'
ruff check . && mypy src && pytest

# frontend
cd web && npm ci && npm run dev
npm test && npm run build     # Vitest + React Testing Library, puis tsc -b + Vite

# de bout en bout, dans un vrai navigateur, sur une pile jetable (Docker requis)
scripts/e2e.sh
```

Les tests tournent dans des conteneurs Docker sur la VM d'intégration (rien à installer sur le
poste de développement) : voir `tests/UAT/CrashTests-Sign/README.md`.

## État du projet

Fonctionnel de bout en bout et utilisé en test réel : SSO, documents versionnés, éditeur
d'éléments, signatures successives avec preuve et vérification, campagnes (groupes, publipostage,
personnes extérieures, démarrage différé, relances, renouvellements), « tout signer en un clic »,
documents signés (téléchargement, export ZIP), procès-verbaux signés, audit chaîné, annuaires
(local, Entra ID, Google Workspace, LDAP), messageries (SMTP, Microsoft Graph, Gmail), logo
d'entreprise, diagnostics, HTTPS, sauvegarde/restauration, manifestes Kubernetes.

**Éprouvé sur un vrai tenant** : l'annuaire Entra ID et l'envoi par Microsoft Graph.
**Pas encore éprouvé en réel** : Google Workspace (annuaire et Gmail) et LDAP — testés contre des
simulations. Les écarts assumés et ce qui reste à faire sont dans [`docs/design.md`](docs/design.md) §18.

## Documentation

| Document | Pour qui |
|---|---|
| [`docs/guide-utilisateur.md`](docs/guide-utilisateur.md) | Signataires, opérateurs, administrateurs : utiliser LCIT Sign |
| [`docs/design.md`](docs/design.md) | Conception détaillée, modèle de sécurité, limites connues |
| [`docs/entra-sso-test.md`](docs/entra-sso-test.md) | Brancher Entra ID |
| [`docs/microsoft-graph-setup.md`](docs/microsoft-graph-setup.md) | Envoyer les e-mails avec Microsoft Graph |
| [`docs/mock-sso-real-accounts.md`](docs/mock-sso-real-accounts.md) | SSO de test avec de vrais comptes |

Hors périmètre : signature avancée ou qualifiée (eIDAS), horodatage qualifié, clé privée par
collaborateur, signature biométrique, stockage S3/MinIO.
