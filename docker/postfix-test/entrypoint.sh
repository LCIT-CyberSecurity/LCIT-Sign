#!/bin/sh
# Test Postfix: a throwaway certificate and a random SASL password are
# generated at every start. Nothing secret exists in the image or in Git;
# the test harness reads the password from /run/lcit-test/credentials.
set -eu

HOST=postfix-test.lcit-test.local
mkdir -p /run/lcit-test /etc/postfix/tls
chmod 755 /run/lcit-test

openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
    -keyout /etc/postfix/tls/key.pem -out /etc/postfix/tls/cert.pem \
    -subj "/CN=$HOST" \
    -addext "subjectAltName=DNS:$HOST,DNS:postfix-test,DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1
chmod 600 /etc/postfix/tls/key.pem
cp /etc/postfix/tls/cert.pem /run/lcit-test/cert.pem

PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
printf 'username=lcit-sign@lcit-test.local\npassword=%s\n' "$PASSWORD" >/run/lcit-test/credentials
chmod 644 /run/lcit-test/credentials
echo "$PASSWORD" | saslpasswd2 -c -p -u lcit-test.local lcit-sign
chgrp postfix /etc/sasldb2 && chmod 640 /etc/sasldb2

cat >/etc/postfix/sasl/smtpd.conf <<SASL
pwcheck_method: auxprop
auxprop_plugin: sasldb
mech_list: PLAIN LOGIN
SASL

# Mailboxes are fictional and local; nothing else exists.
: >/etc/postfix/vmailbox
for u in lcit-sign alice.martin bob.dupont charlie.durand diane.leroy erwan.petit fatima.benali; do
    echo "$u@lcit-test.local lcit-test.local/$u/" >>/etc/postfix/vmailbox
done
postmap /etc/postfix/vmailbox

postconf -e "myhostname = $HOST" \
    "mydestination =" \
    "alias_maps =" \
    "alias_database =" \
    "local_recipient_maps =" \
    "mynetworks = 127.0.0.0/8" \
    "inet_interfaces = all" \
    "inet_protocols = ipv4" \
    "virtual_mailbox_domains = lcit-test.local" \
    "virtual_mailbox_base = /var/mail/vhosts" \
    "virtual_mailbox_maps = hash:/etc/postfix/vmailbox" \
    "virtual_transport = virtual" \
    "virtual_uid_maps = static:5000" \
    "virtual_gid_maps = static:5000" \
    "virtual_minimum_uid = 100" \
    "smtpd_relay_restrictions = reject_unauth_destination" \
    "smtpd_recipient_restrictions = check_recipient_access regexp:/etc/postfix/recipient_access, reject_unauth_destination, reject_unlisted_recipient" \
    "smtpd_tls_cert_file = /etc/postfix/tls/cert.pem" \
    "smtpd_tls_key_file = /etc/postfix/tls/key.pem" \
    "smtpd_tls_security_level = may" \
    "smtpd_sasl_type = cyrus" \
    "smtpd_sasl_path = smtpd" \
    "smtpd_sasl_security_options = noanonymous" \
    "smtpd_sasl_local_domain = lcit-test.local" \
    "broken_sasl_auth_clients = yes" \
    "default_transport = error:outbound delivery is disabled in this test environment" \
    "relay_transport = error:outbound delivery is disabled in this test environment" \
    "soft_bounce = no" \
    "maillog_file = /dev/stdout"

# Port 25: plain, no TLS offered, no AUTH. chroot is off so smtpd can read sasldb.
postconf -M "smtp/inet=smtp inet n - n - - smtpd"
postconf -P "smtp/inet/smtpd_tls_security_level=none"

# 587: STARTTLS required, then AUTH.
postconf -M "587/inet=587 inet n - n - - smtpd"
postconf -P "587/inet/smtpd_tls_security_level=encrypt" \
            "587/inet/smtpd_sasl_auth_enable=yes" \
            "587/inet/smtpd_tls_auth_only=yes"

# 465: implicit TLS, then AUTH.
postconf -M "465/inet=465 inet n - n - - smtpd"
postconf -P "465/inet/smtpd_tls_wrappermode=yes" \
            "465/inet/smtpd_tls_security_level=encrypt" \
            "465/inet/smtpd_sasl_auth_enable=yes"

# 2526: accepts the connection, never speaks (client timeout scenario).
socat TCP-LISTEN:2526,fork,reuseaddr SYSTEM:"sleep 3600" &

postfix check
exec postfix start-fg
