#!/usr/bin/env bash
# Consistent LCIT Sign backup (spec §115): PostgreSQL + the storage volume, with checksums, in ONE
# verified archive. Run on the machine hosting the Docker stack.
#
#   ops/admin/backup.sh                  -> ./backups/lcit-sign-backup-<UTC timestamp>.tar.bz2
#   LCIT_SIGN_BACKUP_DIR=/safe/place ops/admin/backup.sh
#
# The archive holds, flat: db.dump (pg_dump -Fc), data.tar (the storage volume, raw),
# SHA256SUMS (of both) and MANIFEST.txt.
#
# NOT in the archive, by design: LCIT_SIGN_MASTER_KEY. It derives the signing
# keys and decrypts the stored connector credentials; back it up separately
# and securely (never next to this archive). Existing signatures stay
# verifiable without it (they need only the public keys, which are in the
# database); signing again and reading stored credentials need it.
#
# Other stack: LCIT_SIGN_PROJECT (Compose project, default lcit-sign), LCIT_SIGN_DATA_VOLUME
# (default lcit-sign-data) and LCIT_SIGN_DB_NAME (default lcit_sign; the CrashTest one is
# lcit_sign_crashtest).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

PROJECT="${LCIT_SIGN_PROJECT:-lcit-sign}"
OUT_ROOT="${LCIT_SIGN_BACKUP_DIR:-$PWD/backups}"
DATA_VOLUME="${LCIT_SIGN_DATA_VOLUME:-lcit-sign-data}"
DB_NAME="${LCIT_SIGN_DB_NAME:-lcit_sign}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="$OUT_ROOT/lcit-sign-backup-$TIMESTAMP.tar.bz2"

command -v bzip2 >/dev/null || { echo "bzip2 is required to write the archive." >&2; exit 1; }

umask 077   # the archive holds documents and encrypted credentials
mkdir -p "$OUT_ROOT"
WORK="$(mktemp -d "$OUT_ROOT/.lcit-sign-backup.XXXXXX")"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

echo "==> PostgreSQL dump"
docker compose -p "$PROJECT" exec -T postgres pg_dump -U lcit_sign -Fc "$DB_NAME" >"$WORK/db.dump"

echo "==> Storage volume ($DATA_VOLUME)"
docker run --rm -v "$DATA_VOLUME":/data:ro alpine tar -C /data -cf - . >"$WORK/data.tar"

GIT_REF="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
( cd "$WORK" && sha256sum db.dump data.tar >SHA256SUMS )
cat >"$WORK/MANIFEST.txt" <<MANIFEST
LCIT Sign backup
created_utc: $TIMESTAMP
git: $GIT_REF
format: tar.bz2 archive; db.dump = pg_dump -Fc; data.tar = raw archive of the storage volume
contents: db.dump, data.tar, SHA256SUMS, MANIFEST.txt
excluded: LCIT_SIGN_MASTER_KEY (back it up separately and securely, never next to this archive)
MANIFEST

echo "==> Archive"
tar -cjf "$WORK/archive.tmp" -C "$WORK" db.dump data.tar SHA256SUMS MANIFEST.txt
mv "$WORK/archive.tmp" "$ARCHIVE"

echo "Backup written to $ARCHIVE"
echo "Reminder: the master key is not included — keep it somewhere else."
