#!/bin/sh
# Runs from /docker-entrypoint.d before nginx starts. Points nginx at the
# certificate mounted (read-only) in /etc/nginx/certs when there is one,
# otherwise at a self-signed certificate generated here — in the container
# filesystem, never in an image layer, so no key is baked into the image.
set -eu

CERT_DIR=/etc/nginx/certs
FALLBACK_DIR=/var/lib/lcit-sign-tls
CONF_DIR=/etc/nginx/lcit-sign
FQDN="${LCIT_SIGN_TLS_FQDN:-localhost}"

mkdir -p "$CONF_DIR"

if [ -s "$CERT_DIR/tls.crt" ] && [ -s "$CERT_DIR/tls.key" ]; then
    crt="$CERT_DIR/tls.crt"
    key="$CERT_DIR/tls.key"
    echo "lcit-sign-tls: using the mounted certificate"
else
    mkdir -p "$FALLBACK_DIR"
    chmod 700 "$FALLBACK_DIR"
    crt="$FALLBACK_DIR/selfsigned.crt"
    key="$FALLBACK_DIR/selfsigned.key"
    if [ ! -s "$crt" ] || [ ! -s "$key" ]; then
        openssl req -x509 -newkey rsa:3072 -nodes -days 825 \
            -keyout "$key" -out "$crt" -subj "/CN=$FQDN/O=LCIT Sign (self-signed)" \
            -addext "subjectAltName=DNS:$FQDN,DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1
        chmod 600 "$key"
    fi
    echo "lcit-sign-tls: no certificate mounted, using a self-signed one for $FQDN"
fi

printf 'ssl_certificate %s;\nssl_certificate_key %s;\n' "$crt" "$key" >"$CONF_DIR/tls.conf"
