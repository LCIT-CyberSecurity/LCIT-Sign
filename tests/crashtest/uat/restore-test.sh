#!/usr/bin/env bash
# CrashTest: backup -> blank installation -> restore DB + files -> every old
# signature must still verify (spec §116).
#
# Never touches the live stack's data: the restore goes into a throwaway
# PostgreSQL container and a throwaway volume, on a private network.
# It also proves the check has teeth by corrupting a restored file and
# expecting verification to fail.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."

RUN_ID="$(date +%s)"
NET="lcit-restore-net-$RUN_ID"
PG="lcit-restore-pg-$RUN_ID"
VOL="lcit-restore-data-$RUN_ID"
PG_PASSWORD="$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
BACKUP_ROOT="$(mktemp -d)"
IMAGE="${LCIT_SIGN_API_IMAGE:-lcit-sign-api:latest}"

cleanup() {
    docker rm -f "$PG" >/dev/null 2>&1 || true
    docker volume rm "$VOL" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
    docker run --rm -v "$BACKUP_ROOT":/b alpine rm -rf /b/lcit-sign-backup-* /b/unpacked >/dev/null 2>&1 || true
    rmdir "$BACKUP_ROOT" 2>/dev/null || true
}
trap cleanup EXIT

step() { printf '\n==> %s\n' "$*"; }

step "1. Backup of the live stack"
LCIT_SIGN_BACKUP_DIR="$BACKUP_ROOT" ops/admin/backup.sh >/dev/null
ARCHIVE="$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -name 'lcit-sign-backup-*.tar.bz2' | head -1)"
[[ -n "$ARCHIVE" ]] || { echo "FAIL: no archive was written"; exit 1; }
BACKUP="$BACKUP_ROOT/unpacked"; mkdir -p "$BACKUP"
tar -xjf "$ARCHIVE" -C "$BACKUP"
( cd "$BACKUP" && sha256sum -c SHA256SUMS >/dev/null ) && echo "archive extracted, checksums OK"

LIVE_SIGNATURES="$(docker compose -p "${LCIT_SIGN_PROJECT:-lcit-sign}" exec -T postgres psql -U lcit_sign -d "${LCIT_SIGN_DB_NAME:-lcit_sign}" -Atc \
    'select count(*) from signatures')"
echo "live signatures: $LIVE_SIGNATURES"
[[ "$LIVE_SIGNATURES" -gt 0 ]] || { echo "No signature to test: run the seed first."; exit 2; }

step "2. Blank installation (private network, new database, new volume)"
docker network create "$NET" >/dev/null
docker volume create "$VOL" >/dev/null
docker run -d --name "$PG" --network "$NET" \
    -e POSTGRES_USER=lcit_sign -e POSTGRES_PASSWORD="$PG_PASSWORD" -e POSTGRES_DB=lcit_sign \
    postgres:16-alpine >/dev/null
# The image first runs a temporary server (unix socket only) to initialise the
# database, stops it, then starts the real one. Wait on TCP, which only the
# real server answers, so we never restore into the one that is shutting down.
READY=0
for _ in $(seq 1 60); do
    if docker exec "$PG" pg_isready -h 127.0.0.1 -U lcit_sign >/dev/null 2>&1; then READY=1; break; fi
    sleep 1
done
[[ "$READY" -eq 1 ]] || { echo "FAIL: the throwaway PostgreSQL did not start"; exit 1; }

step "3. Restore the database and the files"
docker exec -i "$PG" pg_restore -U lcit_sign -d lcit_sign --no-owner <"$BACKUP/db.dump"
docker run --rm -v "$VOL":/data -v "$BACKUP":/in:ro alpine tar -C /data -xf /in/data.tar
# The API image runs as an unprivileged user; hand it the restored files.
docker run --rm --entrypoint sh "$IMAGE" -c 'id -u' >/tmp/lcit-uid.$$ 2>/dev/null || true
API_UID="$(cat /tmp/lcit-uid.$$ 2>/dev/null || echo 0)"; rm -f /tmp/lcit-uid.$$
docker run --rm -v "$VOL":/data alpine chown -R "$API_UID" /data

verify() {
    docker run --rm --network "$NET" \
        -e LCIT_SIGN_DATABASE_URL="postgresql+psycopg://lcit_sign:${PG_PASSWORD}@${PG}:5432/lcit_sign" \
        -e LCIT_SIGN_STORAGE_ROOT=/var/lib/lcit-sign \
        -v "$VOL":/var/lib/lcit-sign \
        --entrypoint python "$IMAGE" -m lcit_sign.cli verify-all
}

step "4. Every old signature must verify"
OUT="$(verify)" && RC=0 || RC=$?
echo "$OUT" | sed -n '1,12p'
[[ $RC -eq 0 ]] || { echo "FAIL: restored data does not verify"; exit 1; }
RESTORED="$(echo "$OUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["signatures"])' 2>/dev/null \
    || echo "$OUT" | grep -o '"signatures": [0-9]*' | grep -o '[0-9]*$')"
[[ "$RESTORED" == "$LIVE_SIGNATURES" ]] || {
    echo "FAIL: restored $RESTORED signatures, live has $LIVE_SIGNATURES"; exit 1; }
echo "PASS: $RESTORED/$LIVE_SIGNATURES signatures verify after restore"

step "5. The check has teeth: corrupt one restored signed PDF"
docker run --rm -v "$VOL":/data alpine sh -c \
    'f=$(find /data/signed -name "*.pdf" | head -1); echo corrupted >> "$f"'
if verify >/dev/null 2>&1; then
    echo "FAIL: corruption went undetected"; exit 1
fi
echo "PASS: corruption detected"
echo
echo "Restore CrashTest passed."
