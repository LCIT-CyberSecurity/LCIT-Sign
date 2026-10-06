"""Sign every document of a campaign in one go: the fixed signer (the RSSI) who has twenty
documents to sign, or anyone asked for several documents in the same campaign. One consent,
the same answer typed once for every element that shares it, one signature (with its own proof)
per document."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.api.fields import field_payload, load_fields
from lcit_sign.api.signatures import _signature_payload, perform_signature
from lcit_sign.deps import get_current_user, get_db
from lcit_sign.models.campaign import (
    AssignmentStatus,
    Campaign,
    CampaignStatus,
    SignatureAssignment,
)
from lcit_sign.models.document import INPUT_KINDS, Document, DocumentVersion
from lcit_sign.models.user import User
from lcit_sign.services.audit import append_audit_event

router = APIRouter(prefix="/sign-all", tags=["signatures"])

_sign = get_current_user
OPEN = (AssignmentStatus.PENDING, AssignmentStatus.VIEWED)


def _available(
    db: DbSession, campaign: Campaign, user: User
) -> list[tuple[SignatureAssignment, Document, DocumentVersion]]:
    rows = db.execute(
        select(SignatureAssignment, Document, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.id == SignatureAssignment.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            SignatureAssignment.campaign_id == campaign.id,
            SignatureAssignment.user_id == user.id,
            SignatureAssignment.status.in_(OPEN),
        )
        .order_by(Document.title)
    ).all()
    return [(a, d, v) for a, d, v in rows]


def _campaign(db: DbSession, campaign_id: uuid.UUID) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    if campaign.status != CampaignStatus.ACTIVE:
        raise HTTPException(409, "Cette campagne n'est plus ouverte à la signature")
    return campaign


@router.get("/{campaign_id}")
def what_can_be_signed(
    campaign_id: uuid.UUID,
    user: User = Depends(_sign),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """The documents of this campaign the user can sign now, with what they are asked to type
    (an answer shared by several documents is asked once)."""
    campaign = _campaign(db, campaign_id)
    documents = []
    for assignment, document, version in _available(db, campaign, user):
        mine = [f for f in load_fields(db, version.id) if f.role == assignment.role]
        documents.append(
            {
                "version_id": str(version.id),
                "title": document.title,
                "version_label": version.version_label,
                "inputs": [field_payload(f) for f in mine if f.kind in INPUT_KINDS],
            }
        )
    waiting = db.execute(
        select(SignatureAssignment.id).where(
            SignatureAssignment.campaign_id == campaign.id,
            SignatureAssignment.user_id == user.id,
            SignatureAssignment.status == AssignmentStatus.WAITING,
        )
    ).all()
    return {
        "campaign": {"id": str(campaign.id), "name": campaign.name},
        "documents": documents,
        "waiting": len(waiting),
    }


class SignAllRequest(BaseModel):
    consent: bool
    # One answer for every element sharing a group key, and answers for single elements.
    shared: dict[str, str] = {}
    values: dict[str, str] = {}


@router.post("/{campaign_id}")
def sign_everything(
    request: Request,
    campaign_id: uuid.UUID,
    body: SignAllRequest,
    user: User = Depends(_sign),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Sign all the documents the user can sign in this campaign. Everything is checked first:
    one missing answer refuses the whole batch and nothing is signed."""
    if not body.consent:
        raise HTTPException(400, "Explicit consent is required to sign")
    campaign = _campaign(db, campaign_id)
    todo = _available(db, campaign, user)
    if not todo:
        raise HTTPException(409, "Rien à signer pour vous dans cette campagne.")

    plan: list[tuple[uuid.UUID, dict[str, str]]] = []
    for assignment, _document, version in todo:
        answers: dict[str, str] = {}
        for field in load_fields(db, version.id):
            if field.role != assignment.role or field.kind not in INPUT_KINDS:
                continue
            typed = body.values.get(str(field.id), "") or (
                body.shared.get(field.group_key, "") if field.group_key else ""
            )
            if typed.strip():
                answers[str(field.id)] = typed
        plan.append((version.id, answers))

    try:
        # A first pass changes nothing: any refusal (a missing answer…) is raised before the
        # first signature exists.
        for version_id, answers in plan:
            perform_signature(
                request, db, user, version_id, answers, only_campaign=campaign.id, dry_run=True
            )
        signatures = []
        for version_id, answers in plan:
            signature = perform_signature(
                request, db, user, version_id, answers, only_campaign=campaign.id
            )
            assert signature is not None  # noqa: S101 - only a dry run returns None
            signatures.append(signature)
    except HTTPException:
        db.rollback()
        raise
    append_audit_event(
        db,
        action="SIGN_ALL_COMPLETED",
        actor_id=user.id,
        target_type="campaign",
        target_id=str(campaign.id),
        campaign_id=campaign.id,
        metadata={"documents": len(signatures)},
    )
    db.commit()
    return {"signed": len(signatures), "signatures": [_signature_payload(s) for s in signatures]}
