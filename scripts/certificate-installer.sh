#!/usr/bin/env bash
# LCIT Sign — HTTPS certificate installer for the Docker deployment.
#
# Installs, shows or reverts the certificate presented by the reverse proxy,
# validating before it changes anything, verifying the certificate that is
# really served afterwards, and rolling back on any failure.
#
#   scripts/certificate-installer.sh                      interactive menu
#   scripts/certificate-installer.sh --test-command <cmd> [args]   one step
#
# Test commands: validate-certificate <cert> <key> <fqdn>
#                validate-installation
#                copy-certificate <cert> <key> <dest-dir>
#                show-current
#                install-certificate <cert> <key>
#                revert-selfsigned
#
# Environment: LCIT_SIGN_DIR (compose dir), LCIT_SIGN_CERT_DIR, LCIT_SIGN_FQDN,
# LCIT_SIGN_HTTPS_PORT, LCIT_SIGN_TLS_CONNECT_HOST, LCIT_SIGN_DOCKER,
# LCIT_SIGN_PROXY_SERVICE. A private key is never printed or logged.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${LCIT_SIGN_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
CERT_DIR="${LCIT_SIGN_CERT_DIR:-$INSTALL_DIR/certs}"
BACKUP_DIR="${LCIT_SIGN_CERT_BACKUP_DIR:-${CERT_DIR%/}.backup}"
FQDN="${LCIT_SIGN_FQDN:-}"
HTTPS_PORT="${LCIT_SIGN_HTTPS_PORT:-4443}"
CONNECT_HOST="${LCIT_SIGN_TLS_CONNECT_HOST:-127.0.0.1}"
DOCKER="${LCIT_SIGN_DOCKER:-docker}"
PROXY_SERVICE="${LCIT_SIGN_PROXY_SERVICE:-webui}"
LOG_FILE="${LCIT_SIGN_CERT_LOG:-$INSTALL_DIR/certificate-installer.log}"
VERIFY_TIMEOUT="${LCIT_SIGN_VERIFY_TIMEOUT:-15}"
WARN_DAYS=30
CRT="tls.crt"
KEY="tls.key"

# --- output and trace -------------------------------------------------------

say()  { printf '%s\n' "$*"; }
ok()   { printf '  [ OK ] %s\n' "$*"; }
warn() { printf '  [WARN] %s\n' "$*" >&2; }
fail() { printf '  [FAIL] %s\n' "$*" >&2; }

# Operation trace: date, operation, FQDN, fingerprint, subject, result,
# rollback. Never any key material (spec §114).
log_op() {
    local operation="$1" result="$2" rollback="${3:-no}" fingerprint="${4:-}" subject="${5:-}"
    local line
    line="$(date -u +%FT%TZ) op=${operation} fqdn=${FQDN:-?} fingerprint=${fingerprint:-?}"
    line="${line} subject=${subject:-?} result=${result} rollback=${rollback}"
    command -v logger >/dev/null 2>&1 && logger -t lcit-sign-certificate -- "$line" 2>/dev/null
    printf '%s\n' "$line" >>"$LOG_FILE" 2>/dev/null || true
}

# --- certificate inspection -------------------------------------------------

cert_fingerprint() {
    openssl x509 -in "$1" -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2
}

cert_subject() {
    openssl x509 -in "$1" -noout -subject 2>/dev/null | sed 's/^subject= *//'
}

cert_issuer() {
    openssl x509 -in "$1" -noout -issuer 2>/dev/null | sed 's/^issuer= *//'
}

cert_san_dns() {
    openssl x509 -in "$1" -noout -ext subjectAltName 2>/dev/null \
        | grep -o 'DNS:[^,[:space:]]*' | cut -c5-
}

cert_epoch() {  # cert, startdate|enddate
    local value
    value="$(openssl x509 -in "$1" -noout "-$2" 2>/dev/null | cut -d= -f2)"
    [[ -n "$value" ]] && date -u -d "$value" +%s 2>/dev/null
}

cert_pubkey_digest() {
    openssl x509 -in "$1" -noout -pubkey 2>/dev/null \
        | openssl pkey -pubin -pubout -outform DER 2>/dev/null | sha256sum | cut -d' ' -f1
}

key_pubkey_digest() {
    # Empty passphrase: an encrypted key fails here instead of prompting.
    openssl pkey -in "$1" -pubout -outform DER -passin pass: 2>/dev/null \
        | sha256sum | cut -d' ' -f1
}

