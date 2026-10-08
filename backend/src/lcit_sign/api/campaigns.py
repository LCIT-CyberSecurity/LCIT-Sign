from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.api.campaign_access import Level, guard_campaign
from lcit_sign.api.documents import check_publishable, publish_draft
from lcit_sign.config import Settings
from lcit_sign.deps import get_current_user, get_db, require_roles
from lcit_sign.models.campaign import (
    AssignmentStatus,
    Campaign,
    CampaignDocument,
    CampaignPreparer,
    CampaignStatus,
    CampaignTargetGroup,
    CampaignTargetMode,
    CampaignTargetUser,
    SignatureAssignment,
)
from lcit_sign.models.directory import Group, GroupMembership
from lcit_sign.models.document import (
    Document,
    DocumentField,
    DocumentVersion,
    DocumentVersionStatus,
    FieldKind,
)
from lcit_sign.models.mail import Notification, NotificationType
from lcit_sign.models.report import Report
from lcit_sign.models.signature import Signature
from lcit_sign.models.user import Role, User, UserRole
from lcit_sign.services.access import (
    PREPARE_ROLES,
    campaigns_visible_to,
    can_manage_campaign,
    can_operate_campaign,
    is_member,
    roles_of,
)
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.campaign_changes import (
    ChangeError,
    add_recipients,
    is_released,
    release_document,
    remove_recipient,
)
from lcit_sign.services.campaign_launch import create_assignments
from lcit_sign.services.campaign_roles import (
    RoleError,
    RoleSpec,
    check_signers,
    load_roles,
    replace_roles,
    role_label,
    roles_required,
    validate_roles,
    waiting_on,
)
from lcit_sign.services.notification_queue import enqueue_notification
from lcit_sign.services.storage import StorageService
from lcit_sign.time_utils import ensure_utc

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

# Anyone who may prepare; what they may touch is decided per campaign (services/access.py).
_manage = require_roles(Role.SIGNER, Role.OPERATOR, Role.ADMIN)


@router.get("/_meta/users")
def list_targetable_users(
    user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> list[dict[str, Any]]:
    """A minimal, OPERATOR-reachable user picker for campaign targeting
    (spec §33) — deliberately thinner than /admin/users (no roles/active
    detail), which stays ADMIN-only for actual user administration."""
    rows = db.execute(select(User).where(User.active.is_(True)).order_by(User.email)).scalars()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "external": u.external,
        }
        for u in rows
    ]


