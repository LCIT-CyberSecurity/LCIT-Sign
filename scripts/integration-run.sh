#!/usr/bin/env bash
# Run a repository script on the Integrations VM over SSH.
#
#   LCIT_SIGN_INTEGRATION_HOST=vm-integrations \
#   LCIT_SIGN_INTEGRATION_USER=cdev \
#   scripts/integration-run.sh scripts/integration-reset.sh --yes --seed
#
# The host can be an ~/.ssh/config alias. The SSH key lives in ~/.ssh or an
# agent — never in this repository — and the host key is verified: this
# script does not, and must not, use StrictHostKeyChecking=no (spec §90).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

HOST="${LCIT_SIGN_INTEGRATION_HOST:?set LCIT_SIGN_INTEGRATION_HOST}"
REMOTE_USER="${LCIT_SIGN_INTEGRATION_USER:-}"
TARGET="${REMOTE_USER:+$REMOTE_USER@}$HOST"
REMOTE_DIR="${LCIT_SIGN_INTEGRATION_DIR:-Git/LCIT-Sign}"
[[ $# -ge 1 ]] || { echo "usage: integration-run.sh <script> [args...]"; exit 2; }

# The working tree is the source of truth; the VM never is (spec §96).
# .env and TLS material on the VM are preserved.
rsync -az --delete \
    --exclude .git --exclude .env --exclude certs --exclude certs.backup \
    --exclude node_modules --exclude dist --exclude '.*cache' --exclude __pycache__ \
    --exclude backups --exclude '*.log' \
    ./ "$TARGET:$REMOTE_DIR/"
# shellcheck disable=SC2029
ssh "$TARGET" "cd '$REMOTE_DIR' && $(printf '%q ' "$@")"
