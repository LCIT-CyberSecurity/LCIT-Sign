#!/usr/bin/env bash
# Restore a backup made by ops/admin/backup.sh into THIS stack. Destructive: it replaces the
# database and the storage volume. The master key in use must be the one the data was created
# with.
#
#   ops/admin/restore.sh backups/lcit-sign-backup-20261005T120000Z.tar.bz2 [--yes]
#
# Without --yes it asks you to type RESTORE. The checksums are always verified first.
# Other stack: LCIT_SIGN_PROJECT (Compose project, default lcit-sign), LCIT_SIGN_DATA_VOLUME
# (default lcit-sign-data), LCIT_SIGN_DB_NAME (default lcit_sign).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

ARCHIVE="${1:?usage: restore.sh <lcit-sign-backup-*.tar.bz2> [--yes]}"
ASSUME_YES="no"
[[ "${2:-}" == "--yes" ]] && ASSUME_YES="yes"
PROJECT="${LCIT_SIGN_PROJECT:-lcit-sign}"
DATA_VOLUME="${LCIT_SIGN_DATA_VOLUME:-lcit-sign-data}"
DB_NAME="${LCIT_SIGN_DB_NAME:-lcit_sign}"
EXPECTED=(db.dump data.tar SHA256SUMS MANIFEST.txt)

[[ -f "$ARCHIVE" ]] || { echo "No such backup: $ARCHIVE" >&2; exit 2; }
ARCHIVE="$(cd "$(dirname "$ARCHIVE")" && pwd)/$(basename "$ARCHIVE")"
command -v bzip2 >/dev/null || { echo "bzip2 is required to read the archive." >&2; exit 1; }

if [[ "$ASSUME_YES" != "yes" ]]; then
    echo "This REPLACES the database and the documents of the stack '$PROJECT' with $ARCHIVE."
    read -r -p "Type RESTORE to continue: " answer
    [[ "$answer" == "RESTORE" ]] || { echo "Cancelled, nothing was changed."; exit 2; }
fi

umask 077
WORK="$(mktemp -d)"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

echo "==> Reading the archive"
members="$(tar -tjf "$ARCHIVE" | sort | tr '\n' ' ')"
wanted="$(printf '%s\n' "${EXPECTED[@]}" | sort | tr '\n' ' ')"
[[ "$members" == "$wanted" ]] \
    || { echo "Unexpected archive content: $members(expected: $wanted)" >&2; exit 1; }
tar -xjf "$ARCHIVE" -C "$WORK"
for f in "${EXPECTED[@]}"; do
    [[ -f "$WORK/$f" ]] || { echo "Missing in the archive: $f" >&2; exit 1; }
done

echo "==> Verifying checksums"
if ! grep -q ' db.dump$' "$WORK/SHA256SUMS" || ! grep -q ' data.tar$' "$WORK/SHA256SUMS"; then
    echo "SHA256SUMS does not cover db.dump and data.tar" >&2
    exit 1
fi
( cd "$WORK" && sha256sum -c SHA256SUMS )

COMPOSE=(docker compose -p "$PROJECT")

echo "==> Stopping the API"
"${COMPOSE[@]}" stop api

echo "==> Restoring PostgreSQL"
"${COMPOSE[@]}" exec -T postgres pg_restore -U lcit_sign -d "$DB_NAME" \
    --clean --if-exists --no-owner <"$WORK/db.dump"

echo "==> Restoring the storage volume ($DATA_VOLUME)"
docker run --rm -i -v "$DATA_VOLUME":/data alpine \
    sh -c 'find /data -mindepth 1 -delete && tar -C /data -xf -' <"$WORK/data.tar"

echo "==> Starting the API"
"${COMPOSE[@]}" up -d api

echo "==> Health check"
healthy="no"
for _ in $(seq 1 30); do
    if "${COMPOSE[@]}" exec -T api python -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)" \
        >/dev/null 2>&1; then healthy="yes"; break; fi
    sleep 3
done
[[ "$healthy" == "yes" ]] || { echo "The API did not become healthy after the restore." >&2; exit 1; }

echo "==> verify-all"
"${COMPOSE[@]}" exec -T api python -m lcit_sign.cli verify-all

echo "Restore complete."
