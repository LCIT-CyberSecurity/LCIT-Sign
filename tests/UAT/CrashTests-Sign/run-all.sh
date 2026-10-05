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
        -v "$PWD/tests/UAT/CrashTests-Sign":/uat:ro --entrypoint python "$IMAGE" "/uat/$1"
}

echo "##### smoke"; uat smoke.py
echo "##### smtp scenarios (needs the test Postfix)"; if docker inspect lcit-sign-postfix-test >/dev/null 2>&1; then tests/integration/run-smtp-scenarios.sh; else echo "SKIP: postfix-test is not running"; fi
echo "##### seed";  uat seed.py
echo "##### restore"; tests/UAT/CrashTests-Sign/restore-test.sh
echo; echo "CrashTests-Sign: all passed."