class ExternalSignerIn(BaseModel):
    email: str = Field(max_length=320)
    given_name: str = Field(default="", max_length=120)
    family_name: str = Field(default="", max_length=120)


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/_meta/externals", status_code=201)
def add_external_signer(
    body: ExternalSignerIn,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Add someone from outside the company, by e-mail address, so they can be asked to sign. No
    account is created anywhere: they sign in with their own (an Entra guest, a Google
    account…) and are recognised by this address. An address already known is reused, never
    duplicated or changed."""
    email = body.email.strip().lower()
    if not _EMAIL.match(email):
        raise HTTPException(422, "Adresse e-mail invalide")
    existing = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
    if existing is not None:
        if not existing.active:
            raise HTTPException(
                409, "Cette personne est désactivée : un administrateur doit la réactiver."
            )
        return {
            "id": str(existing.id), "email": existing.email,
            "display_name": existing.display_name, "external": existing.external, "existing": True,
        }
    given, family = body.given_name.strip(), body.family_name.strip()
    created = User(
        issuer="directory:manual",
        subject=f"manual:{uuid.uuid4()}",
        email=email,
        given_name=given,
        family_name=family,
        display_name=f"{given} {family}".strip() or email.split("@")[0],
        active=True,
        external=True,
    )
    db.add(created)
    db.flush()
    db.add(UserRole(user_id=created.id, role=Role.SIGNER))
    append_audit_event(
        db, action="USER_CREATED", actor_id=user.id, target_type="user",
        target_id=str(created.id), metadata={"email": email, "source": "external-signer"},
    )
    db.commit()
    return {
        "id": str(created.id), "email": email, "display_name": created.display_name,
        "external": True, "existing": False,
    }


@router.get("/_meta/dashboard")
def operator_dashboard(
    user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    """Figures for the operator's overview (spec §65). `overdue` counts
    outstanding assignments whose deadline has passed; `not_viewed` those
    nobody has opened yet."""
    now = datetime.now(UTC)
    # A preparer's figures are those of their own campaigns; an operator or administrator sees all.
    visible = campaigns_visible_to(db, user)
    scope = [] if visible is None else [Campaign.id.in_(visible)]
    campaign_counts = dict(
        db.execute(
            select(Campaign.status, func.count()).where(*scope).group_by(Campaign.status)
        ).all()
    )
    active_ids = select(Campaign.id).where(Campaign.status == CampaignStatus.ACTIVE, *scope)
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


class SignersIn(BaseModel):
    """The people who sign, in order: a named user, or "every recipient" (last)."""

    signers: list[RoleIn] = Field(default=[], max_length=10)


class LaunchRequest(TargetRequest):
    # Who is "Signataire N": a named person, or the list of recipients below.
    roles: list[RoleIn] = []
    # When it starts: nothing or a past date = now; a future date = scheduled.
    start_at: datetime | None = None
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


def _documents_payload(db: DbSession, campaign: Campaign) -> list[dict[str, Any]]:
    """What the campaign will have people sign, with how far each is prepared."""
    result = []
    for link in campaign.documents:
        version = db.get(DocumentVersion, link.document_version_id)
        document = db.get(Document, version.document_id) if version else None
        if version is None or document is None:
            continue
        fields = db.execute(
            select(DocumentField.role, DocumentField.kind).where(
                DocumentField.document_version_id == version.id
            )
        ).all()
        placed = len(fields)
        result.append(
            {
                "version_id": str(version.id),
                "title": document.title,
                "version_label": version.version_label,
                "status": version.status.value,
                "elements": placed,
                # Which signers (positions) have something to fill on it, and which of them
                # have a signature placed: a signer with elements but no signature is a mistake.
                "element_roles": sorted({role for role, _ in fields}),
                "signature_roles": sorted(
                    {role for role, kind in fields if kind == FieldKind.SIGNATURE}
                ),
                "released": is_released(db, campaign, version.id),
            }
        )
    return sorted(result, key=lambda d: d["title"].lower())


def _roles_payload(db: DbSession, campaign: Campaign) -> list[dict[str, Any]]:
    """Who signs, in order: a named person, or every recipient. Chosen on the draft
    (the editor offers exactly these people) and frozen at launch."""
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
    return []


def _person(db: DbSession, user_id: uuid.UUID | None) -> dict[str, Any] | None:
    person = db.get(User, user_id) if user_id else None
    if person is None:
        return None
    return {"id": str(person.id), "display_name": person.display_name, "email": person.email}


def _campaign_payload(
    campaign: Campaign, db: DbSession, viewer: User | None = None
) -> dict[str, Any]:
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
        # Who runs it now, who started it (never changes), and who else may prepare it.
        "owner": _person(db, campaign.owner_id or campaign.created_by),
        "created_by": _person(db, campaign.created_by),
        "preparers": [
            _person(db, row.user_id)
            for row in db.execute(
                select(CampaignPreparer).where(CampaignPreparer.campaign_id == campaign.id)
            ).scalars()
        ],
        # What the person asking may do with it: the interface only shows what the API allows.
        "access": None
        if viewer is None
        else {
            "operate": can_operate_campaign(db, viewer, campaign),
            "content": can_manage_campaign(db, viewer, campaign),
        },
        "created_at": campaign.created_at.isoformat(),
        "launch_at": campaign.launch_at.isoformat() if campaign.launch_at else None,
        "scheduled_start": (
            campaign.scheduled_start.isoformat() if campaign.scheduled_start else None
        ),
        "deadline": campaign.deadline.isoformat() if campaign.deadline else None,
        "closed_at": campaign.closed_at.isoformat() if campaign.closed_at else None,
        "delete_blockers": campaign_delete_blockers(db, campaign),
        "policies": {field: getattr(campaign, field) for field in POLICY_FIELDS},
        "renewal_of_campaign_id": (
            str(campaign.renewal_of_campaign_id) if campaign.renewal_of_campaign_id else None
        ),
        "document_version_ids": [str(d.document_version_id) for d in campaign.documents],
        "documents": _documents_payload(db, campaign),
        # The work in progress on a draft (recipients, planning); nothing once sent.
        "plan": campaign.launch_request if campaign.status == CampaignStatus.DRAFT else None,
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
    campaign = Campaign(
        name=body.name, description=body.description, created_by=user.id, owner_id=user.id
    )
    db.add(campaign)
    db.flush()
    append_audit_event(
        db, action="CAMPAIGN_CREATED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
    )
    db.commit()
    return _campaign_payload(campaign, db, user)


def _get_draft_campaign(
    db: DbSession, campaign_id: uuid.UUID, user: User, level: Level = "content"
) -> Campaign:
    campaign = guard_campaign(db, user, db.get(Campaign, campaign_id), level)
    if campaign.status != CampaignStatus.DRAFT:
        raise HTTPException(409, "Campaign is no longer a draft")
    return campaign


def _get_editable_campaign(
    db: DbSession, campaign_id: uuid.UUID, user: User, level: Level = "content"
) -> Campaign:
    """A campaign still being prepared, or already sent and running (people and
    documents can be added to it; what was signed stays)."""
    campaign = guard_campaign(db, user, db.get(Campaign, campaign_id), level)
    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.ACTIVE):
        raise HTTPException(409, "Cette campagne est terminée : elle ne se modifie plus")
    return campaign


def _get_active_campaign(
    db: DbSession, campaign_id: uuid.UUID, user: User, level: Level = "operate"
) -> Campaign:
    campaign = guard_campaign(db, user, db.get(Campaign, campaign_id), level)
    if campaign.status != CampaignStatus.ACTIVE:
        raise HTTPException(409, "Seule une campagne en cours se modifie ainsi")
    return campaign


@router.post("/{campaign_id}/documents", status_code=201)
def add_campaign_document(
    campaign_id: uuid.UUID,
    body: AddDocumentRequest,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    campaign = _get_editable_campaign(db, campaign_id, user)
    version = db.get(DocumentVersion, body.document_version_id)
    # A draft can be added and prepared from the campaign; it is published, frozen,
    # when the campaign is launched. A superseded or archived one is not offered.
    if version is None or version.status not in (
        DocumentVersionStatus.PUBLISHED,
        DocumentVersionStatus.DRAFT,
    ):
        raise HTTPException(
            400, "Only a draft or published document version can be added to a campaign"
        )

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
    """Take a document back out of a campaign: one not sent yet can always go; once
    its copies were sent it is part of the campaign."""
    campaign = _get_editable_campaign(db, campaign_id, user)
    if is_released(db, campaign, version_id):
        raise HTTPException(409, "Ce document est déjà envoyé : il ne se retire plus.")
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


class PlanIn(LaunchRequest):
    """The recipients and the planning of a draft, saved as the operator fills them (the signers
    have their own endpoint)."""

    roles: list[RoleIn] = Field(default=[], max_length=0)


@router.put("/{campaign_id}/plan")
def put_plan(
    campaign_id: uuid.UUID,
    body: PlanIn,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Keep what the operator has chosen so far (who is asked, when, how often to remind), so
    that nothing is lost on a reload. Nothing is checked beyond the shape: the launch does."""
    campaign = _get_draft_campaign(db, campaign_id, user)
    campaign.launch_request = body.model_dump(mode="json", exclude={"roles"})
    db.commit()
    return _campaign_payload(campaign, db)


@router.put("/{campaign_id}/signers")
def put_signers(
    campaign_id: uuid.UUID,
    body: SignersIn,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Who signs, in which order — decided before the documents are prepared, so
    the editor can offer these very people for the elements."""
    campaign = _get_draft_campaign(db, campaign_id, user)
    specs = [RoleSpec(s.role, s.mode, s.user_id, s.label) for s in body.signers]
    try:
        ordered = check_signers(db, specs) if specs else []
    except RoleError as exc:
        raise HTTPException(422, str(exc)) from exc
    replace_roles(db, campaign, ordered)
    append_audit_event(
        db, action="CAMPAIGN_UPDATED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
        metadata={"change": "signers", "count": len(ordered)},
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
    _get_draft_campaign(db, campaign_id, user)
    population = _resolve_population(
        db, all_users=body.all_users, group_ids=body.group_ids, user_ids=body.user_ids
    )
    return {"population_count": len(population), "user_ids": [str(u) for u in population]}


def _check_launch(
    db: DbSession, storage: StorageService, campaign: Campaign, body: LaunchRequest
) -> list[RoleSpec]:
    """Everything that can refuse a launch, without changing anything. Returns the
    checked signers."""
    if not campaign.documents:
        raise HTTPException(400, "Campaign has no documents to sign")
    for link in campaign.documents:
        draft = db.get(DocumentVersion, link.document_version_id)
        if draft is not None and draft.status == DocumentVersionStatus.DRAFT:
            check_publishable(db, storage, draft)

    # The signers chosen on the draft; a launch request may still give them itself.
    given = [RoleSpec(r.role, r.mode, r.user_id, r.label) for r in body.roles] or [
        RoleSpec(r.role, r.mode, r.user_id, r.label)  # type: ignore[arg-type]
        for r in load_roles(db, campaign.id)
    ]
    try:
        role_specs = validate_roles(db, campaign, given)
    except RoleError as exc:
        raise HTTPException(422, str(exc)) from exc
    has_list = any(spec.mode == "EACH" for spec in role_specs)
    population = _resolve_population(
        db, all_users=body.all_users, group_ids=body.group_ids, user_ids=body.user_ids
    )
    if has_list and not population:
        raise HTTPException(400, "Target population is empty")
    return role_specs


def execute_launch(
    db: DbSession,
    *,
    settings: Settings,
    storage: StorageService,
    user: User,
    campaign: Campaign,
    body: LaunchRequest,
) -> None:
    """Send the campaign: freeze its drafts, make the copies, notify the first signers.
    Run at once by the launch button, or later by the worker for a scheduled start.
    Raises HTTPException; the caller commits."""
    role_specs = _check_launch(db, storage, campaign, body)
    has_list = any(spec.mode == "EACH" for spec in role_specs)
    population = _resolve_population(
        db, all_users=body.all_users, group_ids=body.group_ids, user_ids=body.user_ids
    )
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

    # The drafts prepared for this campaign are published (frozen) now.
    for campaign_document in campaign.documents:
        pending_version = db.get(DocumentVersion, campaign_document.document_version_id)
        if pending_version is None or pending_version.status not in (
            DocumentVersionStatus.DRAFT,
            DocumentVersionStatus.PUBLISHED,
        ):
            raise HTTPException(409, "Un document de la campagne n'est plus utilisable")
        if pending_version.status == DocumentVersionStatus.DRAFT:
            publish_draft(db, storage, user, pending_version)
    replace_roles(db, campaign, role_specs)
    create_assignments(
        db, campaign, population, deadline=body.deadline,
        public_base_url=settings.public_base_url, roles=role_specs,
    )
    for field in POLICY_FIELDS:
        setattr(campaign, field, getattr(body, field))

    campaign.status = CampaignStatus.ACTIVE
    campaign.launch_at = datetime.now(UTC)
    campaign.scheduled_start = None
    campaign.launch_request = None
    if body.deadline:
        campaign.deadline = body.deadline

    append_audit_event(
        db, action="CAMPAIGN_STARTED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
        metadata={"population": len(population), "documents": len(campaign.documents)},
    )


@router.post("/{campaign_id}/launch")
def launch_campaign(
    request: Request,
    campaign_id: uuid.UUID,
    body: LaunchRequest,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    campaign = _get_draft_campaign(db, campaign_id, user)
    now = datetime.now(UTC)
    if body.start_at is not None and ensure_utc(body.start_at) > now + timedelta(minutes=1):
        # A later start: check everything now, so a refusal is known today and not on the
        # day; keep the request as filled, and let the worker start it on its date.
        _check_launch(db, request.app.state.storage, campaign, body)
        if body.deadline is not None and ensure_utc(body.deadline) <= ensure_utc(body.start_at):
            raise HTTPException(422, "L'échéance doit être après la date de début.")
        campaign.status = CampaignStatus.SCHEDULED
        campaign.scheduled_start = ensure_utc(body.start_at)
        campaign.launch_request = body.model_dump(mode="json")
        append_audit_event(
            db, action="CAMPAIGN_SCHEDULED", actor_id=user.id,
            target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
            metadata={"start": campaign.scheduled_start.isoformat()},
        )
        db.commit()
        return _campaign_payload(campaign, db)

    execute_launch(
        db,
        settings=request.app.state.settings,
        storage=request.app.state.storage,
        user=user,
        campaign=campaign,
        body=body,
    )
    db.commit()
    return _campaign_payload(campaign, db)


class RemindRequest(BaseModel):
    """Remind only these (rows of the follow-up table, or whole people); empty = everyone
    still outstanding."""

    assignment_ids: list[uuid.UUID] = []
    user_ids: list[uuid.UUID] = []


class RecipientsIn(TargetRequest):
    pass


@router.post("/{campaign_id}/recipients")
def add_campaign_recipients(
    request: Request,
    campaign_id: uuid.UUID,
    body: RecipientsIn,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Ask more people on a campaign already sent (groups, users or everyone)."""
    campaign = _get_active_campaign(db, campaign_id, user)
    population = _resolve_population(
        db, all_users=body.all_users, group_ids=body.group_ids, user_ids=body.user_ids
    )
    if not population:
        raise HTTPException(400, "Target population is empty")
    settings: Settings = request.app.state.settings
    try:
        added = add_recipients(
            db, campaign, population, public_base_url=settings.public_base_url
        )
    except ChangeError as exc:
        raise HTTPException(409, str(exc)) from exc
    append_audit_event(
        db, action="CAMPAIGN_UPDATED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
        metadata={"change": "recipients_added", "count": added},
    )
    db.commit()
    return {"added": added, **_campaign_payload(campaign, db)}


@router.delete("/{campaign_id}/recipients/{target_user_id}")
def remove_campaign_recipient(
    campaign_id: uuid.UUID,
    target_user_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Stop asking someone: what they have not signed is cancelled, what they signed stays."""
    campaign = _get_active_campaign(db, campaign_id, user)
    try:
        cancelled = remove_recipient(db, campaign, target_user_id)
    except ChangeError as exc:
        raise HTTPException(409, str(exc)) from exc
    append_audit_event(
        db, action="CAMPAIGN_UPDATED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
        metadata={"change": "recipient_removed", "user_id": str(target_user_id),
                  "cancelled": cancelled},
    )
    db.commit()
    return {"cancelled": cancelled, **_campaign_payload(campaign, db)}


@router.post("/{campaign_id}/documents/{version_id}/release")
def release_campaign_document(
    request: Request,
    campaign_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Send a document added after the launch: it is frozen (published) and its
    copies go to the signers, in order."""
    campaign = _get_active_campaign(db, campaign_id, user, "content")
    link = db.get(CampaignDocument, (campaign.id, version_id))
    version = db.get(DocumentVersion, version_id)
    if link is None or version is None:
        raise HTTPException(404, "This document is not in the campaign")
    if is_released(db, campaign, version_id):
        raise HTTPException(409, "Ce document est déjà envoyé.")
    settings: Settings = request.app.state.settings
    if version.status == DocumentVersionStatus.DRAFT:
        publish_draft(db, request.app.state.storage, user, version)
    elif version.status != DocumentVersionStatus.PUBLISHED:
        raise HTTPException(409, "Ce document n'est plus utilisable")
    try:
        copies = release_document(
            db, campaign, version_id, public_base_url=settings.public_base_url
        )
    except ChangeError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    append_audit_event(
        db, action="CAMPAIGN_UPDATED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
        document_id=version.document_id,
        metadata={"change": "document_sent", "copies": copies},
    )
    db.commit()
    return {"copies": copies, **_campaign_payload(campaign, db)}


@router.post("/{campaign_id}/remind")
def remind_campaign(
    request: Request,
    campaign_id: uuid.UUID,
    body: RemindRequest | None = None,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Manual reminder (spec §83): queues one REMINDER email per
    still-outstanding assignment. Someone who already signed is never
    nagged again — only PENDING/VIEWED assignments qualify.
    """
    campaign = guard_campaign(db, user, db.get(Campaign, campaign_id), "operate")
    if campaign.status != CampaignStatus.ACTIVE:
        raise HTTPException(409, "Only an active campaign can send reminders")

    settings: Settings = request.app.state.settings
    outstanding: list[Any] = list(
        db.execute(
            select(SignatureAssignment, User)
            .join(User, SignatureAssignment.user_id == User.id)
            .where(
                SignatureAssignment.campaign_id == campaign.id,
                SignatureAssignment.status.in_([AssignmentStatus.PENDING, AssignmentStatus.VIEWED]),
            )
        ).all()
    )
    if body and (body.assignment_ids or body.user_ids):
        outstanding = [
            (a, u)
            for a, u in outstanding
            if a.id in set(body.assignment_ids) or u.id in set(body.user_ids)
        ]

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
    campaign = guard_campaign(db, user, db.get(Campaign, campaign_id), "operate")
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
    if campaign.status in (CampaignStatus.ACTIVE, CampaignStatus.SCHEDULED):
        reasons.append("elle est en cours ou programmée : annulez-la d'abord")
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
    campaign = guard_campaign(db, user, db.get(Campaign, campaign_id), "content")
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
    campaign = guard_campaign(db, user, db.get(Campaign, campaign_id), "operate")
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
    campaign = guard_campaign(db, user, db.get(Campaign, campaign_id), "operate")
    if campaign.status not in (
        CampaignStatus.DRAFT,
        CampaignStatus.SCHEDULED,
        CampaignStatus.ACTIVE,
    ):
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
    visible = campaigns_visible_to(db, user)
    query = select(Campaign).order_by(Campaign.created_at.desc())
    if visible is not None:
        query = query.where(Campaign.id.in_(visible))
    return [_campaign_payload(c, db, user) for c in db.execute(query).scalars()]


@router.get("/{campaign_id}")
def get_campaign(
    campaign_id: uuid.UUID, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    campaign = guard_campaign(db, user, db.get(Campaign, campaign_id), "view")
    return _campaign_payload(campaign, db, user)


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
    guard_campaign(db, user, db.get(Campaign, campaign_id), "view")

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
    request: Request, user: User = Depends(get_current_user), db: DbSession = Depends(get_db)
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


# --- who runs a campaign: owner and preparers -----------------------------------------------


class PersonIn(BaseModel):
    user_id: uuid.UUID


def _preparer_candidate(db: DbSession, user_id: uuid.UUID) -> User:
    person = db.get(User, user_id)
    if person is None or not person.active:
        raise HTTPException(404, "Utilisateur introuvable ou désactivé")
    if not (roles_of(db, person) & PREPARE_ROLES):
        raise HTTPException(
            422,
            f"{person.display_name} n'a pas le rôle Signataire (ni Opérateur, ni Admin) : "
            "donnez-lui d'abord ce rôle.",
        )
    return person


@router.get("/_meta/preparers")
def possible_preparers(
    user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> list[dict[str, Any]]:
    """The people who could be made owner or preparer: active, and allowed to prepare."""
    rows = db.execute(
        select(User).where(
            User.active.is_(True),
            User.id.in_(select(UserRole.user_id).where(UserRole.role.in_(PREPARE_ROLES))),
        )
    ).scalars()
    return [
        {"id": str(p.id), "display_name": p.display_name, "email": p.email}
        for p in sorted(rows, key=lambda p: p.display_name.lower())
    ]


@router.put("/{campaign_id}/owner")
def change_owner(
    campaign_id: uuid.UUID,
    body: PersonIn,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Hand the campaign over (an absence, a departure). The creator is never rewritten; the
    previous owner stays a preparer, until someone removes them."""
    campaign = guard_campaign(db, user, db.get(Campaign, campaign_id), "operate")
    new_owner = _preparer_candidate(db, body.user_id)
    previous = campaign.owner_id or campaign.created_by
    if new_owner.id != previous:
        campaign.owner_id = new_owner.id
        already = db.get(CampaignPreparer, (campaign.id, previous))
        if already is None and previous != new_owner.id:
            db.add(CampaignPreparer(campaign_id=campaign.id, user_id=previous, added_by=user.id))
        gone = db.get(CampaignPreparer, (campaign.id, new_owner.id))
        if gone is not None:
            db.delete(gone)  # the owner needs no row of their own
        append_audit_event(
            db, action="CAMPAIGN_OWNER_CHANGED", actor_id=user.id,
            target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
            metadata={"from": str(previous), "to": str(new_owner.id)},
        )
    db.commit()
    return _campaign_payload(campaign, db, user)


@router.post("/{campaign_id}/preparers", status_code=201)
def add_preparer(
    campaign_id: uuid.UUID,
    body: PersonIn,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Allow someone to prepare, run and read this campaign. An operator who must see the content
    is added here, which leaves a trace."""
    campaign = guard_campaign(db, user, db.get(Campaign, campaign_id), "operate")
    person = _preparer_candidate(db, body.user_id)
    if is_member(db, person, campaign):
        raise HTTPException(409, f"{person.display_name} est déjà propriétaire ou préparateur")
    db.add(CampaignPreparer(campaign_id=campaign.id, user_id=person.id, added_by=user.id))
    append_audit_event(
        db, action="CAMPAIGN_PREPARER_ADDED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
        metadata={"user_id": str(person.id)},
    )
    db.commit()
    return _campaign_payload(campaign, db, user)


@router.delete("/{campaign_id}/preparers/{person_id}")
def remove_preparer(
    campaign_id: uuid.UUID,
    person_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    campaign = guard_campaign(db, user, db.get(Campaign, campaign_id), "operate")
    if person_id == (campaign.owner_id or campaign.created_by):
        raise HTTPException(
            409, "Le propriétaire ne se retire pas : changez d'abord de propriétaire."
        )
    row = db.get(CampaignPreparer, (campaign.id, person_id))
    if row is None:
        raise HTTPException(404, "Cette personne n'est pas préparateur de la campagne")
    db.delete(row)
    append_audit_event(
        db, action="CAMPAIGN_PREPARER_REMOVED", actor_id=user.id,
        target_type="campaign", target_id=str(campaign.id), campaign_id=campaign.id,
        metadata={"user_id": str(person_id)},
    )
    db.commit()
    return _campaign_payload(campaign, db, user)

