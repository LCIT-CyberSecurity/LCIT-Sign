# LCIT Sign

Application interne de signature et d'attestation de prise de connaissance de documents.

SSO uniquement (OpenID Connect), documents versionnés et immuables une fois publiés,
signature visuelle type DocuSign adossée à une preuve technique (SHA-256 + Ed25519),
sans eIDAS, sans PKI utilisateur, sans stockage S3/MinIO.

## Stack

- Backend : Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL
- Frontend : Vite, React, Lucide React, CSS custom
- Déploiement : Docker Compose (dev/intégration), Kubernetes (supporté)
- Reverse proxy : nginx (HTTPS, headers de sécurité, BFF)

Projet de référence pour l'architecture et le design : `Easy-Access-Review-Engine`.
LCIT Sign reste un projet autonome, sans dépendance runtime vers EARE.

## Démarrage local

```bash
cp .env.example .env
# éditer .env (au minimum LCIT_SIGN_DB_PASSWORD)
mkdir -p -m 700 certs        # avant le premier `up` (sinon Docker le crée en root)
docker compose up -d --build
```

- Frontend : http://127.0.0.1:4180 (dev) et https://127.0.0.1:4443 (certificat auto-signé tant qu'aucun n'est installé)
- API : proxyée par nginx sous `/api`, healthcheck sur `/api/health`
- Certificat HTTPS : `scripts/certificate-installer.sh`
- Sauvegarde / restauration : `scripts/backup.sh`, `scripts/restore.sh`

## Développement et tests

```bash
# backend
pip install -e '.[dev]'
ruff check . && mypy src && pytest --cov

# frontend
cd web && npm ci && npm run dev
npm test            # Vitest + React Testing Library
```

Les tests d'intégration et de bout en bout (smoke, SMTP/Postfix, Playwright,
restauration) tournent sur les environnements Docker de la VM Integrations :
voir `tests/UAT/CrashTests-Sign/README.md`.

## État du projet

MVP fonctionnel de bout en bout, validé sur l'environnement Docker de la VM
Integrations : SSO OIDC, documents versionnés et immuables, signature avec
preuve (SHA-256 + Ed25519) et vérification, campagnes ciblées (groupes, groupes
imbriqués, instantané des destinataires), relances et renouvellements
automatiques, notifications (SMTP, Microsoft Graph), annuaire (local, Entra ID,
Google Workspace, synchronisation planifiée), procès-verbaux signés, audit
chaîné, diagnostics, HTTPS avec installateur de certificat, sauvegarde et test
de restauration, manifestes Kubernetes, interface par rôle.

**Non éprouvé en conditions réelles** : les connecteurs Entra ID, Google et
Microsoft Graph n'ont été testés que contre des simulations HTTP, jamais contre
un vrai tenant (voir `docs/microsoft-graph-setup.md`). Les écarts assumés par
rapport à la spécification et ce qui reste à faire sont listés dans
`docs/design.md` §18.

Les identifiants des connecteurs d'annuaire et le mot de passe SMTP sont saisis
par un administrateur dans l'interface et stockés chiffrés (AES-256-GCM) en
base, jamais dans `.env`. Seule `LCIT_SIGN_MASTER_KEY` reste côté environnement ;
elle peut être fournie par fichier (`LCIT_SIGN_MASTER_KEY_FILE`).

Conception détaillée : [`docs/design.md`](docs/design.md).

Hors périmètre du MVP : signature eIDAS, horodatage qualifié, PKI utilisateur,
clé privée par collaborateur, signature biométrique, éditeur PDF type DocuSign,
stockage S3/MinIO, compte utilisateur local avec mot de passe.
