"""Real accounts behind the mock SSO, for trying LCIT Sign with Entra ID, Google or an LDAP
directory without changing how the app signs in: the app still talks to ONE OpenID Connect
provider (this one) and never sees a password. Entra and Google are used through their own
login page; LDAP asks for a login and a password HERE, checks them against the directory and
forgets them.

Dev / demo only, like the rest of this service. Which providers exist, and their secrets, come
from a JSON file kept outside Git (MOCK_OIDC_PROVIDERS_FILE); with no file, nothing changes.

    {
      "entra":  {"tenant_id": "...", "client_id": "...", "client_secret": "..."},
      "google": {"client_id": "...", "client_secret": "...", "allowed_domain": "corp.fr"},
      "ldap":   {"server_url": "ldaps://ldap.corp.fr:636", "bind_dn": "cn=svc,dc=corp,dc=fr",
                 "bind_password": "...", "base_dn": "dc=corp,dc=fr"}
    }
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.oauth2.rfc7636 import create_s256_code_challenge

logger = logging.getLogger("mock_oidc.providers")

STATE_TTL_SECONDS = 600
MAX_STATES = 500
LDAP_ATTEMPTS = 5
LDAP_WINDOW_SECONDS = 300

_states: dict[str, dict[str, Any]] = {}
_ldap_attempts: dict[str, list[float]] = {}


def _default_client() -> httpx.Client:
    return httpx.Client(timeout=20.0)


# Replaced by the tests: the HTTP client used to reach Microsoft / Google, and the LDAP connection.
http_client: Callable[[], httpx.Client] = _default_client
ldap_connect: Callable[..., Any] | None = None

LABELS = {"entra": "Microsoft Entra ID", "google": "Google", "ldap": "LDAP / Active Directory"}


def load_config() -> dict[str, dict[str, str]]:
    path = os.environ.get("MOCK_OIDC_PROVIDERS_FILE", "")
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        logger.error("providers file unreadable: real providers disabled")
        return {}
    required = {
        "entra": ("tenant_id", "client_id", "client_secret"),
        "google": ("client_id", "client_secret"),
        "ldap": ("server_url", "bind_dn", "bind_password", "base_dn"),
    }
    return {
        name: {k: str(v) for k, v in values.items()}
        for name, values in raw.items()
        if name in required
        and isinstance(values, dict)
        and all(values.get(key) for key in required[name])
    }


def allowed_redirects() -> list[str]:
    return [
        u.strip() for u in os.environ.get("MOCK_OIDC_ALLOWED_REDIRECTS", "").split(",") if u.strip()
    ]


def redirect_allowed(uri: str) -> bool:
    """With an allow-list set, only those exact addresses receive a code. Without one, the mock
    stays as open as it always was — which is why real providers refuse to work without it."""
    allowed = allowed_redirects()
    return not allowed or uri in allowed


def real_login_possible() -> bool:
    """Real accounts are only offered when the codes can only go to the app itself: otherwise a
    crafted link could send a signed-in person's code to someone else."""
    return bool(allowed_redirects())


def _purge() -> None:
    now = time.time()
    for key in [k for k, v in _states.items() if now - v["created"] > STATE_TTL_SECONDS]:
        del _states[key]
    while len(_states) > MAX_STATES:
        _states.pop(next(iter(_states)))


def _callback_url(public_base: str, provider: str) -> str:
    return f"{public_base.rstrip('/')}/callback/{provider}"


