"""The "a document is waiting for your signature" e-mail, written once. Sent when a request
starts, when an earlier signer has signed, and when someone is added afterwards."""
from __future__ import annotations

from lcit_sign.models.user import User


def to_sign_message(
    person: User,
    *,
    title: str,
    campaign_name: str,
    public_base_url: str,
    signed_by: str | None = None,
) -> tuple[str, str]:
    """(subject, body). `signed_by` is set when it is this person's turn because someone signed
    before them. A person from outside the company is told they have nothing to create: they
    sign in with the address this was sent to."""
    if signed_by:
        why = (
            f'{signed_by} a signé le document "{title}" ({campaign_name}) : '
            "c'est maintenant à votre tour."
        )
    else:
        why = f'Un document "{title}" ({campaign_name}) attend votre signature.'
    lines = [f"Bonjour {person.display_name},", "", why]
    lines.append(f"Connectez-vous à LCIT Sign pour le consulter et le signer : {public_base_url}")
    if person.external:
        lines += [
            "",
            "Vous n'avez aucun compte à créer : connectez-vous avec cette adresse e-mail "
            f"({person.email}), avec votre compte Microsoft ou Google.",
        ]
    return f"Document à signer : {title}", "\n".join(lines) + "\n"
