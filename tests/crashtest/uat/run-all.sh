#!/usr/bin/env bash
# CrashTests-Sign: smoke test, seed, restore test, against the running stack.
# Run on the machine hosting the Docker stack (the Integrations VM).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."

IMAGE="${LCIT_SIGN_API_IMAGE:-lcit-sign-api:latest}"
BASE="${LCIT_SIGN_BASE_URL:-http://localhost:4180}"
uat() {
    docker run --rm --network host -e LCIT_SIGN_BASE_URL="$BASE" \
        -e LCIT_SIGN_SMOKE_SMTP="${LCIT_SIGN_SMOKE_SMTP:-}" \
        -v "$PWD/tests/crashtest/uat":/uat:ro --entrypoint python "$IMAGE" "/uat/$1"
}

echo "##### smoke"; uat smoke.py
echo "##### smtp scenarios (needs the test Postfix)"; if docker inspect lcit-sign-postfix-test >/dev/null 2>&1; then tests/integration/run-smtp-scenarios.sh; else echo "SKIP: postfix-test is not running"; fi
echo "##### seed";  uat seed.py
echo "##### browser end-to-end (Playwright)"
docker run --rm --network host -v "$PWD":/src:ro -e LCIT_SIGN_E2E_BASE_URL="$BASE" \
    "mcr.microsoft.com/playwright:v$(sed -n 's/.*"@playwright\/test": "\^\{0,1\}\([0-9.]*\)".*/\1/p' frontend/package.json)-noble" \
    bash -c "cp -r /src/frontend /w && cp -r /src/tests/e2e /w/e2e && cd /w && npm ci --silent && npx playwright test"
echo "##### restore"; tests/crashtest/uat/restore-test.sh
echo; echo "CrashTests-Sign: all passed."
