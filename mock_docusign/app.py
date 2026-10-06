"""Throwaway DocuSign for the test stack: the little of the eSignature REST API that LCIT Sign
uses (JWT sign-in, create an envelope, its status, the signed PDF, the certificate), and a page
where the tester plays the signer. It signs nothing for real and has NO legal value; like the mock
SSO it must never be reachable from anything but a dev or CI environment.

Instead of DocuSign's e-mail, the signer finds the envelope in the inbox of this service
(`/`), opens it and clicks "Signer".
"""

from __future__ import annotations

import base64
import html
import json
import os
import threading
import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

STORE = Path(os.environ.get("MOCK_DOCUSIGN_DATA", "/tmp/mock-docusign"))  # noqa: S108
PUBLIC_BASE = os.environ.get("MOCK_DOCUSIGN_PUBLIC_BASE_URL", "http://localhost:8091").rstrip("/")
ACCOUNT_ID = os.environ.get("MOCK_DOCUSIGN_ACCOUNT_ID", "mock-account")

app = FastAPI(title="LCIT Sign — Mock DocuSign")
_lock = threading.Lock()


def _file() -> Path:
    STORE.mkdir(parents=True, exist_ok=True)
    return STORE / "envelopes.json"


def _load() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (OSError, ValueError):
        return {}


def _save(envelopes: dict[str, dict[str, Any]]) -> None:
    _file().write_text(json.dumps(envelopes), encoding="utf-8")


def _get(envelope_id: str) -> dict[str, Any]:
    envelope = _load().get(envelope_id)
    if envelope is None:
        raise HTTPException(404, detail={"errorCode": "ENVELOPE_DOES_NOT_EXIST"})
    return envelope


def _claims(assertion: str) -> dict[str, Any]:
    try:
        payload = assertion.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError):
        raise HTTPException(400, detail={"error": "invalid_grant"}) from None
    return data if isinstance(data, dict) else {}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


# --- the API LCIT Sign talks to --------------------------------------------------------------


@app.post("/oauth/token")
def token(grant_type: str = Form(...), assertion: str = Form(...)) -> JSONResponse:
    if grant_type != "urn:ietf:params:oauth:grant-type:jwt-bearer":
        return JSONResponse({"error": "unsupported_grant_type"}, 400)
    claims = _claims(assertion)
    scope = str(claims.get("scope"))
    if not claims.get("iss") or not claims.get("sub") or "signature" not in scope:
        return JSONResponse(
            {"error": "invalid_grant", "error_description": "assertion incomplète"}, 400
        )
    return JSONResponse(
        {"access_token": f"mock-{uuid.uuid4().hex}", "token_type": "Bearer", "expires_in": 3600}
    )


def _authorized(request: Request) -> None:
    if not request.headers.get("authorization", "").startswith("Bearer mock-"):
        raise HTTPException(401, detail={"errorCode": "AUTHORIZATION_INVALID_TOKEN"})


@app.get("/oauth/userinfo")
def userinfo(request: Request) -> dict[str, Any]:
    _authorized(request)
    return {
        "accounts": [{"account_id": ACCOUNT_ID, "is_default": True, "base_uri": PUBLIC_BASE}]
    }


@app.post("/restapi/v2.1/accounts/{account}/envelopes")
def create_envelope(
    account: str, request: Request, body: dict[str, Any] = Body(...)
) -> dict[str, Any]:
    _authorized(request)
    try:
        document = body["documents"][0]
        signer = body["recipients"]["signers"][0]
        pdf = base64.b64decode(document["documentBase64"])
        PdfReader(BytesIO(pdf))
    except (KeyError, IndexError, ValueError, TypeError):
        raise HTTPException(400, detail={"errorCode": "INVALID_REQUEST_BODY"}) from None
    envelope_id = str(uuid.uuid4())
    entry = {
        "id": envelope_id,
        "status": "sent",
        "subject": body.get("emailSubject", ""),
        "message": body.get("emailBlurb", ""),
        "name": document.get("name", "document.pdf"),
        "pdf": document["documentBase64"],
        "signer": {"name": signer.get("name", ""), "email": signer.get("email", "")},
        "tabs": signer.get("tabs", {}),
        "created": datetime.now(UTC).isoformat(),
        "completed": None,
    }
    with _lock:
        envelopes = _load()
        envelopes[envelope_id] = entry
        _save(envelopes)
    return {"envelopeId": envelope_id, "status": "sent", "uri": f"/envelopes/{envelope_id}"}