def begin(provider: str, params: dict[str, str], public_base: str) -> str:
    """The address of the provider's own login page, for this sign-in. What the app asked is
    kept here, under a one-time state, until the provider sends the person back."""
    config = load_config().get(provider)
    if config is None or provider not in ("entra", "google"):
        raise LookupError(provider)
    _purge()
    token = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(16)
    _states[token] = {
        "provider": provider,
        "params": params,
        "verifier": verifier,
        "nonce": nonce,
        "created": time.time(),
    }
    query = {
        "client_id": config["client_id"],
        "response_type": "code",
        "redirect_uri": _callback_url(public_base, provider),
        "scope": "openid profile email",
        "state": token,
        "nonce": nonce,
        "code_challenge": create_s256_code_challenge(verifier),
        "code_challenge_method": "S256",
    }
    if provider == "entra":
        base = f"https://login.microsoftonline.com/{config['tenant_id']}/oauth2/v2.0/authorize"
        query["prompt"] = "select_account"
    else:
        base = "https://accounts.google.com/o/oauth2/v2/auth"
        query["prompt"] = "select_account"
        if config.get("allowed_domain"):
            query["hd"] = config["allowed_domain"]
    return f"{base}?{urlencode(query)}"


class ProviderError(Exception):
    """The provider refused, or answered something unusable; the message is for the person."""


def _claims_of(id_token: str) -> dict[str, Any]:
    # Received straight from the provider's token endpoint over TLS in exchange for our own
    # code: OpenID Connect lets the client rely on that without checking the signature.
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as exc:
        raise ProviderError("Réponse du fournisseur illisible.") from exc
    if not isinstance(data, dict):
        raise ProviderError("Réponse du fournisseur illisible.")
    return data


def _split(name: str) -> tuple[str, str]:
    given, _, family = name.strip().partition(" ")
    return given, family


def finish(
    provider: str, code: str, state: str, public_base: str
) -> tuple[dict[str, str], dict[str, str]]:
    """Trade the provider's code for who the person is. Returns (identity, what the app asked)."""
    pending = _states.pop(state, None)
    if pending is None or pending["provider"] != provider:
        raise ProviderError("Connexion expirée ou déjà utilisée : recommencez.")
    if time.time() - pending["created"] > STATE_TTL_SECONDS:
        raise ProviderError("Connexion expirée : recommencez.")
    config = load_config().get(provider)
    if config is None:
        raise ProviderError("Ce fournisseur n'est plus configuré.")
    if provider == "entra":
        token_url = f"https://login.microsoftonline.com/{config['tenant_id']}/oauth2/v2.0/token"
    else:
        token_url = "https://oauth2.googleapis.com/token"  # noqa: S105
    try:
        with http_client() as client:
            response = client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _callback_url(public_base, provider),
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "code_verifier": pending["verifier"],
                },
            )
    except httpx.HTTPError as exc:
        raise ProviderError("Impossible de joindre le fournisseur d'identité.") from exc
    if response.status_code != 200:
        raise ProviderError(
            "Le fournisseur a refusé la connexion"
            + (
                f" ({response.json().get('error', 'erreur')})."
                if response.headers.get("content-type", "").startswith("application/json")
                else "."
            )
        )
    claims = _claims_of(str(response.json().get("id_token", "")))
    if claims.get("aud") != config["client_id"] or claims.get("nonce") != pending["nonce"]:
        raise ProviderError("Réponse du fournisseur incohérente : connexion refusée.")
    if provider == "google":
        if claims.get("email_verified") is False:
            raise ProviderError("Cette adresse Google n'est pas vérifiée.")
        domain = config.get("allowed_domain")
        if domain and str(claims.get("email", "")).lower().rsplit("@", 1)[-1] != domain.lower():
            raise ProviderError(f"Seuls les comptes @{domain} sont acceptés.")
        email = str(claims.get("email", ""))
        subject = f"google:{claims.get('sub', '')}"
    else:
        # Entra gives the sign-in name (and the mail when the account has one).
        email = str(claims.get("email") or claims.get("preferred_username") or "")
        subject = f"entra:{claims.get('oid') or claims.get('sub', '')}"
    if "@" not in email:
        raise ProviderError("Ce compte n'a pas d'adresse e-mail : connexion impossible.")
    given = str(claims.get("given_name") or "")
    family = str(claims.get("family_name") or "")
    if not given and not family:
        given, family = _split(str(claims.get("name") or email.split("@")[0]))
    return (
        {"sub": subject, "email": email.lower(), "given_name": given, "family_name": family},
        pending["params"],
    )


