#!/usr/bin/env bash
# Keep your sign-in and directory settings (Microsoft, Google, Entra directory…) in a PRIVATE file,
# outside the repository, and put them back in one command instead of typing them again.
#
#   scripts/connections.sh export               # installation normale (projet « lcit-sign »)
#   scripts/connections.sh import
#   scripts/connections.sh export --crashtest   # la pile CrashTest
#   scripts/connections.sh import --crashtest
#
# The file holds client ids and the secrets ENCRYPTED under the master key (useless without it).
# Default place: ~/.config/lcit-sign/connections.json (mode 600). Change it with
# LCIT_SIGN_PRIVATE_DIR. A place inside the repository is refused unless Git ignores it.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

action="${1:-}"; shift || true
case "$action" in export|import) ;; *) echo "usage: $0 export|import [--crashtest]" >&2; exit 2;; esac

dir="${LCIT_SIGN_PRIVATE_DIR:-$HOME/.config/lcit-sign}"
file="$dir/connections.json"
case "$(realpath -m "$dir")/" in
    "$(pwd)"/*) git check-ignore -q "$file" || { echo "Refusé : $dir est dans le dépôt et n'est pas ignoré par Git." >&2; exit 1; };;
esac

if [ "${1:-}" = "--crashtest" ]; then
    ENV_FILE=crashtest/crashtest.env
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^LCIT_SIGN_[A-Z_]+$ ]] || continue
        [ -n "${!key+x}" ] || export "$key=$value"
    done < "$ENV_FILE"
    compose=(docker compose -p "$LCIT_SIGN_PREFIX" --env-file "$ENV_FILE"
             -f docker-compose.yml -f crashtest/docker-compose.crashtest.yml --profile crashtest)
else
    compose=(docker compose -p "${LCIT_SIGN_PREFIX:-lcit-sign}")
fi

if [ "$action" = export ]; then
    mkdir -p "$dir"; chmod 700 "$dir"
    umask 077
    "${compose[@]}" exec -T api python -m lcit_sign.cli export-connections > "$file.tmp"
    mv "$file.tmp" "$file"; chmod 600 "$file"
    echo "Réglages enregistrés dans $file (secrets chiffrés)."
else
    [ -f "$file" ] || { echo "Rien à restaurer : $file n'existe pas." >&2; exit 1; }
    "${compose[@]}" exec -T api python -m lcit_sign.cli import-connections < "$file"
fi
