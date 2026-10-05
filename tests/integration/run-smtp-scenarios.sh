#!/usr/bin/env bash
# Run the SMTP scenarios against the test Postfix, on the machine hosting
# the stack:
#   docker compose -f docker-compose.yml -f docker-compose.test.yml up -d --build postfix-test
#   tests/integration/run-smtp-scenarios.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

PF=lcit-sign-postfix-test
IMAGE="${LCIT_SIGN_API_IMAGE:-lcit-sign-api:latest}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK:?}"' EXIT

docker exec "$PF" cat /run/lcit-test/cert.pem >"$WORK/cert.pem"
# The API image runs as an unprivileged user: the (public) certificate and its
# directory must be world-readable. No private material is in $WORK.
chmod 755 "$WORK"; chmod 644 "$WORK/cert.pem"
CREDS="$(docker exec "$PF" cat /run/lcit-test/credentials)"
USER_NAME="$(printf '%s\n' "$CREDS" | sed -n 's/^username=//p')"
PASSWORD="$(printf '%s\n' "$CREDS" | sed -n 's/^password=//p')"

count_mail() {
    docker exec "$PF" sh -c 'find /var/mail/vhosts/lcit-test.local/alice.martin -type f 2>/dev/null | wc -l'
}
BEFORE="$(count_mail)"

docker run --rm --network host \
    -e TEST_SMTP_USER="$USER_NAME" -e TEST_SMTP_PASSWORD="$PASSWORD" \
    -e TEST_SMTP_CA_FILE=/ca/cert.pem \
    -v "$WORK":/ca:ro -v "$PWD/tests/integration":/it:ro \
    --entrypoint python "$IMAGE" /it/smtp_scenarios.py

AFTER="$(count_mail)"
DELIVERED=$((AFTER - BEFORE))
echo "mailbox deliveries during the run: $DELIVERED (expected 3)"
[[ "$DELIVERED" -eq 3 ]] || { echo "FAIL: unexpected number of deliveries"; exit 1; }

# The environment must never have tried to reach the Internet: nothing is
# queued for outbound delivery, and the external recipient was refused at RCPT.
QUEUE="$(docker exec "$PF" postqueue -p)"
if echo "$QUEUE" | grep -q "Mail queue is empty"; then
    echo "PASS: mail queue empty (nothing left for outbound delivery)"
else
    echo "FAIL: mail is queued"; echo "$QUEUE"; exit 1
fi
# Captured first: `grep -q` closing the pipe early would trip pipefail on docker logs.
PF_LOGS="$(docker logs "$PF" 2>&1)"
if grep -qi "Relay access denied" <<<"$PF_LOGS"; then
    echo "PASS: relay attempts were denied"
else
    echo "FAIL: no relay denial logged"; exit 1
fi
