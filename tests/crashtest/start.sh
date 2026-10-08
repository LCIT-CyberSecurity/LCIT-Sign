#!/usr/bin/env bash
# Start the CrashTest stack and load its dataset: a separate Docker project (own containers, own
# PostgreSQL, own volumes), the mock SSO, fictional accounts. Run it from anywhere.
#
#   ./tests/crashtest/start.sh
#
# Needs Docker. See tests/crashtest/README.md for the accounts and for putting it on another port.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

ENV_FILE=tests/crashtest/crashtest.env
# Did the caller choose where the mock finds its real accounts? (reset.sh already exported the
# env file's empty-folder default: that is not a choice.)
CALLER_SECRETS_DIR="${LCIT_SIGN_SECRETS_DIR-}"
[ "$CALLER_SECRETS_DIR" != "./tests/crashtest/no-secrets" ] || CALLER_SECRETS_DIR=""
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

# The real accounts the mock SSO may offer (Entra, Google) are read from a PRIVATE folder outside
# the repository, filled below from your imported connection settings. Created before the stack
# starts, so Docker does not create it as root.
PRIVATE_DIR="${LCIT_SIGN_PRIVATE_DIR:-$HOME/.config/lcit-sign}"
MOCK_DIR="$PRIVATE_DIR/mock-sso"
if [ -z "$CALLER_SECRETS_DIR" ]; then
    mkdir -p "$MOCK_DIR"; chmod 700 "$PRIVATE_DIR" "$MOCK_DIR"
    export LCIT_SIGN_SECRETS_DIR="$MOCK_DIR"
fi
: "${MOCK_OIDC_UID:=$(id -u)}"
export MOCK_OIDC_UID

COMPOSE=(docker compose -p "$LCIT_SIGN_PREFIX" --env-file "$ENV_FILE"
         -f compose.yaml -f tests/crashtest/compose.crashtest.yaml --profile crashtest)

echo "== CrashTest « $LCIT_SIGN_PREFIX » : démarrage de la pile"
"${COMPOSE[@]}" up -d --build --wait

echo "== Jeu de données (comptes fictifs, campagnes)"
"${COMPOSE[@]}" exec -T api python /crashtest/seed.py

# Your own settings (Microsoft, Google, Entra directory), kept in a private file outside the
# repository by ops/admin/connections.sh export --crashtest: put back if there is one.
if [ -f "$PRIVATE_DIR/connections.json" ]; then
    echo "== Restauration de vos réglages de connexion"
    ./ops/admin/connections.sh import --crashtest
fi

# Entra / Google behind the mock SSO: built from those settings (secret decrypted into a private
# file, mode 600, never printed, never in Git). Nothing found: the mock offers its fictional people.
if [ "$LCIT_SIGN_SECRETS_DIR" = "$MOCK_DIR" ]; then
    ( umask 077
      "${COMPOSE[@]}" exec -T api python -m lcit_sign.cli export-mock-providers \
          > "$MOCK_DIR/mock-oidc-providers.json.tmp" )
    if [ "$(tr -d '[:space:]' < "$MOCK_DIR/mock-oidc-providers.json.tmp")" = "{}" ]; then
        rm -f "$MOCK_DIR/mock-oidc-providers.json.tmp" "$MOCK_DIR/mock-oidc-providers.json"
        echo "== Aucun compte réel (Entra/Google) dans vos réglages : le Mock SSO propose ses personnes fictives."
    else
        mv "$MOCK_DIR/mock-oidc-providers.json.tmp" "$MOCK_DIR/mock-oidc-providers.json"
        chmod 600 "$MOCK_DIR/mock-oidc-providers.json"
        echo "== Comptes réels disponibles derrière le Mock SSO : $(python3 -c "import json,sys; print(', '.join(json.load(open(sys.argv[1]))))" "$MOCK_DIR/mock-oidc-providers.json")"
    fi
fi

echo
echo "LCIT Sign CrashTest est prêt : $LCIT_SIGN_PUBLIC_BASE_URL"
echo "  (réinitialiser : ./tests/crashtest/reset.sh — ne touche qu'au projet « $LCIT_SIGN_PREFIX »)"
