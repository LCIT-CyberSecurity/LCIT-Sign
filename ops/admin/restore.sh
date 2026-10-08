#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh into THIS stack. Destructive:
# it replaces the database and the storage volume. The master key in use
# must be the one the data was created with.
#
#   scripts/restore.sh backups/lcit-sign-20261005T120000Z --yes
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

SRC="${1:?usage: restore.sh <backup-dir> --yes}"
[[ "${2:-}" == "--yes" ]] || { echo "Refusing without --yes (this replaces all data)."; exit 2; }
DATA_VOLUME="${LCIT_SIGN_DATA_VOLUME:-lcit-sign-data}"
SRC="$(cd "$SRC" && pwd)"

echo "==> Verifying checksums"
( cd "$SRC" && sha256sum -c SHA256SUMS )

echo "==> Stopping the API"
docker compose stop api

echo "==> Restoring PostgreSQL"
docker compose exec -T postgres pg_restore -U lcit_sign -d lcit_sign \
    --clean --if-exists --no-owner <"$SRC/db.dump"

echo "==> Restoring the storage volume ($DATA_VOLUME)"
docker run --rm -v "$DATA_VOLUME":/data -v "$SRC":/in:ro alpine \
    sh -c 'find /data -mindepth 1 -delete && tar -C /data -xf /in/data.tar'

echo "==> Starting the API"
docker compose up -d api

echo "Restore complete. Verify with:"
echo "  docker compose exec api python -m lcit_sign.cli verify-all"