def _throttled(key: str) -> bool:
    now = time.time()
    recent = [t for t in _ldap_attempts.get(key, []) if now - t < LDAP_WINDOW_SECONDS]
    _ldap_attempts[key] = recent
    return len(recent) >= LDAP_ATTEMPTS


def ldap_login(login: str, password: str, client_ip: str) -> dict[str, str] | None:
    """Check a login and password against the directory. Returns the identity, or None when
    they are wrong. Raises ProviderError when the directory cannot be used or the person
    tried too often. The password is used for this one bind and never kept."""
    config = load_config().get("ldap")
    if config is None:
        raise ProviderError("LDAP n'est pas configuré sur ce serveur.")
    login = login.strip()
    # An empty password would succeed as an anonymous bind on many servers: never let it through.
    if not login or not password:
        return None
    key = f"{client_ip}|{login.lower()}"
    if _throttled(key) or _throttled(f"{client_ip}|*"):
        raise ProviderError("Trop d'essais : patientez quelques minutes.")
    _ldap_attempts.setdefault(key, []).append(time.time())
    _ldap_attempts.setdefault(f"{client_ip}|*", []).append(time.time())

    from ldap3 import SUBTREE, Connection, Server, Tls
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.conv import escape_filter_chars

    template = config.get(
        "user_filter",
        "(&(objectClass=person)(|(mail={login})(uid={login})(sAMAccountName={login})))",
    )
    flt = template.replace("{login}", escape_filter_chars(login))
    email_attr = config.get("email_attribute", "mail")
    attributes = [email_attr, "givenName", "sn", "cn", "displayName", "entryUUID", "objectGUID"]
    try:
        if ldap_connect is not None:
            service = ldap_connect(config["bind_dn"], config["bind_password"])
            connect_user: Callable[[str, str], Any] = lambda dn, pw: ldap_connect(dn, pw)  # noqa: E731
        else:
            import ssl
            from urllib.parse import urlparse

            url = urlparse(config["server_url"])
            secure = url.scheme == "ldaps"
            tls = (
                Tls(
                    validate=ssl.CERT_NONE
                    if config.get("insecure_skip_verify") == "true"
                    else ssl.CERT_REQUIRED
                )
                if secure
                else None
            )
            server = Server(
                url.hostname or "",
                port=url.port or (636 if secure else 389),
                use_ssl=secure,
                tls=tls,
                connect_timeout=10,
            )

            def connect_user(dn: str, pw: str) -> Any:
                return Connection(server, user=dn, password=pw, receive_timeout=20)

            service = connect_user(config["bind_dn"], config["bind_password"])
        if not service.bind():
            raise ProviderError(
                "Le compte de service LDAP est refusé : contactez l'administrateur."
            )
        service.search(
            config["base_dn"], flt, search_scope=SUBTREE, attributes=attributes, size_limit=2
        )
        entries = [e for e in (service.response or []) if e.get("type") == "searchResEntry"]
        service.unbind()
        # Not found, or ambiguous: the same answer as a wrong password.
        if len(entries) != 1:
            return None
        entry = entries[0]
        user_connection = connect_user(entry["dn"], password)
        ok = bool(user_connection.bind())
        try:
            user_connection.unbind()
        except LDAPException:
            pass
        if not ok:
            return None
    except LDAPException as exc:
        logger.warning("ldap login failed: %s", type(exc).__name__)
        raise ProviderError("Impossible de joindre l'annuaire LDAP.") from exc

    attrs = entry.get("attributes", {})

    def first(name: str) -> str:
        value = attrs.get(name)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        return "" if value is None else str(value)

    email = first(email_attr).lower()
    if "@" not in email:
        raise ProviderError("Ce compte LDAP n'a pas d'adresse e-mail : connexion impossible.")
    given, family = first("givenName"), first("sn")
    if not given and not family:
        given, family = _split(first("displayName") or first("cn") or email)
    _ldap_attempts.pop(key, None)
    return {
        "sub": f"ldap:{first('entryUUID') or first('objectGUID') or entry['dn'].lower()}",
        "email": email,
        "given_name": given,
        "family_name": family,
    }
