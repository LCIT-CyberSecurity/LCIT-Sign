"""Who signs as "Signataire N" in a campaign, and in which order.

The editor only numbers the roles of a document. At launch each number gets a
person (FIXED) or "every recipient" (EACH). Roles sign in order: the person of
role 2 is asked only once role 1 has signed, and their copy then carries the
earlier signature. EACH is always the last role, so a fixed signer's signature
(the RSSI's, say) is the same on every copy.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.models.campaign import (
    AssignmentStatus,
    Campaign,
    CampaignRole,
    SignatureAssignment,
)
from lcit_sign.models.document import DocumentField
from lcit_sign.models.mail import NotificationType
from lcit_sign.models.user import User
from lcit_sign.services.notification_queue import enqueue_notification

Mode = Literal["FIXED", "EACH"]


class RoleError(ValueError):
    """The roles given for a campaign cannot be launched; the message says why."""


@dataclass(frozen=True)
class RoleSpec:
    role: int
    mode: Mode
    user_id: uuid.UUID | None = None
    label: str = ""


def roles_by_version(db: DbSession, version_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[int]]:
    """For each document version, the roles that have an element to fill on it
    (role 1 alone when nothing was prepared). Ascending."""
    found: dict[uuid.UUID, set[int]] = {v: set() for v in version_ids}
    for version_id, role in db.execute(
        select(DocumentField.document_version_id, DocumentField.role)
        .where(DocumentField.document_version_id.in_(version_ids))
        .distinct()
    ):
        found[version_id].add(role)
    return {v: sorted(roles or {1}) for v, roles in found.items()}


def roles_required(db: DbSession, campaign: Campaign) -> int:
    """How many "Signataire N" the campaign's documents ask for."""
    per_version = roles_by_version(db, [d.document_version_id for d in campaign.documents])
    return max((max(r) for r in per_version.values()), default=1)


def validate_roles(
    db: DbSession, campaign: Campaign, given: list[RoleSpec]
) -> list[RoleSpec]:
    """The complete, checked list of roles for the campaign. With no roles given,
    a campaign whose documents have a single signer defaults to "every recipient"
    (what it always did)."""
    needed = roles_required(db, campaign)
    if not given:
        if needed > 1:
            raise RoleError(
                f"Ces documents prévoient {needed} signataires : indiquez qui est "
                "chacun d'eux avant de lancer."
            )
        return [RoleSpec(role=1, mode="EACH")]

    by_number = {spec.role: spec for spec in given}
    if len(by_number) != len(given):
        raise RoleError("Un même signataire est défini deux fois.")
    expected = list(range(1, needed + 1))
    if sorted(by_number) != expected:
        raise RoleError(
            "Il faut définir exactement les signataires "
            + ", ".join(f"« Signataire {n} »" for n in expected)
            + "."
        )
    each = [spec for spec in given if spec.mode == "EACH"]
    if len(each) > 1:
        raise RoleError("Un seul signataire peut être « chaque destinataire ».")
    if each and each[0].role != needed:
        raise RoleError(
            "« Chaque destinataire » doit être le dernier signataire : "
            "les signataires fixes (le RSSI par exemple) signent avant."
        )
    fixed_ids: list[uuid.UUID] = []
    for spec in given:
        if spec.mode == "FIXED":
            if spec.user_id is None:
                raise RoleError(f"Choisissez une personne pour le signataire {spec.role}.")
            fixed_ids.append(spec.user_id)
        elif spec.user_id is not None:
            raise RoleError("« Chaque destinataire » n'a pas de personne associée.")
    if len(set(fixed_ids)) != len(fixed_ids):
        raise RoleError("Une même personne ne peut pas tenir deux rôles de signataire.")
    active = set(
        db.execute(select(User.id).where(User.id.in_(fixed_ids), User.active.is_(True))).scalars()
    )
    if active != set(fixed_ids):
        raise RoleError("Un signataire choisi n'existe pas ou est désactivé.")
    return sorted(given, key=lambda spec: spec.role)


