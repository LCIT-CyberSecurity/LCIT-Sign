"""The DocuSign connection, set by an administrator: the settings and a private key that is
stored encrypted and never shown again, a test of the connection, and — on a development or test
server only — one click to use the mock DocuSign of the test stack."""
from __future__ import annotations

from typing import Any, Literal

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from lcit_sign.config import Settings
from lcit_sign.deps import get_db, require_roles
from lcit_sign.models.docusign import DocusignConfig
from lcit_sign.models.user import Role, User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.connector_fields import FieldSpec
from lcit_sign.services.crypto import encrypt_secret
from lcit_sign.services.docusign import (
    DocusignClient,
    DocusignError,
    load_private_key,
)
from lcit_sign.services.docusign_flow import is_configured, load_settings

router = APIRouter(prefix="/admin/docusign", tags=["admin"])
_admin = require_roles(Role.ADMIN)

MOCK_URL = "http://mock-docusign:8091"

FIELDS = (
    FieldSpec(
        "environment",
        "Environnement",
        "« Bac à sable » : le compte de développement gratuit de DocuSign, sans valeur légale. "
        "« Production » : le vrai service, avec valeur légale.",
        "Bac à sable (demo)",
        kind="select",
        options=(("demo", "Bac à sable (demo)"), ("production", "Production")),
        default="demo",
    ),
    FieldSpec(
        "integration_key",
        "Clé d'intégration",
        "L'identifiant de l'application que vous avez créée chez DocuSign (« Integration Key »), "
        "un GUID. DocuSign → Paramètres → Intégrations → Applications et clés d'intégration.",
        "6f1e7a3c-2b8d-4c15-9a07-3d5e8b1f4a62",
    ),
    FieldSpec(
        "user_id",
        "ID utilisateur (GUID)",
        "L'utilisateur DocuSign au nom duquel les enveloppes sont envoyées (« User ID », un GUID). "
        "Même page que la clé d'intégration, rubrique « Mon compte API ».",
        "b7c2d4e1-8f30-4a59-b1c6-2e9d0a7f3c58",
    ),
    FieldSpec(
        "account_id",
        "ID de compte API",
        "L'identifiant du compte DocuSign (« API Account ID »), un GUID, au même endroit.",
        "e3a9c5b7-1d24-4f68-8a0b-6c7d2e1f9a43",
    ),
)

PRIVATE_KEY = FieldSpec(
    "private_key",
    "Clé privée RSA",
    "La clé privée générée avec l'application chez DocuSign (« Generate RSA »), au format PEM, "
    "avec les lignes BEGIN et END. DocuSign ne l'affiche qu'une fois. Chiffrée ici, jamais "
    "réaffichée.",
    "-----BEGIN RSA PRIVATE KEY-----\n…\n-----END RSA PRIVATE KEY-----",
    kind="textarea",
)

GUIDE = (
    "Créez un compte développeur gratuit sur developers.docusign.com : c'est le bac à sable, sans "
    "valeur légale. Pour la production, il faut un compte DocuSign avec accès à l'API.",
    "Connectez-vous (compte.docusign.com), Paramètres → Intégrations → Applications et clés "
    "d'intégration → « Ajouter une application et une clé d'intégration ».",
    "Dans l'application : méthode d'authentification « Authorization Code Grant » avec le JWT "
    "autorisé, puis « Générer RSA ». Copiez la clé privée tout de suite : elle ne sera plus "
    "affichée. Ajoutez une adresse de retour quelconque (https://localhost).",
    "Notez, sur la même page, la clé d'intégration, l'ID utilisateur et l'ID de compte API : ils "
    "vont dans les champs ci-dessous.",
    "Donnez le consentement une fois : ouvrez dans un navigateur "
    "https://account-d.docusign.com/oauth/auth?response_type=code&scope=signature%20impersonation"
    "&client_id=<clé d'intégration>&redirect_uri=<l'adresse de retour> (pour la production : "
    "account.docusign.com), connectez-vous et acceptez.",
    "Enregistrez ici, puis « Tester la connexion ». « consent_required » veut dire que l'étape 5 "
    "n'est pas faite ; « invalid_grant » que la clé privée ou les identifiants ne "
    "correspondent pas.",
)