# Standard TLS hostname matching: exact (case-insensitive), or a wildcard
# that is the whole leftmost label and covers exactly one label.
hostname_matches() {
    local host="${1,,}" pattern="${2,,}"
    if [[ "$pattern" == \*.* ]]; then
        local rest="${pattern#*.}"
        [[ "$rest" == *.* ]] || return 1          # "*.com" is not a valid wildcard
        [[ "$host" == *.* ]] || return 1
        [[ "${host%%.*}" != "" ]] || return 1
        [[ "${host#*.}" == "$rest" ]]
        return
    fi
    [[ "$host" == "$pattern" ]]
}

# --- validation (spec §100-101) ----------------------------------------------

# Prints FAIL/WARN lines; returns 0 only if nothing failed.
validate_certificate() {
    local cert="$1" key="$2" fqdn="$3" failed=0

    if [[ ! -f "$cert" ]]; then fail "certificate file not found: $cert"; return 1; fi
    if [[ ! -f "$key" ]]; then fail "private key file not found: $key"; return 1; fi
    ok "certificate and key files present"

    if ! grep -q 'BEGIN CERTIFICATE' "$cert" || ! openssl x509 -in "$cert" -noout 2>/dev/null; then
        fail "the certificate is not a valid PEM certificate"; return 1
    fi
    ok "certificate PEM is valid"

    if ! openssl pkey -in "$key" -noout -passin pass: 2>/dev/null; then
        fail "the private key is not a valid, unencrypted PEM key"; return 1
    fi
    ok "private key PEM is valid"

    local cert_digest key_digest
    cert_digest="$(cert_pubkey_digest "$cert")"
    key_digest="$(key_pubkey_digest "$key")"
    if [[ -z "$cert_digest" || "$cert_digest" != "$key_digest" ]]; then
        fail "the private key does not match the certificate"; failed=1
    else
        ok "certificate and private key match"
    fi

    local now start end
    now="$(date -u +%s)"
    start="$(cert_epoch "$cert" startdate)"
    end="$(cert_epoch "$cert" enddate)"
    if [[ -z "$start" || -z "$end" ]]; then
        fail "cannot read the certificate validity dates"; failed=1
    else
        if (( now < start )); then
            fail "the certificate is not valid yet (notBefore is in the future)"; failed=1
        elif (( now >= end )); then
            fail "the certificate has expired"; failed=1
        else
            ok "certificate validity period is current"
        fi
    fi

    local sans
    sans="$(cert_san_dns "$cert")"
    if [[ -z "$sans" ]]; then
        fail "the certificate has no Subject Alternative Name (DNS)"; failed=1
    else
        ok "SAN present"
        local covered=0 name
        while IFS= read -r name; do
            if hostname_matches "$fqdn" "$name"; then covered=1; break; fi
        done <<<"$sans"
        if (( covered )); then
            ok "FQDN ${fqdn} is covered by the SAN"
        else
            fail "FQDN ${fqdn} is not covered by the certificate SAN"; failed=1
        fi
    fi

    # An isolated non-self-signed certificate usually means the intermediate
    # CA certificate was left out; informative only (spec §101).
    local count
    count="$(grep -c 'BEGIN CERTIFICATE' "$cert")"
    if (( count == 1 )) && [[ "$(cert_subject "$cert")" != "$(cert_issuer "$cert")" ]]; then
        warn "possible intermediate certificate missing (only one certificate in the file)"
    fi

    return "$failed"
}

# --- what the proxy really presents (spec §109) --------------------------------

presented_certificate() {  # prints the PEM certificate served on the HTTPS port
    local sni="${FQDN:-$CONNECT_HOST}"
    timeout 10 openssl s_client -connect "${CONNECT_HOST}:${HTTPS_PORT}" -servername "$sni" \
        </dev/null 2>/dev/null | openssl x509 -outform PEM 2>/dev/null
}

presented_fingerprint() {
    local pem
    pem="$(presented_certificate)"
    [[ -n "$pem" ]] || return 1
    printf '%s\n' "$pem" | openssl x509 -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2
}

# Wait until the proxy serves `expected` (or, with no argument, anything).
wait_for_fingerprint() {
    local expected="${1:-}" deadline=$((SECONDS + VERIFY_TIMEOUT)) current=""
    while (( SECONDS <= deadline )); do
        current="$(presented_fingerprint)"
        if [[ -n "$current" && ( -z "$expected" || "$current" == "$expected" ) ]]; then
            printf '%s' "$current"
            return 0
        fi
        sleep 1
    done
    printf '%s' "$current"
    return 1
}

# --- files: permissions, atomic copy, backup (spec §103, §105-106) ---------------

