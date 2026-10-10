from __future__ import annotations

import httpx

from lcit_sign.services.directory import diagnostics as diag

# What Microsoft's token endpoint is telling us, in terms of what to go and fix.
# Only the error code and our own wording are shown: never the raw response, and
# of course never the secret.
_HINTS: dict[int, str] = {
    7000215: (
        "le secret client est invalide. Dans Entra → Certificats et secrets, copiez la colonne "
        "« Valeur » (et non « ID du secret »), sans espace avant ou après"
    ),
    7000222: "le secret client a expiré : créez-en un nouveau dans Entra → Certificats et secrets",
    700016: (
        "l'application est introuvable dans ce tenant : vérifiez l'« ID de l'application "
        "(client) » (et non l'« ID d'objet ») et l'« ID du tenant »"
    ),
    90002: "le tenant est introuvable : vérifiez l'« ID du tenant »",
    900023: "l'« ID du tenant » n'a pas un format valide",
    700025: (
        "l'application est déclarée « client public » : dans Entra → Authentification, "
        "désactivez « Autoriser les flux clients publics »"
    ),
    7000218: "l'application attend un certificat ou un secret : aucun secret n'a été envoyé",
    53003: "un accès conditionnel bloque cette application",
    70011: "l'étendue demandée est refusée pour cette application",
}


def describe_token_error(response: httpx.Response) -> str:
    """A short, actionable sentence for a failed token request."""
    code: int | None = None
    try:
        data = response.json()
        codes = data.get("error_codes") or []
        if codes:
            code = int(codes[0])
    except (ValueError, TypeError, AttributeError):
        pass
    label = f"AADSTS{code}" if code is not None else f"HTTP {response.status_code}"
    hint = _HINTS.get(code) if code is not None else None
    if hint is None and response.status_code in (400, 401):
        hint = "identifiants refusés (ID de l'application, secret ou tenant incorrect)"
    return f"Microsoft a refusé la connexion ({label}) : {hint or 'erreur inattendue'}"


# The same codes as above, structured for the connection test: our own code, what happened,
# and what to do. Only the code and our wording are shown.
_PROBLEMS: dict[int, tuple[str, str, str]] = {
    7000215: (
        diag.INVALID_CREDENTIALS,
        "Le secret client est invalide.",
        "Dans Entra > Certificats et secrets, copiez la colonne « Valeur » (et non « ID du "
        "secret »), sans espace avant ou après.",
    ),
    7000222: (
        diag.SECRET_EXPIRED,
        "Le secret client a expiré.",
        "Créer un nouveau secret dans Entra > Certificats et secrets.",
    ),
    700016: (
        diag.INVALID_CONFIGURATION,
        "L'application est introuvable dans ce tenant.",
        "Vérifiez l'ID de l'application (client), et non l'ID d'objet, ainsi que l'ID du tenant.",
    ),
    90002: (
        diag.TENANT_NOT_FOUND,
        "Le tenant est introuvable.",
        "Vérifiez l'ID du tenant (Entra > Vue d'ensemble).",
    ),
    900023: (
        diag.INVALID_CONFIGURATION,
        "L'ID du tenant n'a pas un format valide.",
        "Utilisez l'ID de locataire (GUID) ou le domaine .onmicrosoft.com.",
    ),
    700025: (
        diag.INVALID_CONFIGURATION,
        "L'application est déclarée « client public ».",
        "Dans Entra > Authentification, désactivez « Autoriser les flux clients publics ».",
    ),
    7000218: (
        diag.INVALID_CONFIGURATION,
        "Aucun secret n'a été reçu pour cette application.",
        "Saisissez la valeur du secret client dans le connecteur.",
    ),
    53003: (
        diag.AUTH_FAILED,
        "Un accès conditionnel bloque cette application.",
        "Ajoutez une exception pour cette application dans l'accès conditionnel d'Entra.",
    ),
    70011: (
        diag.INVALID_CONFIGURATION,
        "L'étendue demandée est refusée pour cette application.",
        "Vérifiez les permissions de type Application accordées à l'application dans Entra.",
    ),
}


def classify_token_error(response: httpx.Response) -> diag.CheckResult:
    """The connection test's view of a refused token request. Never echoes the body."""
    number: int | None = None
    try:
        codes = response.json().get("error_codes") or []
        if codes:
            number = int(codes[0])
    except (ValueError, TypeError, AttributeError):
        pass
    provider = f"AADSTS{number}" if number is not None else f"HTTP {response.status_code}"
    known = _PROBLEMS.get(number) if number is not None else None
    if known:
        code, message, action = known
        return diag.fail("authentication", code, message, provider_code=provider, action=action)
    return diag.fail(
        "authentication",
        diag.AUTH_FAILED,
        "Microsoft a refusé l'authentification.",
        provider_code=provider,
        action="Vérifiez l'ID du tenant, l'ID de l'application et le secret client.",
    )
