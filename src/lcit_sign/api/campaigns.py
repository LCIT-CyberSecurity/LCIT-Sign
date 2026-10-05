from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.config import Settings
from lcit_sign.deps import get_current_user, get_db, require_roles
from lcit_sign.models.campaign import (
    AssignmentStatus,
    Campaign,
    CampaignDocument,
    CampaignStatus,
    CampaignTargetGroup,
    CampaignTargetMode,
    CampaignTargetUser,
    SignatureAssignment,
)
from lcit_sign.models.directory import GroupMembership
from lcit_sign.models.document import Document, DocumentVersion, DocumentVersionStatus
from lcit_sign.models.mail import NotificationType
from lcit_sign.models.user import Role, User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.notification_queue import enqueue_notification

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

_manage = require_roles(Role.OPERATOR, Role.ADMIN)


class CreateCampaignRequest(BaseModel):
    name: str
    description: str = ""


class AddDocumentRequest(BaseModel):
    document_version_id: uuid.UUID


class TargetRequest(BaseModel):
    # Groups and explicit users combine (spec §33's "groupes + utilisateurs
    # supplémentaires"); all_users, when true, wins over both.
    all_users: bool = False
    group_ids: list[uuid.UUID] = []
    user_ids: list[uuid.UUID] = []


class LaunchRequest(TargetRequest):
    deadline: datetime | None = None


