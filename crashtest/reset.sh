#!/usr/bin/env bash
# Destroy the CrashTest stack's own containers and volumes, then start it again with a fresh
# dataset. Only the project named by LCIT_SIGN_PREFIX is touched — never a normal installation.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ENV_FILE=crashtest/crashtest.env
while IFS='=' read -r key value; do
    [[ "$key" =~ ^LCIT_SIGN_[A-Z_]+$ ]] || continue
    [ -n "${!key+x}" ] || export "$key=$value"
done < "$ENV_FILE"

if [ "$LCIT_SIGN_PREFIX" = "lcit-sign" ] || [ -z "$LCIT_SIGN_PREFIX" ]; then
    echo "Refusé : LCIT_SIGN_PREFIX ne peut pas être « lcit-sign » (c'est une installation normale)." >&2
    exit 1
fi

echo "== Suppression de « $LCIT_SIGN_PREFIX » (conteneurs et volumes de CrashTest uniquement)"
docker compose -p "$LCIT_SIGN_PREFIX" --env-file "$ENV_FILE" \
    -f docker-compose.yml -f crashtest/docker-compose.crashtest.yml --profile crashtest \
    down -v --remove-orphans

exec ./crashtest/start.sh
