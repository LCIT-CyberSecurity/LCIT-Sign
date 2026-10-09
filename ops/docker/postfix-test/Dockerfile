# Postfix for TESTS ONLY. It is not an open relay and cannot reach the
# Internet: it accepts mail only for fictional *.lcit-test.local mailboxes
# and refuses every other destination ("Relay access denied"); outbound
# delivery is disabled outright. Never deploy it outside a test network.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN echo "postfix postfix/main_mailer_type select No configuration" | debconf-set-selections \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        postfix libsasl2-modules libsasl2-modules-db sasl2-bin openssl socat ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 5000 vmail && useradd -u 5000 -g 5000 -d /var/mail/vhosts -s /usr/sbin/nologin vmail \
    && mkdir -p /var/mail/vhosts /etc/postfix/sasl && chown -R vmail:vmail /var/mail/vhosts

# The 'No configuration' preseed installs no config files: an empty main.cf (compiled-in defaults) plus the dist master.cf.
RUN : > /etc/postfix/main.cf \
    && cp /usr/share/postfix/master.cf.dist /etc/postfix/master.cf

COPY entrypoint.sh /entrypoint.sh
COPY recipient_access /etc/postfix/recipient_access
RUN chmod +x /entrypoint.sh
# 25: plain, no TLS | 587: STARTTLS + AUTH | 465: implicit TLS + AUTH
# 2526: accepts connections and never answers (timeout scenario)
EXPOSE 25 587 465 2526
ENTRYPOINT ["/entrypoint.sh"]
