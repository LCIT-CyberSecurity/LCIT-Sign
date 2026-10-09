"""The campaign access rules (services/access.py) as the routes ask for them: 404 when the
campaign does not exist *or* this person may not even see it (its existence is not theirs to
know); 403 when they see it but not at the level asked."""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from sqlalchemy.orm import Session as DbSession

from lcit_sign.models.campaign import Campaign
from lcit_sign.models.user import User
from lcit_sign.services.access import (
    can_manage_campaign,
    can_operate_campaign,
    can_view_campaign,
)

Level = Literal["view", "operate", "content"]


def guard_campaign(db: DbSession, user: User, campaign: Campaign | None, level: Level) -> Campaign:
    if campaign is None or not can_view_campaign(db, user, campaign):
        raise HTTPException(404, "Campaign not found")
    if level == "operate" and not can_operate_campaign(db, user, campaign):
        raise HTTPException(403, "Vous ne pouvez pas agir sur cette campagne")
    if level == "content" and not can_manage_campaign(db, user, campaign):
        raise HTTPException(
            403,
            "Le contenu de cette campagne est confidentiel : il faut en être le propriétaire ou "
            "un préparateur.",
        )
    return campaign