def _public(row: DocusignConfig | None, settings: Settings) -> dict[str, Any]:
    return {
        "configured": bool(
            row
            and row.encrypted_private_key
            and row.integration_key
            and row.user_id
            and row.account_id
        ),
        "values": {
            "environment": row.environment if row else "demo",
            "integration_key": row.integration_key if row else "",
            "user_id": row.user_id if row else "",
            "account_id": row.account_id if row else "",
        },
        "has_private_key": bool(row and row.encrypted_private_key),
        "fields": [f.payload() for f in FIELDS],
        "private_key": PRIVATE_KEY.payload(),
        "guide": list(GUIDE),
        # The mock DocuSign only exists on a development or test server.
        "test_setup_available": settings.environment != "production",
        "mock": bool(row and row.environment == "test"),
    }


class DocusignRequest(BaseModel):
    environment: Literal["demo", "production"]
    integration_key: str
    user_id: str
    account_id: str
    # Left out to keep the one already stored.
    private_key: str | None = None


@router.get("")
def get_docusign(
    request: Request, user: User = Depends(_admin), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    return _public(db.get(DocusignConfig, 1), request.app.state.settings)


@router.put("")
def put_docusign(
    request: Request,
    body: DocusignRequest,
    user: User = Depends(_admin),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    for label, value in (
        ("la clé d'intégration", body.integration_key),
        ("l'ID utilisateur", body.user_id),
        ("l'ID de compte API", body.account_id),
    ):
        if not value.strip():
            raise HTTPException(422, f"Indiquez {label}.")
    row = db.get(DocusignConfig, 1)
    if body.private_key and body.private_key.strip():
        try:
            load_private_key(body.private_key)
        except DocusignError as exc:
            raise HTTPException(422, str(exc)) from exc
    elif row is None or not row.encrypted_private_key:
        raise HTTPException(422, "Collez la clé privée RSA donnée par DocuSign.")
    if row is None:
        row = DocusignConfig(id=1)
        db.add(row)
    row.environment = body.environment
    row.integration_key = body.integration_key.strip()
    row.user_id = body.user_id.strip()
    row.account_id = body.account_id.strip()
    row.auth_url = row.api_url = None
    if body.private_key and body.private_key.strip():
        row.encrypted_private_key = encrypt_secret(settings.master_key, body.private_key.strip())
    row.updated_by = user.id
    append_audit_event(
        db, action="DOCUSIGN_CONFIGURED", actor_id=user.id, target_type="docusign",
        metadata={"environment": body.environment},
    )
    db.commit()
    return _public(row, settings)


@router.post("/test-connection")
def test_connection(
    request: Request, user: User = Depends(_admin), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    config = load_settings(db, settings.master_key)
    if config is None:
        raise HTTPException(409, "DocuSign n'est pas encore configuré.")
    with httpx.Client(timeout=20.0) as http:
        try:
            return {"ok": True, "message": DocusignClient(http, config).check()}
        except DocusignError as exc:
            return {"ok": False, "message": str(exc)}


@router.post("/test-setup")
def use_the_mock(
    request: Request, user: User = Depends(_admin), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    """Point LCIT Sign at the mock DocuSign of the test stack, with a throwaway key."""
    settings: Settings = request.app.state.settings
    if settings.environment == "production":
        raise HTTPException(404, "Not found")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    row = db.get(DocusignConfig, 1)
    if row is None:
        row = DocusignConfig(id=1)
        db.add(row)
    row.environment = "test"
    row.integration_key = "mock-integration-key"
    row.user_id = "mock-user"
    row.account_id = "mock-account"
    row.auth_url = row.api_url = MOCK_URL
    row.encrypted_private_key = encrypt_secret(settings.master_key, pem)
    row.updated_by = user.id
    append_audit_event(
        db, action="DOCUSIGN_CONFIGURED", actor_id=user.id, target_type="docusign",
        metadata={"environment": "test"},
    )
    db.commit()
    return _public(row, settings)


def methods_payload(db: DbSession) -> list[dict[str, Any]]:
    """The ways to sign a request, for the "Faire signer" choice."""
    ready = is_configured(db)
    return [
        {
            "method": "LOCAL",
            "label": "Signature LCIT",
            "description": (
                "La signature de LCIT Sign : identité par votre SSO, empreinte du document, "
                "horodatage et preuve. Signature électronique simple."
            ),
            "available": True,
        },
        {
            "method": "DOCUSIGN",
            "label": "Signature eIDAS (DocuSign)",
            "description": (
                "Chaque signataire reçoit un e-mail de DocuSign et signe chez DocuSign. "
                "Le PDF signé et le certificat sont rapatriés ici."
            ),
            "available": ready,
            "unavailable_reason": None
            if ready
            else "DocuSign n'est pas configuré (Administration → DocuSign).",
        },
    ]
