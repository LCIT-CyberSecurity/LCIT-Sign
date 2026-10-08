"""Who may do what with a campaign, and with the documents that belong to it.

Three levels, nothing finer (no per-action rights):

* **view** — see that the campaign exists, its status, owner, preparers, signers and progress.
  Administrators and operators see every campaign; a preparer sees the ones they own or prepare.
* **operate** — act on how it runs: remind, cancel, close, archive, add or remove a recipient,
  hand it over (owner, preparers). Administrators, operators, the owner and its preparers.
* **content** — everything confidential: its documents and their signed PDFs, the proofs, the
  exports, the report, and building it (documents, elements, signers, sending). Administrators,
  the owner and its preparers — NOT an operator, unless they were made a preparer of it.

The owner always has the rights of a preparer without a row of their own in
`campaign_preparers`. Every rule lives here, so the routes only ask.
"""
from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.models.campaign import Campaign, CampaignDocument, CampaignPreparer
from lcit_sign.models.document import Document, DocumentVersion
from lcit_sign.models.user import Role, User, UserRole

PREPARE_ROLES = frozenset({Role.SIGNER, Role.OPERATOR, Role.ADMIN})


def roles_of(db: DbSession, user: User) -> set[Role]:
    return set(db.execute(select(UserRole.role).where(UserRole.user_id == user.id)).scalars())


def can_prepare(roles: set[Role]) -> bool:
    """May prepare documents and create campaigns: any signer (the standard user), and the staff."""
    return bool(roles & PREPARE_ROLES)


def is_member(db: DbSession, user: User, campaign: Campaign) -> bool:
    """Owner or preparer of this campaign."""
    owner = campaign.owner_id or campaign.created_by
    if owner == user.id:
        return True
    return (
        db.execute(
            select(CampaignPreparer.user_id).where(
                CampaignPreparer.campaign_id == campaign.id, CampaignPreparer.user_id == user.id
            )
        ).first()
        is not None
    )


def can_read_campaign_content(db: DbSession, user: User, campaign: Campaign) -> bool:
    roles = roles_of(db, user)
    if Role.ADMIN in roles:
        return True
    return can_prepare(roles) and is_member(db, user, campaign)


def can_manage_campaign(db: DbSession, user: User, campaign: Campaign) -> bool:
    """Build, change and send it: same people as those who read its content."""
    return can_read_campaign_content(db, user, campaign)


def can_operate_campaign(db: DbSession, user: User, campaign: Campaign) -> bool:
    roles = roles_of(db, user)
    if roles & {Role.ADMIN, Role.OPERATOR}:
        return True
    return can_prepare(roles) and is_member(db, user, campaign)


def can_view_campaign(db: DbSession, user: User, campaign: Campaign) -> bool:
    return can_operate_campaign(db, user, campaign)


def sees_every_campaign(roles: set[Role]) -> bool:
    return bool(roles & {Role.ADMIN, Role.OPERATOR})


def member_campaign_ids(db: DbSession, user: User) -> set[uuid.UUID]:
    """The campaigns this person owns or prepares."""
    return set(
        db.execute(
            select(Campaign.id).where(
                or_(
                    Campaign.owner_id == user.id,
                    (Campaign.owner_id.is_(None)) & (Campaign.created_by == user.id),
                    Campaign.id.in_(
                        select(CampaignPreparer.campaign_id).where(
                            CampaignPreparer.user_id == user.id
                        )
                    ),
                )
            )
        ).scalars()
    )


def campaigns_with_content_access(db: DbSession, user: User) -> set[uuid.UUID] | None:
    """The campaigns whose content this person may read; None means all of them (administrator)."""
    roles = roles_of(db, user)
    if Role.ADMIN in roles:
        return None
    return member_campaign_ids(db, user) if can_prepare(roles) else set()


def campaigns_visible_to(db: DbSession, user: User) -> set[uuid.UUID] | None:
    """The campaigns this person may see; None means all of them."""
    roles = roles_of(db, user)
    if sees_every_campaign(roles):
        return None
    return member_campaign_ids(db, user) if can_prepare(roles) else set()


def can_read_document(db: DbSession, user: User, document: Document) -> bool:
    """The document in the library, with its versions and files: an administrator; whoever
    uploaded it (if they may prepare); a preparer of a campaign that uses it. An operator who is
    none of these sees that the document exists, nothing more."""
    roles = roles_of(db, user)
    if Role.ADMIN in roles:
        return True
    if not can_prepare(roles):
        return False
    if document.created_by == user.id:
        return True
    mine = member_campaign_ids(db, user)
    if not mine:
        return False
    return (
        db.execute(
            select(CampaignDocument.campaign_id)
            .join(DocumentVersion, DocumentVersion.id == CampaignDocument.document_version_id)
            .where(
                DocumentVersion.document_id == document.id, CampaignDocument.campaign_id.in_(mine)
            )
        ).first()
        is not None
    )
