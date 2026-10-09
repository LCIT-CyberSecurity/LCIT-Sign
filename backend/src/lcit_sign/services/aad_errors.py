from __future__ import annotations

import httpx

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
