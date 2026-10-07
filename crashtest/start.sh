#!/usr/bin/env bash
# Start the CrashTest stack and load its dataset: a separate Docker project (own containers, own
# PostgreSQL, own volumes), the mock SSO, fictional accounts. Run it from anywhere.
#
#   ./crashtest/start.sh
#
# Needs Docker. See crashtest/README.md for the accounts and for putting it on another port.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ENV_FILE=crashtest/crashtest.env
# Defaults from the env file, only for what the caller did not set.
while IFS='=' read -r key value; do
    [[ "$key" =~ ^LCIT_SIGN_[A-Z_]+$ ]] || continue
    [ -n "${!key+x}" ] || export "$key=$value"
done < "$ENV_FILE"

# A normal installation is the project "lcit-sign": CrashTest must never share its name, so never
# its containers, networks or volumes.
if [ "$LCIT_SIGN_PREFIX" = "lcit-sign" ] || [ -z "$LCIT_SIGN_PREFIX" ]; then
    echo "Refusé : LCIT_SIGN_PREFIX ne peut pas être « lcit-sign » (c'est une installation normale)." >&2
    exit 1
fi

COMPOSE=(docker compose -p "$LCIT_SIGN_PREFIX" --env-file "$ENV_FILE"
         -f docker-compose.yml -f crashtest/docker-compose.crashtest.yml --profile crashtest)

echo "== CrashTest « $LCIT_SIGN_PREFIX » : démarrage de la pile"
"${COMPOSE[@]}" up -d --build --wait

echo "== Jeu de données (comptes fictifs, campagnes)"
"${COMPOSE[@]}" exec -T api python /crashtest/seed.py

echo
echo "LCIT Sign CrashTest est prêt : $LCIT_SIGN_PUBLIC_BASE_URL"
echo "  (réinitialiser : ./crashtest/reset.sh — ne touche qu'au projet « $LCIT_SIGN_PREFIX »)"