@app.get("/restapi/v2.1/accounts/{account}/envelopes/{envelope_id}")
def envelope_status(account: str, envelope_id: str, request: Request) -> dict[str, str]:
    _authorized(request)
    return {"envelopeId": envelope_id, "status": _get(envelope_id)["status"]}


@app.put("/restapi/v2.1/accounts/{account}/envelopes/{envelope_id}")
def change_envelope(
    account: str, envelope_id: str, request: Request, body: dict[str, Any] = Body(...)
) -> dict[str, str]:
    _authorized(request)
    with _lock:
        envelopes = _load()
        entry = envelopes.get(envelope_id)
        if entry is None:
            raise HTTPException(404, detail={"errorCode": "ENVELOPE_DOES_NOT_EXIST"})
        if body.get("status") == "voided" and entry["status"] != "completed":
            entry["status"] = "voided"
            _save(envelopes)
    return {"envelopeId": envelope_id, "status": entry["status"]}


def _signed_pdf(entry: dict[str, Any]) -> bytes:
    """The document with what each tab asks drawn at its place, and a last page that says it
    is a simulation."""
    original = base64.b64decode(entry["pdf"])
    reader = PdfReader(BytesIO(original))
    writer = PdfWriter()
    when = (entry.get("completed") or datetime.now(UTC).isoformat())[:10]
    signer = entry["signer"]
    drawn = {
        "signHereTabs": lambda: signer["name"],
        "fullNameTabs": lambda: signer["name"],
        "emailTabs": lambda: signer["email"],
        "dateSignedTabs": lambda: when,
        "firstNameTabs": lambda: signer["name"].split(" ")[0],
        "lastNameTabs": lambda: " ".join(signer["name"].split(" ")[1:]),
        "textTabs": lambda: "(saisi)",
    }
    for number, page in enumerate(reader.pages, start=1):
        height = float(page.mediabox.height)
        width = float(page.mediabox.width)
        overlay = BytesIO()
        pen = canvas.Canvas(overlay, pagesize=(width, height))
        for key, tabs in entry["tabs"].items():
            for tab in tabs:
                if int(tab.get("pageNumber", 1)) != number or key not in drawn:
                    continue
                pen.setFont("Helvetica-Oblique" if key == "signHereTabs" else "Helvetica", 10)
                pen.drawString(
                    float(tab["xPosition"]) + 2, height - float(tab["yPosition"]) - 12, drawn[key]()
                )
        pen.showPage()  # a page even when nothing is drawn on this one
        pen.save()
        overlay.seek(0)
        page.merge_page(PdfReader(overlay).pages[0])
        writer.add_page(page)
    last = BytesIO()
    pen = canvas.Canvas(last, pagesize=A4)
    pen.setFont("Helvetica-Bold", 14)
    pen.drawString(60, 760, "Signé électroniquement via DocuSign (SIMULATION)")
    pen.setFont("Helvetica", 10)
    pen.drawString(60, 735, f"Enveloppe : {entry['id']}")
    pen.drawString(60, 720, f"Signataire : {signer['name']} <{signer['email']}>")
    pen.drawString(60, 705, f"Date : {entry.get('completed')}")
    pen.drawString(60, 680, "Faux DocuSign de test : aucune valeur légale.")
    pen.save()
    last.seek(0)
    writer.add_page(PdfReader(last).pages[0])
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _certificate(entry: dict[str, Any]) -> bytes:
    buffer = BytesIO()
    pen = canvas.Canvas(buffer, pagesize=A4)
    pen.setFont("Helvetica-Bold", 16)
    pen.drawString(60, 770, "Certificat d'achèvement DocuSign (SIMULATION)")
    pen.setFont("Helvetica", 10)
    lines = [
        f"Enveloppe : {entry['id']}",
        f"Document : {entry['name']}",
        f"Signataire : {entry['signer']['name']} <{entry['signer']['email']}>",
        f"Envoyé : {entry['created']}",
        f"Terminé : {entry.get('completed')}",
        "Faux DocuSign de test : ce certificat n'a aucune valeur légale.",
    ]
    for index, line in enumerate(lines):
        pen.drawString(60, 740 - 16 * index, line)
    pen.save()
    return buffer.getvalue()


