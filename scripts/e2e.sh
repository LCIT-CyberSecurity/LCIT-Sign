#!/usr/bin/env bash
# End-to-end tests in a real browser, on a throwaway copy of the stack: its own containers, ports
# and volumes (prefix "lcit-e2e"), the CrashTests dataset, the mock SSO. The real stack (and its
# data) is never touched, and everything is removed at the end.
#
#   scripts/e2e.sh                       # all tests
#   scripts/e2e.sh -g "drag and drop"    # the ones matching, any Playwright argument
#
# Needs Docker. Run on the Integrations VM with scripts/integration-run.sh, not on a dev machine.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

COMPOSE=(docker compose -p lcit-e2e --env-file docker/e2e.env --profile dev-sso)
BASE_URL="http://127.0.0.1:14180"

cleanup() { "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

echo "== starting the throwaway stack"
"${COMPOSE[@]}" up -d --build --wait

echo "== loading the CrashTests dataset"
LCIT_SIGN_BASE_URL="$BASE_URL" LCIT_SIGN_API_IMAGE="lcit-e2e-api:latest" scripts/integration-seed.sh

echo "== running the browser tests"
docker run --rm --network host -v "$PWD/web":/src:ro \
    -e LCIT_SIGN_E2E_BASE_URL="$BASE_URL" \
    mcr.microsoft.com/playwright:v1.63.0-noble \
    bash -c 'cp -r /src /w && cd /w && npm ci --silent && npx playwright test "$@"' _ "$@"
