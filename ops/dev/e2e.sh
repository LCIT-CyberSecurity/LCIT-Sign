#!/usr/bin/env bash
# End-to-end tests in a real browser, on a throwaway CrashTest stack (tests/crashtest/): its own
# containers, ports and volumes (prefix "lcit-e2e"), the CrashTest dataset, the mock SSO. A real
# stack (and its data) is never touched, and everything is removed at the end.
#
#   ops/dev/e2e.sh                       # all tests
#   ops/dev/e2e.sh -g "drag and drop"    # the ones matching, any Playwright argument
#
# Needs Docker. Run on the Integrations VM with ops/dev/integration-run.sh, not on a dev machine.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

# This run's own names and ports first (ops/dev/e2e.env), then the CrashTest defaults for the rest.
for file in ops/dev/e2e.env tests/crashtest/crashtest.env; do
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^LCIT_SIGN_[A-Z_]+$ ]] || continue
        [ -n "${!key+x}" ] || export "$key=$value"
    done < "$file"
done
COMPOSE=(docker compose -p "$LCIT_SIGN_PREFIX" --env-file tests/crashtest/crashtest.env
         -f compose.yaml -f tests/crashtest/compose.crashtest.yaml --profile crashtest)
BASE_URL="http://127.0.0.1:${LCIT_SIGN_HTTP_PORT}"

cleanup() { "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

echo "== starting the throwaway stack"
"${COMPOSE[@]}" up -d --build --wait

echo "== loading the CrashTest dataset"
"${COMPOSE[@]}" exec -T api python /crashtest/seed.py | tail -4

echo "== running the browser tests"
docker run --rm --network host -v "$PWD":/src:ro \
    -e LCIT_SIGN_E2E_BASE_URL="$BASE_URL" \
    mcr.microsoft.com/playwright:v1.63.0-noble \
    bash -c 'cp -r /src/frontend /w && cp -r /src/tests/e2e /w/e2e && cd /w && npm ci --silent && npx playwright test "$@"' _ "$@"
