"""Changing a campaign after it was sent: more people, fewer people, one more document.

What was signed stays signed (it is evidence): only what is still outstanding can be
cancelled. A newcomer gets a copy of every document, in the role of "every recipient";
a waiting copy becomes theirs to sign when the earlier signers (the RSSI) have signed.
Fixed signers are not changed here.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.models.campaign import AssignmentStatus, Campaign, SignatureAssignment
from lcit_sign.models.document import Document, DocumentVersion
from lcit_sign.models.mail import NotificationType
from lcit_sign.models.user import User
from lcit_sign.services.campaign_roles import load_roles, roles_by_version
from lcit_sign.services.notification_queue import enqueue_notification
from lcit_sign.services.signing_mail import to_sign_message

OUTSTANDING = (AssignmentStatus.WAITING, AssignmentStatus.PENDING, AssignmentStatus.VIEWED)


class ChangeError(ValueError):
    """The change is not possible; the message says why."""


def each_role(db: DbSession, campaign: Campaign) -> int | None:
    return next((r.role for r in load_roles(db, campaign.id) if r.mode == "EACH"), None)


def recipients(db: DbSession, campaign: Campaign) -> list[uuid.UUID]:
    """The people currently asked as "every recipient" (not cancelled)."""
    role = each_role(db, campaign)
    if role is None:
        return []
    return list(
        db.execute(
            select(SignatureAssignment.user_id)
            .where(
                SignatureAssignment.campaign_id == campaign.id,
                SignatureAssignment.role == role,
                SignatureAssignment.status != AssignmentStatus.CANCELLED,
            )
            .distinct()
        ).scalars()
    )


def _their_turn(db: DbSession, campaign: Campaign, version_id: uuid.UUID, role: int) -> bool:
    """Whether every earlier role of this document has signed already."""
    unsigned_before = db.execute(
        select(func.count()).where(
            SignatureAssignment.campaign_id == campaign.id,
            SignatureAssignment.document_version_id == version_id,
            SignatureAssignment.role < role,
            SignatureAssignment.status != AssignmentStatus.SIGNED,
        )
    ).scalar_one()
    return unsigned_before == 0


def _notify(
    db: DbSession, campaign: Campaign, person: User, title: str, public_base_url: str
) -> None:
    subject, body = to_sign_message(
        person, title=title, campaign_name=campaign.name, public_base_url=public_base_url
    )
    enqueue_notification(
        db,
        notification_type=NotificationType.DOCUMENT_TO_SIGN,
        recipient_email=person.email,
        recipient_user_id=person.id,
        subject=subject,
        body_text=body,
    )


def _title(db: DbSession, version_id: uuid.UUID) -> str:
    version = db.get(DocumentVersion, version_id)
    document = db.get(Document, version.document_id) if version else None
    return document.title if document else "document"


def add_recipients(
    db: DbSession, campaign: Campaign, user_ids: list[uuid.UUID], *, public_base_url: str
) -> int:
    """Ask more people, on every document already sent. Returns how many were added
    (someone already asked is left alone; someone removed earlier is asked again)."""
    role = each_role(db, campaign)
    if role is None:
        raise ChangeError(
            "Cette campagne n'a pas de liste de destinataires : "
            "tous ses signataires sont des personnes précises."
        )
    fixed = {r.user_id for r in load_roles(db, campaign.id) if r.user_id}
    people = {
        u.id: u
        for u in db.execute(
            select(User).where(User.id.in_(user_ids), User.active.is_(True))
        ).scalars()
    }
    added = 0
    for user_id in dict.fromkeys(user_ids):
        person = people.get(user_id)
        if person is None or user_id in fixed:
            continue
        touched = False
        for link in campaign.documents:
            version_id = link.document_version_id
            if role not in roles_by_version(db, [version_id])[version_id]:
                continue
            if _released(db, campaign, version_id) is False:
                continue  # a document not sent yet will reach them when it is
            existing = db.execute(
                select(SignatureAssignment).where(
                    SignatureAssignment.campaign_id == campaign.id,
                    SignatureAssignment.document_version_id == version_id,
                    SignatureAssignment.user_id == user_id,
                )
            ).scalar_one_or_none()
            if existing is not None and existing.status != AssignmentStatus.CANCELLED:
                continue
            my_turn = _their_turn(db, campaign, version_id, role)
            status = AssignmentStatus.PENDING if my_turn else AssignmentStatus.WAITING
            if existing is None:
                db.add(
                    SignatureAssignment(
                        campaign_id=campaign.id,
                        document_version_id=version_id,
                        user_id=user_id,
                        role=role,
                        status=status,
                        deadline=campaign.deadline,
                    )
                )
            else:  # asked again after having been removed
                existing.status = status
                existing.role = role
                existing.first_viewed_at = None
                existing.deadline = campaign.deadline
            touched = True
            if my_turn:
                _notify(db, campaign, person, _title(db, version_id), public_base_url)
        added += 1 if touched else 0
    return added


def remove_recipient(db: DbSession, campaign: Campaign, user_id: uuid.UUID) -> int:
    """Stop asking someone: what they have not signed is cancelled; what they have
    signed stays (it is evidence). Returns how many copies were cancelled."""
    role = each_role(db, campaign)
    if role is None:
        raise ChangeError("Cette campagne n'a pas de liste de destinataires.")
    if user_id in {r.user_id for r in load_roles(db, campaign.id) if r.user_id}:
        raise ChangeError(
            "Un signataire désigné ne se retire pas ici : annulez la campagne "
            "et recréez-la avec un autre signataire."
        )
    cancelled = 0
    for assignment in db.execute(
        select(SignatureAssignment).where(
            SignatureAssignment.campaign_id == campaign.id,
            SignatureAssignment.user_id == user_id,
            SignatureAssignment.role == role,
            SignatureAssignment.status.in_(OUTSTANDING),
        )
    ).scalars():
        assignment.status = AssignmentStatus.CANCELLED
        cancelled += 1
    return cancelled


def _released(db: DbSession, campaign: Campaign, version_id: uuid.UUID) -> bool:
    return (
        db.execute(
            select(func.count()).where(
                SignatureAssignment.campaign_id == campaign.id,
                SignatureAssignment.document_version_id == version_id,
            )
        ).scalar_one()
        > 0
    )


def is_released(db: DbSession, campaign: Campaign, version_id: uuid.UUID) -> bool:
    return _released(db, campaign, version_id)


def release_document(
    db: DbSession, campaign: Campaign, version_id: uuid.UUID, *, public_base_url: str
) -> int:
    """Send a document added after the launch: a copy for each signer role, in order
    (the first role is asked now, the others wait their turn). Returns the copies made.
    The version must already be published."""
    if _released(db, campaign, version_id):
        raise ChangeError("Ce document est déjà envoyé.")
    configured = {r.role: r for r in load_roles(db, campaign.id)}
    used = roles_by_version(db, [version_id])[version_id]
    if not set(used) <= set(configured):
        raise ChangeError(
            "Ce document prévoit plus de signataires que la campagne : "
            "placez ses éléments sur les signataires existants."
        )
    crowd = recipients(db, campaign)
    title = _title(db, version_id)
    first = used[0]
    made = 0
    for role in used:
        spec = configured[role]
        people = [spec.user_id] if spec.mode == "FIXED" and spec.user_id else crowd
        users = {
            u.id: u
            for u in db.execute(select(User).where(User.id.in_(people))).scalars()
        }
        for user_id in people:
            my_turn = role == first
            db.add(
                SignatureAssignment(
                    campaign_id=campaign.id,
                    document_version_id=version_id,
                    user_id=user_id,
                    role=role,
                    status=AssignmentStatus.PENDING if my_turn else AssignmentStatus.WAITING,
                    deadline=campaign.deadline,
                )
            )
            made += 1
            if my_turn and user_id in users:
                _notify(db, campaign, users[user_id], title, public_base_url)
    return made
