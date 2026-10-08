#!/usr/bin/env bash
# Consistent LCIT Sign backup (spec §115): PostgreSQL + the storage volume,
# with checksums. Run on the machine hosting the Docker stack.
#
#   scripts/backup.sh                  -> ./backups/lcit-sign-<UTC timestamp>/
#   LCIT_SIGN_BACKUP_DIR=/safe/place scripts/backup.sh
#
# NOT in the archive, by design: LCIT_SIGN_MASTER_KEY. It derives the signing
# keys and decrypts the stored connector credentials; back it up separately
# and securely (never next to this archive). Existing signatures stay
# verifiable without it (they need only the public keys, which are in the
# database); signing again and reading stored credentials need it.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

OUT_ROOT="${LCIT_SIGN_BACKUP_DIR:-$PWD/backups}"
DATA_VOLUME="${LCIT_SIGN_DATA_VOLUME:-lcit-sign-data}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$OUT_ROOT/lcit-sign-$TIMESTAMP"

umask 077   # the archive holds documents and encrypted credentials
mkdir -p "$DEST"

echo "==> PostgreSQL dump"
docker compose exec -T postgres pg_dump -U lcit_sign -Fc lcit_sign >"$DEST/db.dump"

echo "==> Storage volume ($DATA_VOLUME)"
docker run --rm -v "$DATA_VOLUME":/data:ro -v "$DEST":/out alpine \
    tar -C /data -cf /out/data.tar .

( cd "$DEST" && sha256sum db.dump data.tar >SHA256SUMS )
cat >"$DEST/MANIFEST.txt" <<MANIFEST
LCIT Sign backup
created_utc: $TIMESTAMP
contents: db.dump (pg_dump -Fc), data.tar (storage volume), SHA256SUMS
excluded: LCIT_SIGN_MASTER_KEY (back it up separately)
MANIFEST

echo "Backup written to $DEST"
echo "Reminder: the master key is not included — keep it somewhere else."
