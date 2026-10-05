from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.models.campaign import AssignmentStatus, Campaign, SignatureAssignment
from lcit_sign.models.document import Document, DocumentVersion
from lcit_sign.models.mail import NotificationType
from lcit_sign.models.user import User
from lcit_sign.services.campaign_roles import RoleSpec, roles_by_version
from lcit_sign.services.notification_queue import enqueue_notification


def create_assignments(
    db: DbSession,
    campaign: Campaign,
    population: list[uuid.UUID],
    *,
    deadline: datetime | None,
    public_base_url: str,
    roles: list[RoleSpec] | None = None,
) -> None:
    """Freeze the signers into one SignatureAssignment per (document, role,
    person) and queue the "document to sign" email (spec §18). Shared by a
    manual launch and by an automatic renewal, so both behave identically.

    `roles` says who "Signataire N" is: a named person (signs once, whatever the
    size of the population) or every recipient. Only the first role of each
    document is asked now; the following ones wait their turn (WAITING) and are
    notified when the one before has signed. A fixed signer is not also
    assigned as a recipient: their signature already covers it.
    """
    specs = {spec.role: spec for spec in (roles or [RoleSpec(role=1, mode="EACH")])}
    fixed_ids = {spec.user_id for spec in specs.values() if spec.user_id}
    recipients = [user_id for user_id in population if user_id not in fixed_ids]
    wanted = {*population, *fixed_ids}
    users_by_id = {
        u.id: u for u in db.execute(select(User).where(User.id.in_(wanted))).scalars()
    }
    per_version = roles_by_version(db, [d.document_version_id for d in campaign.documents])

    for campaign_document in campaign.documents:
        version = db.get(DocumentVersion, campaign_document.document_version_id)
        document = db.get(Document, version.document_id) if version else None
        document_title = document.title if document else "document"
        used = per_version[campaign_document.document_version_id]
        first_role = used[0]

        for role in used:
            spec = specs.get(role) or RoleSpec(role=role, mode="EACH")
            people = [spec.user_id] if spec.mode == "FIXED" and spec.user_id else recipients
            for target_user_id in people:
                my_turn = role == first_role
                db.add(
                    SignatureAssignment(
                        campaign_id=campaign.id,
                        document_version_id=campaign_document.document_version_id,
                        user_id=target_user_id,
                        role=role,
                        status=AssignmentStatus.PENDING if my_turn else AssignmentStatus.WAITING,
                        deadline=deadline,
                    )
                )
                target_user = users_by_id.get(target_user_id)
                if my_turn and target_user is not None:
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
                            f"{public_base_url}\n"
                        ),
                    )
