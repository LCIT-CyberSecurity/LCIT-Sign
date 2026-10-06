from __future__ import annotations

import calendar
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.config import Settings
from lcit_sign.models.campaign import (
    AssignmentStatus,
    Campaign,
    CampaignDocument,
    CampaignStatus,
    SignatureAssignment,
)
from lcit_sign.models.directory import DirectoryConnectorConfig, DirectorySyncRun
from lcit_sign.models.document import DocumentVersion, DocumentVersionStatus
from lcit_sign.models.mail import NotificationType
from lcit_sign.models.user import User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.campaign_launch import create_assignments
from lcit_sign.services.campaign_roles import RoleSpec, load_roles, save_roles
from lcit_sign.services.directory.base import (
    DirectoryConnector,
    DirectoryConnectorError,
)
from lcit_sign.services.directory.registry import build_remote_connector
from lcit_sign.services.directory_sync import LocalConnector, sync_directory
from lcit_sign.services.notification_queue import enqueue_notification
from lcit_sign.services.storage import StorageService
from lcit_sign.time_utils import ensure_utc

logger = logging.getLogger(__name__)

_OUTSTANDING = [AssignmentStatus.PENDING, AssignmentStatus.VIEWED]


def add_months(moment: datetime, months: int) -> datetime:
    index = moment.month - 1 + months
    year, month = moment.year + index // 12, index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def _reminder_due(campaign: Campaign, assignment: SignatureAssignment, now: datetime) -> bool:
    if campaign.reminder_first_days is None or campaign.reminder_interval_days is None:
        return False
    sent = assignment.reminder_count
    assigned_at = ensure_utc(assignment.assigned_at)
    last = ensure_utc(assignment.last_reminder_at) if assignment.last_reminder_at else None

    # One extra reminder N days before the deadline, whatever the cadence
    # has already produced (spec §50 "relance avant échéance").
    deadline = assignment.deadline or campaign.deadline
    if campaign.reminder_before_deadline_days is not None and deadline is not None:
        threshold = ensure_utc(deadline) - timedelta(days=campaign.reminder_before_deadline_days)
        if now >= threshold and (last is None or last < threshold):
            return True

    if campaign.reminder_max_count is not None and sent >= campaign.reminder_max_count:
        return False
    if last is None:
        return now >= assigned_at + timedelta(days=campaign.reminder_first_days)
    return now >= last + timedelta(days=campaign.reminder_interval_days)


def process_reminders(db: DbSession, settings: Settings, now: datetime | None = None) -> int:
    """Queue the reminders the campaigns' policies say are due. Idempotent:
    each queued reminder advances `last_reminder_at`, so running this twice
    in a row sends nothing the second time. Signed people are never nagged.
    """
    now = now or datetime.now(UTC)
    queued = 0
    campaigns = db.execute(
        select(Campaign).where(
            Campaign.status == CampaignStatus.ACTIVE, Campaign.reminder_first_days.is_not(None)
        )
    ).scalars()
    for campaign in campaigns:
        rows = db.execute(
            select(SignatureAssignment, User)
            .join(User, SignatureAssignment.user_id == User.id)
            .where(
                SignatureAssignment.campaign_id == campaign.id,
                SignatureAssignment.status.in_(_OUTSTANDING),
                User.active.is_(True),
            )
        ).all()
        sent_here = 0
        for assignment, target_user in rows:
            if not _reminder_due(campaign, assignment, now):
                continue
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
            sent_here += 1
        if sent_here:
            append_audit_event(
                db, action="REMINDER_SENT", target_type="campaign", target_id=str(campaign.id),
                campaign_id=campaign.id, metadata={"count": sent_here, "automatic": True},
            )
            queued += sent_here
    db.commit()
    return queued