copy_certificate() {  # cert key dest-dir
    local cert="$1" key="$2" dest="${3:?destination directory required}"
    mkdir -p "$dest" || return 1
    if [[ ! -w "$dest" || ! -O "$dest" ]]; then
        # Typically the directory was created by Docker (a bind mount of a
        # missing path is created by root). Create it yourself beforehand:
        #   mkdir -p -m 700 certs
        fail "${dest} is not owned and writable by $(id -un); fix: sudo chown -R $(id -un) ${dest}"
        return 1
    fi
    chmod 700 "$dest" || return 1
    local tmp_crt tmp_key
    tmp_crt="$(mktemp "$dest/.${CRT}.XXXXXX")" || return 1
    tmp_key="$(mktemp "$dest/.${KEY}.XXXXXX")" || { rm -f "${tmp_crt:?}"; return 1; }
    # Written under their final modes first, then moved into place: a reader
    # never sees a half-written file or a world-readable key.
    chmod 644 "$tmp_crt"; chmod 600 "$tmp_key"
    if ! cat "$cert" >"$tmp_crt" || ! cat "$key" >"$tmp_key"; then
        rm -f "${tmp_crt:?}" "${tmp_key:?}"; return 1
    fi
    mv -f "$tmp_key" "$dest/$KEY" && mv -f "$tmp_crt" "$dest/$CRT"
}

backup_current() {
    # A single rollback copy, no key accumulation. ${VAR:?} aborts instead
    # of ever expanding to an empty path.
    rm -rf "${BACKUP_DIR:?}"
    mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR" || return 1
    if [[ -f "$CERT_DIR/$CRT" && -f "$CERT_DIR/$KEY" ]]; then
        cp -p "$CERT_DIR/$CRT" "$BACKUP_DIR/$CRT" && cp -p "$CERT_DIR/$KEY" "$BACKUP_DIR/$KEY" \
            && chmod 600 "$BACKUP_DIR/$KEY"
    else
        : >"$BACKUP_DIR/.none"      # nothing was installed: rollback removes
    fi
}

remove_installed() {
    rm -f "${CERT_DIR:?}/${CRT:?}" "${CERT_DIR:?}/${KEY:?}"
}

restore_backup() {
    if [[ -f "$BACKUP_DIR/.none" ]]; then
        remove_installed
    elif [[ -f "$BACKUP_DIR/$CRT" && -f "$BACKUP_DIR/$KEY" ]]; then
        copy_certificate "$BACKUP_DIR/$CRT" "$BACKUP_DIR/$KEY" "$CERT_DIR"
    else
        return 1
    fi
}

# --- Docker (spec §107-108) ----------------------------------------------------

compose_validate() {
    (cd "$INSTALL_DIR" && "$DOCKER" compose config -q) >/dev/null 2>&1
}

recreate_proxy() {
    (cd "$INSTALL_DIR" && "$DOCKER" compose up -d --force-recreate --no-deps "$PROXY_SERVICE") \
        >/dev/null 2>&1
}

rollback() {
    local operation="$1"
    warn "rolling back to the previous certificate"
    if restore_backup && recreate_proxy; then
        ok "previous configuration restored"
    else
        fail "rollback incomplete: check ${CERT_DIR} and the proxy by hand"
    fi
    log_op "$operation" failure yes
}

# --- operations -------------------------------------------------------------------

require_fqdn() {
    if [[ -z "$FQDN" && -t 0 ]]; then
        read -r -p "FQDN users reach this installation at: " FQDN
    fi
    [[ -n "$FQDN" ]] || { fail "FQDN is required (set LCIT_SIGN_FQDN)"; return 1; }
}

install_certificate() {  # cert key
    local cert="$1" key="$2"
    require_fqdn || return 1
    say "Validating the new certificate..."
    if ! validate_certificate "$cert" "$key" "$FQDN"; then
        log_op install failure no "" ""
        fail "nothing was changed"
        return 1
    fi

    local expected subject
    expected="$(cert_fingerprint "$cert")"
    subject="$(cert_subject "$cert")"

    backup_current || { fail "cannot create the rollback backup"; return 1; }
    ok "rollback backup created (single copy, restricted permissions)"

    if ! copy_certificate "$cert" "$key" "$CERT_DIR"; then
        fail "cannot write the certificate files"
        rollback install; return 1
    fi
    ok "certificate installed atomically"

    if ! compose_validate; then
        fail "docker compose configuration is invalid"
        rollback install; return 1
    fi
    if ! recreate_proxy; then
        fail "the reverse proxy did not start"
        rollback install; return 1
    fi

    local presented
    if ! presented="$(wait_for_fingerprint "$expected")"; then
        fail "the proxy presents a different certificate (${presented:-none})"
        rollback install; return 1
    fi
    ok "the proxy presents the new certificate (${presented})"
    log_op install success no "$expected" "$subject"
    return 0
}

