from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.models.campaign import Campaign, SignatureAssignment
from lcit_sign.models.document import Document, DocumentVersion
from lcit_sign.models.mail import NotificationType
from lcit_sign.models.user import User
from lcit_sign.services.notification_queue import enqueue_notification


def create_assignments(
    db: DbSession,
    campaign: Campaign,
    population: list[uuid.UUID],
    *,
    deadline: datetime | None,
    public_base_url: str,
) -> None:
    """Freeze `population` into one SignatureAssignment per (document,
    user) and queue the "document to sign" email (spec §18). Shared by a
    manual launch and by an automatic renewal, so both behave identically.
    """
    users_by_id = {
        u.id: u for u in db.execute(select(User).where(User.id.in_(population))).scalars()
    }
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
                    deadline=deadline,
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
                        f"{public_base_url}\n"
                    ),
                )
