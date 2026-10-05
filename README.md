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
docker compose up -d --build
```

- Frontend : http://127.0.0.1:4180
- API : proxyée par nginx sous `/api`, healthcheck sur `/api/health`

## Développement

```bash
# backend
pip install -e '.[dev]'
ruff check .
mypy src
pytest --cov

# frontend
cd web
npm install
npm run dev
npm test
```

## État du projet

Phases 0 à 7 livrées, plus l'interface complète par rôle (signataire, opérateur,
administrateur) : SSO OIDC, documents versionnés, signature avec preuve
(SHA-256 + Ed25519), campagnes ciblées par groupe, notifications e-mail,
annuaire (local, Microsoft Entra ID, Google Workspace) et procès-verbaux
signés.

Les identifiants des connecteurs d'annuaire et le mot de passe SMTP sont saisis
par un administrateur dans l'interface et stockés chiffrés (AES-256-GCM) en
base, jamais dans `.env`. Seule `LCIT_SIGN_MASTER_KEY` reste côté environnement ;
elle peut être fournie par fichier (`LCIT_SIGN_MASTER_KEY_FILE`).

Conception détaillée : [`docs/design.md`](docs/design.md).

Hors périmètre du MVP : signature eIDAS, horodatage qualifié, PKI utilisateur,
clé privée par collaborateur, signature biométrique, éditeur PDF type DocuSign,
stockage S3/MinIO, compte utilisateur local avec mot de passe.