@app.get("/restapi/v2.1/accounts/{account}/envelopes/{envelope_id}/documents/{which}")
def documents(account: str, envelope_id: str, which: str, request: Request) -> Response:
    _authorized(request)
    entry = _get(envelope_id)
    if entry["status"] != "completed":
        raise HTTPException(409, detail={"errorCode": "ENVELOPE_NOT_COMPLETED"})
    if which == "combined":
        return Response(_signed_pdf(entry), media_type="application/pdf")
    if which == "certificate":
        return Response(_certificate(entry), media_type="application/pdf")
    raise HTTPException(404, detail={"errorCode": "DOCUMENT_NOT_FOUND"})


# --- the page where the tester plays the signer ----------------------------------------------


def _page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"""<html><head><meta charset="utf-8"><title>DocuSign (simulation)</title></head>
        <body style="font-family: sans-serif; max-width: 640px; margin: 40px auto;">
        <h2>DocuSign — simulation de test</h2>
        <p style="color:#b42318">Faux DocuSign : aucune valeur légale.</p>{body}</body></html>""",
        status_code=status,
    )


@app.get("/", response_class=HTMLResponse)
def inbox() -> HTMLResponse:
    rows = sorted(_load().values(), key=lambda e: e["created"], reverse=True)
    items = "".join(
        f'<li><a href="sign/{e["id"]}">{html.escape(e["subject"] or e["name"])}</a> — '
        f"{html.escape(e['signer']['name'])} &lt;{html.escape(e['signer']['email'])}&gt; — "
        f"<b>{html.escape(e['status'])}</b></li>"
        for e in rows
    )
    return _page(
        "<p>Les e-mails que DocuSign enverrait aux signataires :</p>"
        + (f"<ul>{items}</ul>" if items else "<p>Aucune enveloppe pour l'instant.</p>")
    )


@app.get("/sign/{envelope_id}", response_class=HTMLResponse)
def sign_page(envelope_id: str) -> HTMLResponse:
    entry = _get(envelope_id)
    signer = entry["signer"]
    title = html.escape(entry["subject"] or entry["name"])
    if entry["status"] != "sent":
        state = html.escape(entry["status"])
        return _page(f"<h3>{title}</h3><p>Cette enveloppe est : <b>{state}</b>.</p>")
    return _page(
        f"""<h3>{title}</h3><p>{html.escape(entry["message"])}</p>
        <p>Signataire : {html.escape(signer["name"])} &lt;{html.escape(signer["email"])}&gt;</p>
        <form method="post" action="{envelope_id}" style="display:flex;gap:8px">
          <button name="action" value="sign" type="submit">Signer (simulation)</button>
          <button name="action" value="decline" type="submit">Refuser</button>
        </form>"""
    )


@app.post("/sign/{envelope_id}")
def sign_action(envelope_id: str, action: str = Form(...)) -> RedirectResponse:
    with _lock:
        envelopes = _load()
        entry = envelopes.get(envelope_id)
        if entry is None:
            raise HTTPException(404)
        if entry["status"] == "sent":
            entry["status"] = "completed" if action == "sign" else "declined"
            entry["completed"] = datetime.now(UTC).isoformat() if action == "sign" else None
            _save(envelopes)
    return RedirectResponse(envelope_id, status_code=303)
