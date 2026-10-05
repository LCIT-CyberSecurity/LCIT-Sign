from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
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
from lcit_sign.models.directory import Group, GroupMembership
from lcit_sign.models.document import Document, DocumentVersion, DocumentVersionStatus
from lcit_sign.models.mail import Notification, NotificationType
from lcit_sign.models.report import Report
from lcit_sign.models.signature import Signature
from lcit_sign.models.user import Role, User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.campaign_launch import create_assignments
from lcit_sign.services.campaign_roles import (
    RoleError,
    RoleSpec,
    load_roles,
    role_label,
    roles_required,
    save_roles,
    validate_roles,
    waiting_on,
)
from lcit_sign.services.notification_queue import enqueue_notification

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

_manage = require_roles(Role.OPERATOR, Role.ADMIN)


@router.get("/_meta/users")
def list_targetable_users(
    user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> list[dict[str, Any]]:
    """A minimal, OPERATOR-reachable user picker for campaign targeting
    (spec §33) — deliberately thinner than /admin/users (no roles/active
    detail), which stays ADMIN-only for actual user administration."""
    rows = db.execute(select(User).where(User.active.is_(True)).order_by(User.email)).scalars()
    return [{"id": str(u.id), "email": u.email, "display_name": u.display_name} for u in rows]


@router.get("/_meta/dashboard")
def operator_dashboard(
    user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    """Figures for the operator's overview (spec §65). `overdue` counts
    outstanding assignments whose deadline has passed; `not_viewed` those
    nobody has opened yet."""
    now = datetime.now(UTC)
    campaign_counts = dict(
        db.execute(select(Campaign.status, func.count()).group_by(Campaign.status)).all()
    )
    active_ids = select(Campaign.id).where(Campaign.status == CampaignStatus.ACTIVE)
    status_counts = dict(
        db.execute(
            select(SignatureAssignment.status, func.count())
            .where(SignatureAssignment.campaign_id.in_(active_ids))
            .group_by(SignatureAssignment.status)
        ).all()
    )
    signed = status_counts.get(AssignmentStatus.SIGNED, 0)
    pending = status_counts.get(AssignmentStatus.PENDING, 0)
    viewed = status_counts.get(AssignmentStatus.VIEWED, 0)
    waiting = status_counts.get(AssignmentStatus.WAITING, 0)
    expected = sum(status_counts.values())
    overdue = db.execute(
        select(func.count())
        .select_from(SignatureAssignment)
        .where(
            SignatureAssignment.campaign_id.in_(active_ids),
            SignatureAssignment.status.in_([AssignmentStatus.PENDING, AssignmentStatus.VIEWED]),
            SignatureAssignment.deadline.is_not(None),
            SignatureAssignment.deadline < now,
        )
    ).scalar_one()
    reminders = db.execute(
        select(func.coalesce(func.sum(SignatureAssignment.reminder_count), 0)).where(
            SignatureAssignment.campaign_id.in_(active_ids)
        )
    ).scalar_one()
    return {
        "campaigns": {
            "active": campaign_counts.get(CampaignStatus.ACTIVE, 0),
            "closed": campaign_counts.get(CampaignStatus.CLOSED, 0),
            "draft": campaign_counts.get(CampaignStatus.DRAFT, 0),
        },
        "assignments": {
            "expected": expected,
            "signed": signed,
            "outstanding": pending + viewed + waiting,
            "waiting": waiting,
            "not_viewed": pending,
            "overdue": overdue,
        },
        "signature_rate": round(100 * signed / expected) if expected else None,
        "reminders_sent": int(reminders),
    }


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


POLICY_FIELDS = (
    "reminder_first_days",
    "reminder_interval_days",
    "reminder_max_count",
    "reminder_before_deadline_days",
    "renewal_every",
    "renewal_unit",
)


class RoleIn(BaseModel):
    role: int = Field(ge=1, le=10)
    mode: Literal["FIXED", "EACH"]
    user_id: uuid.UUID | None = None
    label: str = Field(default="", max_length=100)


class LaunchRequest(TargetRequest):
    # Who is "Signataire N": a named person, or the list of recipients below.
    roles: list[RoleIn] = []
    deadline: datetime | None = None
    # Reminder policy (spec §50) and renewal (spec §51); all optional.
    reminder_first_days: int | None = Field(default=None, ge=0, le=365)
    reminder_interval_days: int | None = Field(default=None, ge=1, le=365)
    reminder_max_count: int | None = Field(default=None, ge=0, le=50)
    reminder_before_deadline_days: int | None = Field(default=None, ge=0, le=365)
    renewal_every: int | None = Field(default=None, ge=1, le=3650)
    renewal_unit: Literal["DAYS", "MONTHS"] | None = None

    @model_validator(mode="after")
    def _coherent_policies(self) -> LaunchRequest:
        if (self.renewal_every is None) != (self.renewal_unit is None):
            raise ValueError("renewal_every and renewal_unit go together")
        if self.reminder_first_days is not None and self.reminder_interval_days is None:
            raise ValueError("reminder_interval_days is required with reminder_first_days")
        return self


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


def _roles_payload(db: DbSession, campaign: Campaign) -> list[dict[str, Any]]:
    """The signer roles of a campaign. Launched: who each one is. Draft: what the
    documents ask for, named as the editor named them (nobody chosen yet)."""
    configured = load_roles(db, campaign.id)
    names = {
        u.id: u.display_name
        for u in db.execute(
            select(User).where(User.id.in_([r.user_id for r in configured if r.user_id]))
        ).scalars()
    }
    if configured:
        return [
            {
                "role": r.role,
                "label": r.label,
                "mode": r.mode,
                "user_id": str(r.user_id) if r.user_id else None,
                "user_display_name": names.get(r.user_id) if r.user_id else None,
            }
            for r in configured
        ]
    labels: dict[int, str] = {}
    for d in campaign.documents:
        version = db.get(DocumentVersion, d.document_version_id)
        for key, value in ((version.role_labels if version else None) or {}).items():
            labels.setdefault(int(key), value)
    needed = roles_required(db, campaign)
    return [
        {"role": n, "label": labels.get(n, ""), "mode": None, "user_id": None,
         "user_display_name": None}
        for n in range(1, needed + 1)
    ]


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
        "delete_blockers": campaign_delete_blockers(db, campaign),
        "policies": {field: getattr(campaign, field) for field in POLICY_FIELDS},
        "renewal_of_campaign_id": (
            str(campaign.renewal_of_campaign_id) if campaign.renewal_of_campaign_id else None
        ),
        "document_version_ids": [str(d.document_version_id) for d in campaign.documents],
        "roles_required": roles_required(db, campaign),
        "roles": _roles_payload(db, campaign),
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


@router.delete("/{campaign_id}/documents/{version_id}")
def remove_campaign_document(
    campaign_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Take a document back out of a campaign that has not started."""
    campaign = _get_draft_campaign(db, campaign_id)
    link = db.get(CampaignDocument, (campaign.id, version_id))
    if link is None:
        raise HTTPException(404, "This document is not in the campaign")
    db.delete(link)
    append_audit_event(
        db, action="CAMPAIGN_UPDATED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
        metadata={"change": "document_removed", "document_version_id": str(version_id)},
    )
    db.commit()
    db.refresh(campaign)
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

    try:
        role_specs = validate_roles(
            db,
            campaign,
            [RoleSpec(r.role, r.mode, r.user_id, r.label) for r in body.roles],
        )
    except RoleError as exc:
        raise HTTPException(422, str(exc)) from exc
    has_list = any(spec.mode == "EACH" for spec in role_specs)

    population = _resolve_population(
        db, all_users=body.all_users, group_ids=body.group_ids, user_ids=body.user_ids
    )
    if has_list and not population:
        raise HTTPException(400, "Target population is empty")
    if not has_list:
        # Every signer is a named person: nobody else is asked.
        population = []

    campaign.target_mode = _target_mode_label(
        all_users=body.all_users, group_ids=body.group_ids, user_ids=body.user_ids
    )
    if not body.all_users:
        for group_id in body.group_ids:
            db.add(CampaignTargetGroup(campaign_id=campaign.id, group_id=group_id))
        for target_user_id in body.user_ids:
            db.add(CampaignTargetUser(campaign_id=campaign.id, user_id=target_user_id))

    settings: Settings = request.app.state.settings
    save_roles(db, campaign, role_specs)
    create_assignments(
        db, campaign, population, deadline=body.deadline,
        public_base_url=settings.public_base_url, roles=role_specs,
    )
    for field in POLICY_FIELDS:
        setattr(campaign, field, getattr(body, field))

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
    # Closing ends the signing: what is still outstanding can no longer be signed.
    _end_outstanding(db, campaign.id, AssignmentStatus.EXPIRED)
    append_audit_event(
        db, action="CAMPAIGN_CLOSED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
    )
    db.commit()
    return _campaign_payload(campaign, db)


def _end_outstanding(db: DbSession, campaign_id: uuid.UUID, status: AssignmentStatus) -> None:
    for assignment in db.execute(
        select(SignatureAssignment).where(
            SignatureAssignment.campaign_id == campaign_id,
            SignatureAssignment.status.in_(
                [AssignmentStatus.WAITING, AssignmentStatus.PENDING, AssignmentStatus.VIEWED]
            ),
        )
    ).scalars():
        assignment.status = status


def campaign_delete_blockers(db: DbSession, campaign: Campaign) -> list[str]:
    """Why this campaign cannot be erased. One that is running must be cancelled
    first; one that holds signatures or reports is part of the evidence trail
    and can only be archived (signatures, reports and the audit trail name it)."""
    reasons: list[str] = []
    if campaign.status == CampaignStatus.ACTIVE:
        reasons.append("elle est en cours : annulez-la d'abord")
    signed = db.execute(
        select(func.count()).select_from(Signature).where(Signature.campaign_id == campaign.id)
    ).scalar_one()
    if signed:
        reasons.append(f"{signed} signature(s) enregistrée(s)")
    reports = db.execute(
        select(func.count()).select_from(Report).where(Report.campaign_id == campaign.id)
    ).scalar_one()
    if reports:
        reasons.append(f"{reports} procès-verbal(aux)")
    return reasons


@router.delete("/{campaign_id}")
def delete_campaign(
    campaign_id: uuid.UUID, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    """Erase a campaign that never produced evidence (a draft, or one cancelled
    before anyone signed). Otherwise it is refused with the reason: archive it."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    reasons = campaign_delete_blockers(db, campaign)
    if reasons:
        raise HTTPException(
            409,
            "Cette campagne ne peut pas être supprimée (" + " ; ".join(reasons) + ")."
            + (" Archivez-la à la place." if campaign.status != CampaignStatus.ACTIVE else ""),
        )
    assignment_ids = select(SignatureAssignment.id).where(
        SignatureAssignment.campaign_id == campaign.id
    )
    # Queued e-mails about these assignments go with them.
    db.execute(delete(Notification).where(Notification.related_assignment_id.in_(assignment_ids)))
    for model in (SignatureAssignment, CampaignTargetUser, CampaignTargetGroup, CampaignDocument):
        db.execute(delete(model).where(model.campaign_id == campaign.id))
    name = campaign.name
    db.delete(campaign)
    append_audit_event(
        db, action="CAMPAIGN_DELETED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign_id), metadata={"name": name},
    )
    db.commit()
    return {"deleted": str(campaign_id)}


@router.post("/{campaign_id}/archive")
def archive_campaign(
    campaign_id: uuid.UUID, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    """Put a finished campaign away: it leaves the working list but its signatures,
    reports and audit trail stay intact and reachable."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    if campaign.status not in (CampaignStatus.CLOSED, CampaignStatus.CANCELLED):
        raise HTTPException(409, "Seule une campagne clôturée ou annulée peut être archivée")
    campaign.status = CampaignStatus.ARCHIVED
    append_audit_event(
        db, action="CAMPAIGN_UPDATED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
        metadata={"change": "archived"},
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
    campaign.closed_at = datetime.now(UTC)
    # A cancelled campaign is withdrawn: nobody can sign it any more.
    _end_outstanding(db, campaign.id, AssignmentStatus.CANCELLED)
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
    document_version_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    viewed: bool | None = None,
    overdue: bool | None = None,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Follow-up table (spec §66), filterable by status, document, group,
    viewed / not viewed and overdue."""
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
    if document_version_id is not None:
        stmt = stmt.where(SignatureAssignment.document_version_id == document_version_id)
    if group_id is not None:
        stmt = stmt.where(
            SignatureAssignment.user_id.in_(
                select(GroupMembership.user_id).where(GroupMembership.group_id == group_id)
            )
        )
    if viewed is True:
        stmt = stmt.where(SignatureAssignment.first_viewed_at.is_not(None))
    elif viewed is False:
        stmt = stmt.where(SignatureAssignment.first_viewed_at.is_(None))
    if overdue:
        stmt = stmt.where(
            SignatureAssignment.status.in_([AssignmentStatus.PENDING, AssignmentStatus.VIEWED]),
            SignatureAssignment.deadline.is_not(None),
            SignatureAssignment.deadline < datetime.now(UTC),
        )
    rows = db.execute(stmt.order_by(User.display_name)).all()

    group_names: dict[uuid.UUID, list[str]] = {}
    for member_id, group_name in db.execute(
        select(GroupMembership.user_id, Group.name)
        .join(Group, Group.id == GroupMembership.group_id)
        .where(GroupMembership.user_id.in_({a.user_id for a, _ in rows}))
        .order_by(Group.name)
    ):
        group_names.setdefault(member_id, []).append(group_name)
    titles = {
        v.id: f"{d.title} v{v.version_label}"
        for v, d in db.execute(
            select(DocumentVersion, Document)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentVersion.id.in_({a.document_version_id for a, _ in rows}))
        )
    }
    roles = {r.role: r for r in load_roles(db, campaign_id)}
    # Who a waiting copy is waiting for: the earlier roles of that document not yet signed.
    unsigned: dict[uuid.UUID, list[tuple[int, str]]] = {}
    for doc_id, earlier_role, earlier_name in db.execute(
        select(
            SignatureAssignment.document_version_id, SignatureAssignment.role, User.display_name
        )
        .join(User, User.id == SignatureAssignment.user_id)
        .where(
            SignatureAssignment.campaign_id == campaign_id,
            SignatureAssignment.status.in_([AssignmentStatus.WAITING, AssignmentStatus.PENDING,
                                            AssignmentStatus.VIEWED]),
        )
    ):
        unsigned.setdefault(doc_id, []).append((earlier_role, earlier_name))
    return [
        {
            "id": str(assignment.id),
            "role": assignment.role,
            "role_label": role_label(roles.get(assignment.role), assignment.role),
            "waiting_on": sorted(
                {n for r, n in unsigned.get(assignment.document_version_id, [])
                 if r < assignment.role}
            ) if assignment.status == AssignmentStatus.WAITING else [],
            "document_version_id": str(assignment.document_version_id),
            "document_title": titles.get(assignment.document_version_id, ""),
            "groups": group_names.get(assignment.user_id, []),
            "signature_id": str(assignment.signature_id) if assignment.signature_id else None,
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
    ).scalars().all()

    campaigns_by_id = {
        c.id: c
        for c in db.execute(
            select(Campaign).where(Campaign.id.in_({a.campaign_id for a in rows}))
        ).scalars()
    }
    versions_by_id = {
        v.id: v
        for v in db.execute(
            select(DocumentVersion).where(
                DocumentVersion.id.in_({a.document_version_id for a in rows})
            )
        ).scalars()
    }
    documents_by_id = {
        d.id: d
        for d in db.execute(
            select(Document).where(
                Document.id.in_({v.document_id for v in versions_by_id.values()})
            )
        ).scalars()
    }

    result = []
    for a in rows:
        version = versions_by_id.get(a.document_version_id)
        document = documents_by_id.get(version.document_id) if version else None
        campaign = campaigns_by_id.get(a.campaign_id)
        result.append(
            {
                "id": str(a.id),
                "role": a.role,
                "waiting_on": waiting_on(db, a) if a.status == AssignmentStatus.WAITING else [],
                "campaign_id": str(a.campaign_id),
                "campaign_name": campaign.name if campaign else "",
                "document_version_id": str(a.document_version_id),
                "document_title": document.title if document else "",
                "version_label": version.version_label if version else "",
                "status": a.status.value,
                "assigned_at": a.assigned_at.isoformat(),
                "deadline": a.deadline.isoformat() if a.deadline else None,
                "signed_at": a.signed_at.isoformat() if a.signed_at else None,
                "signature_id": str(a.signature_id) if a.signature_id else None,
            }
        )
    return result