def save_roles(db: DbSession, campaign: Campaign, specs: list[RoleSpec]) -> None:
    for spec in specs:
        db.add(
            CampaignRole(
                campaign_id=campaign.id,
                role=spec.role,
                label=spec.label.strip()[:100],
                mode=spec.mode,
                user_id=spec.user_id,
            )
        )


def load_roles(db: DbSession, campaign_id: uuid.UUID) -> list[CampaignRole]:
    return list(
        db.execute(
            select(CampaignRole)
            .where(CampaignRole.campaign_id == campaign_id)
            .order_by(CampaignRole.role)
        ).scalars()
    )


def role_label(role: CampaignRole | None, number: int) -> str:
    base = f"Signataire {number}"
    return f"{base} — {role.label}" if role and role.label else base


def release_next_role(
    db: DbSession,
    campaign_id: uuid.UUID,
    version_id: uuid.UUID,
    finished_role: int,
    *,
    document_title: str,
    campaign_name: str,
    signed_by: str,
    public_base_url: str,
) -> int:
    """After a signature, ask the next role of that document — once every
    assignment of the finished role is signed. Returns how many people were
    notified."""
    still_open = db.execute(
        select(func.count()).where(
            SignatureAssignment.campaign_id == campaign_id,
            SignatureAssignment.document_version_id == version_id,
            SignatureAssignment.role == finished_role,
            SignatureAssignment.status != AssignmentStatus.SIGNED,
        )
    ).scalar_one()
    if still_open:
        return 0
    next_role = db.execute(
        select(func.min(SignatureAssignment.role)).where(
            SignatureAssignment.campaign_id == campaign_id,
            SignatureAssignment.document_version_id == version_id,
            SignatureAssignment.role > finished_role,
            SignatureAssignment.status == AssignmentStatus.WAITING,
        )
    ).scalar_one()
    if next_role is None:
        return 0
    waiting = list(
        db.execute(
            select(SignatureAssignment).where(
                SignatureAssignment.campaign_id == campaign_id,
                SignatureAssignment.document_version_id == version_id,
                SignatureAssignment.role == next_role,
                SignatureAssignment.status == AssignmentStatus.WAITING,
            )
        ).scalars()
    )
    users = {
        u.id: u
        for u in db.execute(
            select(User).where(User.id.in_([a.user_id for a in waiting]))
        ).scalars()
    }
    for assignment in waiting:
        assignment.status = AssignmentStatus.PENDING
        person = users.get(assignment.user_id)
        if person is None:
            continue
        enqueue_notification(
            db,
            notification_type=NotificationType.DOCUMENT_TO_SIGN,
            recipient_email=person.email,
            recipient_user_id=person.id,
            subject=f"Document à signer : {document_title}",
            body_text=(
                f"Bonjour {person.display_name},\n\n"
                f'{signed_by} a signé le document "{document_title}" ({campaign_name}) : '
                f"c'est maintenant à votre tour.\n"
                f"Connectez-vous à LCIT Sign pour le consulter et le signer : "
                f"{public_base_url}\n"
            ),
        )
    return len(waiting)


def waiting_on(db: DbSession, assignment: SignatureAssignment) -> list[str]:
    """Names of the people an assignment is waiting for (earlier roles not yet signed)."""
    rows = db.execute(
        select(User.display_name)
        .join(SignatureAssignment, SignatureAssignment.user_id == User.id)
        .where(
            SignatureAssignment.campaign_id == assignment.campaign_id,
            SignatureAssignment.document_version_id == assignment.document_version_id,
            SignatureAssignment.role < assignment.role,
            SignatureAssignment.status != AssignmentStatus.SIGNED,
        )
        .order_by(SignatureAssignment.role)
    ).scalars()
    return list(rows)