revert_to_selfsigned() {
    require_fqdn || return 1
    backup_current || { fail "cannot create the rollback backup"; return 1; }
    remove_installed
    if ! compose_validate || ! recreate_proxy; then
        fail "the reverse proxy did not start"
        rollback revert; return 1
    fi
    local presented
    if ! presented="$(wait_for_fingerprint)"; then
        fail "the proxy does not answer over TLS"
        rollback revert; return 1
    fi
    ok "the proxy now presents its self-signed certificate (${presented})"
    log_op revert success no "$presented" "self-signed"
}

show_current() {
    local pem
    pem="$(presented_certificate)"
    if [[ -z "$pem" ]]; then
        fail "no certificate presented on ${CONNECT_HOST}:${HTTPS_PORT}"
        return 1
    fi
    local file
    file="$(mktemp)" && printf '%s\n' "$pem" >"$file"
    local end now days
    end="$(cert_epoch "$file" enddate)"; now="$(date -u +%s)"
    days=$(( (end - now) / 86400 ))
    say "Subject      : $(cert_subject "$file")"
    say "Issuer       : $(cert_issuer "$file")"
    say "Valid from   : $(openssl x509 -in "$file" -noout -startdate | cut -d= -f2)"
    say "Valid until  : $(openssl x509 -in "$file" -noout -enddate | cut -d= -f2)"
    say "Days remaining: ${days}"
    say "SAN          : $(cert_san_dns "$file" | paste -sd, -)"
    say "SHA-256      : $(cert_fingerprint "$file")"
    (( days < WARN_DAYS )) && warn "the certificate expires in less than ${WARN_DAYS} days"
    rm -f "${file:?}"
    return 0
}

validate_installation() {
    local failed=0 mode
    for entry in "$CERT_DIR:700" "$CERT_DIR/$KEY:600" "$CERT_DIR/$CRT:644"; do
        local path="${entry%%:*}" expected="${entry##*:}"
        if [[ ! -e "$path" ]]; then fail "missing: $path"; failed=1; continue; fi
        mode="$(stat -c '%a' "$path")"
        if [[ "$mode" != "$expected" ]]; then
            fail "$path has mode $mode (expected $expected)"; failed=1
        else
            ok "$path mode $mode"
        fi
    done
    (( failed )) && return 1
    if [[ "$(cert_pubkey_digest "$CERT_DIR/$CRT")" != "$(key_pubkey_digest "$CERT_DIR/$KEY")" ]]; then
        fail "installed certificate and key do not match"; return 1
    fi
    ok "installed certificate and key match"
    local expected presented
    expected="$(cert_fingerprint "$CERT_DIR/$CRT")"
    presented="$(presented_fingerprint)" || { fail "no certificate presented"; return 1; }
    if [[ "$presented" != "$expected" ]]; then
        fail "the proxy presents ${presented}, the installed file is ${expected}"; return 1
    fi
    ok "the proxy presents the installed certificate"
}

# --- entry points -------------------------------------------------------------------

menu() {
    while true; do
        cat <<'MENU'

LCIT Sign — HTTPS certificate
  1) Install / replace a custom certificate
  2) Show the certificate currently presented
  3) Revert to the self-signed certificate
  4) Quit
MENU
        read -r -p "Choice: " choice || return 0
        case "$choice" in
            1)
                read -r -p "Certificate file (PEM, with chain if any): " cert
                read -r -p "Private key file (PEM, unencrypted): " key
                install_certificate "$cert" "$key" ;;
            2) show_current ;;
            3) revert_to_selfsigned ;;
            4) return 0 ;;
            *) warn "unknown choice" ;;
        esac
    done
}

main() {
    command -v openssl >/dev/null 2>&1 || { fail "openssl is required"; exit 2; }
    if [[ "${1:-}" == "--test-command" ]]; then
        local command="${2:-}"; shift 2 || true
        case "$command" in
            validate-certificate) validate_certificate "${1:-}" "${2:-}" "${3:-$FQDN}" ;;
            validate-installation) validate_installation ;;
            copy-certificate) copy_certificate "${1:-}" "${2:-}" "${3:-}" ;;
            show-current) show_current ;;
            install-certificate) install_certificate "${1:-}" "${2:-}" ;;
            revert-selfsigned) revert_to_selfsigned ;;
            *) fail "unknown test command: $command"; exit 2 ;;
        esac
        exit $?
    fi
    menu
}

main "$@"
