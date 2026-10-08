#!/usr/bin/env bash
# Load the CrashTests dataset into the running stack (idempotent enough to
# re-run: roles and signatures already present are tolerated).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
docker run --rm --network host \
    -e LCIT_SIGN_BASE_URL="${LCIT_SIGN_BASE_URL:-http://localhost:4180}" \
    -v "$PWD/tests/crashtest/uat":/uat:ro \
    --entrypoint python "${LCIT_SIGN_API_IMAGE:-lcit-sign-api:latest}" /uat/seed.py
