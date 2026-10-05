#!/usr/bin/env bash
# Reset the LCIT Sign stack on THIS machine to an empty, freshly migrated
# state, then (optionally) seed the CrashTests dataset. DESTRUCTIVE — meant
# for the Integrations VM only (spec §92-93). Other projects' containers and
# volumes are untouched: only the `lcit-sign` compose project is affected.
#
#   scripts/integration-reset.sh --yes [--seed]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

[[ " $* " == *" --yes "* ]] || { echo "Refusing without --yes: this deletes all LCIT Sign data."; exit 2; }

echo "==> Removing the lcit-sign stack and its volumes"
docker compose down --volumes --remove-orphans
echo "==> Rebuilding and starting"
docker compose up -d --build
for _ in $(seq 1 60); do
    [[ "$(docker inspect -f '{{.State.Health.Status}}' lcit-sign-webui 2>/dev/null)" == healthy ]] \
        && [[ "$(docker inspect -f '{{.State.Health.Status}}' lcit-sign-api 2>/dev/null)" == healthy ]] \
        && break
    sleep 2
done
docker compose ps

if [[ " $* " == *" --seed "* ]]; then
    scripts/integration-seed.sh
fi