def process_renewals(db: DbSession, settings: Settings, now: datetime | None = None) -> int:
    """Open a follow-up campaign for every campaign whose renewal date has
    come (spec §51). The previous campaign and its signatures are untouched;
    the new one re-asks the people (still active) of the old population for
    every document version that is still published."""
    now = now or datetime.now(UTC)
    renewed = 0
    candidates = db.execute(
        select(Campaign).where(
            Campaign.renewal_every.is_not(None),
            Campaign.renewed_at.is_(None),
            Campaign.launch_at.is_not(None),
            Campaign.status.in_([CampaignStatus.ACTIVE, CampaignStatus.CLOSED]),
        )
    ).scalars()
    for campaign in candidates:
        assert campaign.renewal_every is not None and campaign.launch_at is not None  # noqa: S101
        launch_at = ensure_utc(campaign.launch_at)
        due_at = (
            launch_at + timedelta(days=campaign.renewal_every)
            if campaign.renewal_unit == "DAYS"
            else add_months(launch_at, campaign.renewal_every)
        )
        if now < due_at:
            continue

        published_ids = {
            vid
            for vid in db.execute(
                select(DocumentVersion.id).where(
                    DocumentVersion.id.in_([d.document_version_id for d in campaign.documents]),
                    DocumentVersion.status == DocumentVersionStatus.PUBLISHED,
                )
            ).scalars()
        }
        # The same people sign in the same roles: fixed signers (the RSSI) stay,
        # and the recipients are the ones who were asked as "each".
        old_roles = load_roles(db, campaign.id)
        each_role = next((r.role for r in old_roles if r.mode == "EACH"), None)
        recipients_query = (
            select(SignatureAssignment.user_id)
            .join(User, SignatureAssignment.user_id == User.id)
            .where(SignatureAssignment.campaign_id == campaign.id, User.active.is_(True))
        )
        if old_roles:
            recipients_query = recipients_query.where(SignatureAssignment.role == each_role)
        population = (
            list(db.execute(recipients_query.distinct()).scalars())
            if each_role is not None or not old_roles
            else []
        )
        fixed_active = all(
            db.execute(
                select(User.id).where(User.id == r.user_id, User.active.is_(True))
            ).first()
            for r in old_roles
            if r.mode == "FIXED"
        )
        campaign.renewed_at = now
        if not published_ids or not fixed_active or (not population and each_role is not None):
            # Nothing renewable (versions superseded, everyone gone):
            # recorded as handled so it is not retried every cycle.
            continue

        new_campaign = Campaign(
            id=uuid.uuid4(),
            name=f"{campaign.name} — renouvellement {now.strftime('%d/%m/%Y')}",
            description=campaign.description,
            status=CampaignStatus.ACTIVE,
            target_mode=campaign.target_mode,
            created_by=campaign.created_by,
            launch_at=now,
            renewal_of_campaign_id=campaign.id,
            signature_method=campaign.signature_method,
            reminder_first_days=campaign.reminder_first_days,
            reminder_interval_days=campaign.reminder_interval_days,
            reminder_max_count=campaign.reminder_max_count,
            reminder_before_deadline_days=campaign.reminder_before_deadline_days,
            renewal_every=campaign.renewal_every,
            renewal_unit=campaign.renewal_unit,
        )
        deadline = None
        if campaign.deadline is not None:
            deadline = now + (ensure_utc(campaign.deadline) - launch_at)
            new_campaign.deadline = deadline
        db.add(new_campaign)
        db.flush()
        for version_id in published_ids:
            db.add(CampaignDocument(campaign_id=new_campaign.id, document_version_id=version_id))
        db.flush()
        db.refresh(new_campaign)
        specs = [
            RoleSpec(role=r.role, mode=r.mode, user_id=r.user_id, label=r.label)  # type: ignore[arg-type]
            for r in old_roles
        ]
        save_roles(db, new_campaign, specs)
        create_assignments(
            db, new_campaign, population, deadline=deadline,
            public_base_url=settings.public_base_url, roles=specs or None,
        )
        append_audit_event(
            db, action="CAMPAIGN_STARTED", target_type="campaign", target_id=str(new_campaign.id),
            campaign_id=new_campaign.id,
            metadata={"renewal_of": str(campaign.id), "population": len(population),
                      "automatic": True},
        )
        renewed += 1
    db.commit()
    return renewed


def process_directory_syncs(
    db: DbSession, settings: Settings, http_client: httpx.Client, now: datetime | None = None
) -> int:
    """Run every directory source whose configured interval has elapsed
    since its last run (spec §15). A failed run counts as a run, so a down
    upstream is retried at the normal cadence, not in a tight loop."""
    now = now or datetime.now(UTC)
    ran = 0
    configs = db.execute(
        select(DirectoryConnectorConfig).where(
            DirectoryConnectorConfig.sync_interval_minutes.is_not(None)
        )
    ).scalars()
    for config in list(configs):
        assert config.sync_interval_minutes is not None  # noqa: S101
        last = db.execute(
            select(DirectorySyncRun.started_at)
            .where(DirectorySyncRun.source == config.source)
            .order_by(DirectorySyncRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last is not None and now < ensure_utc(last) + timedelta(
            minutes=config.sync_interval_minutes
        ):
            continue
        connector: DirectoryConnector
        if config.source == "local":
            connector = LocalConnector()
        else:
            try:
                connector = build_remote_connector(config, settings.master_key, http_client)
            except DirectoryConnectorError:
                logger.exception("scheduled sync: cannot build connector %s", config.source)
                continue
        sync_directory(db, connector)
        ran += 1
    return ran


def process_scheduled_starts(
    db: DbSession, settings: Settings, storage: StorageService, now: datetime | None = None
) -> int:
    """Start the campaigns whose start date has come, with the launch request the
    operator filled in. One that can no longer start (a document removed, a logo gone,
    nobody left to ask) goes back to being a draft, with the reason in the audit trail,
    rather than being retried forever."""
    # Imported here: the launch rules live with the API, which imports this module's siblings.
    from fastapi import HTTPException

    from lcit_sign.api.campaigns import LaunchRequest, execute_launch

    now = now or datetime.now(UTC)
    started = 0
    due = list(
        db.execute(
            select(Campaign.id).where(
                Campaign.status == CampaignStatus.SCHEDULED,
                Campaign.scheduled_start <= now,
            )
        ).scalars()
    )
    for campaign_id in due:
        campaign = db.get(Campaign, campaign_id)
        if campaign is None or campaign.launch_request is None:
            continue
        owner = db.get(User, campaign.created_by)
        try:
            if owner is None:
                raise HTTPException(409, "Le créateur de la campagne n'existe plus")
            execute_launch(
                db,
                settings=settings,
                storage=storage,
                user=owner,
                campaign=campaign,
                body=LaunchRequest.model_validate(campaign.launch_request),
            )
            db.commit()
            started += 1
        except Exception as exc:
            db.rollback()
            reason = exc.detail if isinstance(exc, HTTPException) else type(exc).__name__
            campaign = db.get(Campaign, campaign_id)
            if campaign is not None:
                campaign.status = CampaignStatus.DRAFT
                campaign.scheduled_start = None
                campaign.launch_request = None
                append_audit_event(
                    db, action="CAMPAIGN_START_FAILED", target_type="campaign",
                    target_id=str(campaign_id), campaign_id=campaign_id, result="FAILURE",
                    metadata={"reason": str(reason)},
                )
                db.commit()
    return started