def _resolve_population(
    db: DbSession, *, all_users: bool, group_ids: list[uuid.UUID], user_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Compute the target user set. Deliberately resolved fresh each call —
    the campaign only *freezes* it at launch time, by copying the result
    into SignatureAssignment rows (spec §34).
    """
    if all_users:
        return list(db.execute(select(User.id).where(User.active.is_(True))).scalars())

    population: set[uuid.UUID] = set()
    if group_ids:
        population |= set(
            db.execute(
                select(GroupMembership.user_id)
                .join(User, GroupMembership.user_id == User.id)
                .where(GroupMembership.group_id.in_(group_ids), User.active.is_(True))
            ).scalars()
        )
    if user_ids:
        population |= set(
            db.execute(
                select(User.id).where(User.id.in_(user_ids), User.active.is_(True))
            ).scalars()
        )
    return list(population)


def _target_mode_label(
    *, all_users: bool, group_ids: list[uuid.UUID], user_ids: list[uuid.UUID]
) -> str:
    if all_users:
        return CampaignTargetMode.ALL_USERS.value
    if group_ids and user_ids:
        return CampaignTargetMode.GROUPS_AND_USERS.value
    if group_ids:
        return CampaignTargetMode.GROUPS.value
    return CampaignTargetMode.SPECIFIC_USERS.value


def _campaign_payload(campaign: Campaign, db: DbSession) -> dict[str, Any]:
    raw_counts = dict(
        db.execute(
            select(SignatureAssignment.status, func.count())
            .where(SignatureAssignment.campaign_id == campaign.id)
            .group_by(SignatureAssignment.status)
        ).all()
    )
    return {
        "id": str(campaign.id),
        "name": campaign.name,
        "description": campaign.description,
        "status": campaign.status.value,
        "target_mode": campaign.target_mode,
        "created_at": campaign.created_at.isoformat(),
        "launch_at": campaign.launch_at.isoformat() if campaign.launch_at else None,
        "deadline": campaign.deadline.isoformat() if campaign.deadline else None,
        "closed_at": campaign.closed_at.isoformat() if campaign.closed_at else None,
        "document_version_ids": [str(d.document_version_id) for d in campaign.documents],
        "assignment_counts": {
            status.value: raw_counts.get(status, 0) for status in AssignmentStatus
        },
    }


@router.post("", status_code=201)
def create_campaign(
    body: CreateCampaignRequest, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    campaign = Campaign(name=body.name, description=body.description, created_by=user.id)
    db.add(campaign)
    db.flush()
    append_audit_event(
        db, action="CAMPAIGN_CREATED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
    )
    db.commit()
    return _campaign_payload(campaign, db)


def _get_draft_campaign(db: DbSession, campaign_id: uuid.UUID) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    if campaign.status != CampaignStatus.DRAFT:
        raise HTTPException(409, "Campaign is no longer a draft")
    return campaign


@router.post("/{campaign_id}/documents", status_code=201)
def add_campaign_document(
    campaign_id: uuid.UUID,
    body: AddDocumentRequest,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    campaign = _get_draft_campaign(db, campaign_id)
    version = db.get(DocumentVersion, body.document_version_id)
    if version is None or version.status != DocumentVersionStatus.PUBLISHED:
        raise HTTPException(400, "Only a published document version can be added to a campaign")

    exists = db.get(CampaignDocument, (campaign.id, version.id))
    if exists is None:
        db.add(CampaignDocument(campaign_id=campaign.id, document_version_id=version.id))
        append_audit_event(
            db, action="CAMPAIGN_UPDATED", actor_id=user.id,
            target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
            document_id=version.document_id, metadata={"change": "document_added"},
        )
        db.commit()
    return _campaign_payload(campaign, db)


@router.post("/{campaign_id}/targets/preview")
def preview_targets(
    campaign_id: uuid.UUID,
    body: TargetRequest,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    _get_draft_campaign(db, campaign_id)
    population = _resolve_population(
        db, all_users=body.all_users, group_ids=body.group_ids, user_ids=body.user_ids
    )
    return {"population_count": len(population), "user_ids": [str(u) for u in population]}


@router.post("/{campaign_id}/launch")
def launch_campaign(
    request: Request,
    campaign_id: uuid.UUID,
    body: LaunchRequest,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    campaign = _get_draft_campaign(db, campaign_id)
    if not campaign.documents:
        raise HTTPException(400, "Campaign has no documents to sign")

    population = _resolve_population(
        db, all_users=body.all_users, group_ids=body.group_ids, user_ids=body.user_ids
    )
    if not population:
        raise HTTPException(400, "Target population is empty")

    campaign.target_mode = _target_mode_label(
        all_users=body.all_users, group_ids=body.group_ids, user_ids=body.user_ids
    )
    if not body.all_users:
        for group_id in body.group_ids:
            db.add(CampaignTargetGroup(campaign_id=campaign.id, group_id=group_id))
        for target_user_id in body.user_ids:
            db.add(CampaignTargetUser(campaign_id=campaign.id, user_id=target_user_id))

    settings: Settings = request.app.state.settings
    population_users = db.execute(select(User).where(User.id.in_(population))).scalars()
    users_by_id = {u.id: u for u in population_users}

    for campaign_document in campaign.documents:
        version = db.get(DocumentVersion, campaign_document.document_version_id)
        document = db.get(Document, version.document_id) if version else None
        document_title = document.title if document else "document"

        for target_user_id in population:
            db.add(
                SignatureAssignment(
                    campaign_id=campaign.id,
                    document_version_id=campaign_document.document_version_id,
                    user_id=target_user_id,
                    deadline=body.deadline,
                )
            )
            target_user = users_by_id.get(target_user_id)
            if target_user is not None:
                enqueue_notification(
                    db,
                    notification_type=NotificationType.DOCUMENT_TO_SIGN,
                    recipient_email=target_user.email,
                    recipient_user_id=target_user.id,
                    subject=f"Document à signer : {document_title}",
                    body_text=(
                        f"Bonjour {target_user.display_name},\n\n"
                        f'Un document "{document_title}" ({campaign.name}) '
                        f"attend votre signature.\n"
                        f"Connectez-vous à LCIT Sign pour le consulter et le signer : "
                        f"{settings.public_base_url}\n"
                    ),
                )

    campaign.status = CampaignStatus.ACTIVE
    campaign.launch_at = datetime.now(UTC)
    if body.deadline:
        campaign.deadline = body.deadline

    append_audit_event(
        db, action="CAMPAIGN_STARTED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
        metadata={"population": len(population), "documents": len(campaign.documents)},
    )
    db.commit()
    return _campaign_payload(campaign, db)


@router.post("/{campaign_id}/remind")
def remind_campaign(
    request: Request,
    campaign_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Manual reminder (spec §83): queues one REMINDER email per
    still-outstanding assignment. Someone who already signed is never
    nagged again — only PENDING/VIEWED assignments qualify.
    """
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    if campaign.status != CampaignStatus.ACTIVE:
        raise HTTPException(409, "Only an active campaign can send reminders")

    settings: Settings = request.app.state.settings
    outstanding = db.execute(
        select(SignatureAssignment, User)
        .join(User, SignatureAssignment.user_id == User.id)
        .where(
            SignatureAssignment.campaign_id == campaign.id,
            SignatureAssignment.status.in_([AssignmentStatus.PENDING, AssignmentStatus.VIEWED]),
        )
    ).all()

    now = datetime.now(UTC)
    for assignment, target_user in outstanding:
        enqueue_notification(
            db,
            notification_type=NotificationType.REMINDER,
            recipient_email=target_user.email,
            recipient_user_id=target_user.id,
            related_assignment_id=assignment.id,
            subject=f"Rappel : document à signer — {campaign.name}",
            body_text=(
                f"Bonjour {target_user.display_name},\n\n"
                f'Il vous reste un document à signer pour la campagne "{campaign.name}".\n'
                f"Connectez-vous à LCIT Sign pour le consulter et le signer : "
                f"{settings.public_base_url}\n"
            ),
        )
        assignment.last_reminder_at = now
        assignment.reminder_count += 1

    append_audit_event(
        db, action="CAMPAIGN_UPDATED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
        metadata={"change": "reminder_sent", "count": len(outstanding)},
    )
    db.commit()
    return {"reminders_queued": len(outstanding)}


@router.post("/{campaign_id}/close")
def close_campaign(
    campaign_id: uuid.UUID, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    if campaign.status != CampaignStatus.ACTIVE:
        raise HTTPException(409, "Only an active campaign can be closed")

    campaign.status = CampaignStatus.CLOSED
    campaign.closed_at = datetime.now(UTC)
    append_audit_event(
        db, action="CAMPAIGN_CLOSED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
    )
    db.commit()
    return _campaign_payload(campaign, db)


@router.post("/{campaign_id}/cancel")
def cancel_campaign(
    campaign_id: uuid.UUID, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.ACTIVE):
        raise HTTPException(409, "Campaign cannot be cancelled from its current status")

    campaign.status = CampaignStatus.CANCELLED
    append_audit_event(
        db, action="CAMPAIGN_CANCELLED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
    )
    db.commit()
    return _campaign_payload(campaign, db)


@router.get("")
def list_campaigns(
    user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> list[dict[str, Any]]:
    campaigns = db.execute(select(Campaign).order_by(Campaign.created_at.desc())).scalars()
    return [_campaign_payload(c, db) for c in campaigns]


@router.get("/{campaign_id}")
def get_campaign(
    campaign_id: uuid.UUID, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    return _campaign_payload(campaign, db)


@router.get("/{campaign_id}/assignments")
def list_campaign_assignments(
    campaign_id: uuid.UUID,
    status: AssignmentStatus | None = None,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> list[dict[str, Any]]:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")

    stmt = (
        select(SignatureAssignment, User)
        .join(User, SignatureAssignment.user_id == User.id)
        .where(SignatureAssignment.campaign_id == campaign_id)
    )
    if status is not None:
        stmt = stmt.where(SignatureAssignment.status == status)
    rows = db.execute(stmt).all()
    return [
        {
            "id": str(assignment.id),
            "document_version_id": str(assignment.document_version_id),
            "user_id": str(assignment.user_id),
            "user_email": target_user.email,
            "user_display_name": target_user.display_name,
            "status": assignment.status.value,
            "assigned_at": assignment.assigned_at.isoformat(),
            "first_viewed_at": assignment.first_viewed_at.isoformat()
            if assignment.first_viewed_at
            else None,
            "signed_at": assignment.signed_at.isoformat() if assignment.signed_at else None,
            "deadline": assignment.deadline.isoformat() if assignment.deadline else None,
            "reminder_count": assignment.reminder_count,
        }
        for assignment, target_user in rows
    ]


me_router = APIRouter(tags=["campaigns"])


@me_router.get("/me/assignments")
def list_my_assignments(
    user: User = Depends(get_current_user), db: DbSession = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(SignatureAssignment)
        .where(SignatureAssignment.user_id == user.id)
        .order_by(SignatureAssignment.assigned_at.desc())
    ).scalars()
    return [
        {
            "id": str(a.id),
            "campaign_id": str(a.campaign_id),
            "document_version_id": str(a.document_version_id),
            "status": a.status.value,
            "assigned_at": a.assigned_at.isoformat(),
            "deadline": a.deadline.isoformat() if a.deadline else None,
            "signed_at": a.signed_at.isoformat() if a.signed_at else None,
        }
        for a in rows
    ]
