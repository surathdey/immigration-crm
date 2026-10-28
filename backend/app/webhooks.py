"""Inbound Meta webhooks (WhatsApp + Facebook/Instagram) -> CRM leads.

UNAUTHENTICATED BY DESIGN: Meta cannot log in as a CRM user, so the
X-Hub-Signature-256 HMAC check is this endpoint's ONLY authentication.
Nothing is created when the signature is missing or invalid.

Env vars (read from os.environ at request time only; never hardcoded,
never logged):
  META_VERIFY_TOKEN — compared against hub.verify_token on the GET handshake
  META_APP_SECRET   — HMAC-SHA256 key for X-Hub-Signature-256 on POST
  META_PAGE_TOKEN   — optional Page access token for Lead Ads detail fetch

Leads land on the first tenant (lowest id) — the single-firm assumption.
Per-tenant routing (e.g. per-tenant verify tokens) is a follow-up before
multi-firm production use. Unknown event types are ignored with HTTP 200
(never 500) so Meta does not retry-storm them.
"""
import hashlib
import hmac
import json
import os
import urllib.request
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Session

from .db import Base, get_db
from .models import Lead, Tenant

router = APIRouter()


class WebhookEvent(Base):
    """Dedupe ledger: one row per Meta event that created a lead."""
    __tablename__ = "webhook_events"
    id = Column(Integer, primary_key=True)
    provider = Column(String, nullable=False)  # whatsapp | facebook | instagram
    event_id = Column(String, nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    received_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("provider", "event_id",
                                       name="uq_webhook_events_provider_event"),)


def _log(provider, event_type, event_id, outcome):
    print(f"[webhook] provider={provider} type={event_type} id={event_id} outcome={outcome}",
          flush=True)


def _default_tenant(db):
    return db.query(Tenant).order_by(Tenant.id).first()


def _already_seen(db, provider, event_id):
    return db.query(WebhookEvent).filter(
        WebhookEvent.provider == provider, WebhookEvent.event_id == event_id).first() is not None


def _create_lead(db, tenant, full_name, phone, email, source, notes):
    lead = Lead(tenant_id=tenant.id, branch_id=None, full_name=full_name, email=email or "",
                phone=phone or "", source=source, stream_of_interest="", stage="New", notes=notes or "")
    db.add(lead)
    db.flush()
    return lead


def _record(db, provider, event_id, lead):
    db.add(WebhookEvent(provider=provider, event_id=event_id, lead_id=lead.id if lead else None))
    db.commit()


@router.get("/api/webhooks/meta")
def meta_verify(request: Request):
    """Meta verification handshake: echo hub.challenge only on token match."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token") or ""
    challenge = request.query_params.get("hub.challenge") or ""
    verify = os.environ.get("META_VERIFY_TOKEN", "")
    if mode == "subscribe" and verify and hmac.compare_digest(token, verify):
        return PlainTextResponse(challenge)
    return PlainTextResponse("forbidden", status_code=403)


def _fetch_leadgen_fields(leadgen_id):
    """Fetch a Lead Ads lead's field_data via Graph API. Returns a dict of
    field name -> first value, or None when no Page token is set or the
    fetch fails. Error text is never returned or logged: it can contain
    the request URL (and therefore the token)."""
    token = os.environ.get("META_PAGE_TOKEN", "")
    if not token:
        return None
    url = f"https://graph.facebook.com/v19.0/{leadgen_id}?access_token={token}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    fields = {}
    for item in data.get("field_data", []) or []:
        values = item.get("values") or []
        fields[item.get("name", "")] = values[0] if values else ""
    return fields


def _handle_whatsapp(db, tenant, value, counts):
    contacts = {}
    for contact in value.get("contacts", []) or []:
        contacts[contact.get("wa_id")] = (contact.get("profile") or {}).get("name") or ""
    for msg in value.get("messages", []) or []:
        mid = msg.get("id") or ""
        if msg.get("type") != "text":
            _log("whatsapp", f"message:{msg.get('type')}", mid, "ignored: non-text")
            counts["ignored"] += 1
            continue
        if not mid:
            _log("whatsapp", "message", "-", "ignored: no id")
            counts["ignored"] += 1
            continue
        if _already_seen(db, "whatsapp", mid):
            _log("whatsapp", "message", mid, "duplicate")
            counts["duplicates"] += 1
            continue
        sender = msg.get("from") or ""
        name = contacts.get(sender) or f"WhatsApp user {sender}"
        text = (msg.get("text") or {}).get("body") or ""
        lead = _create_lead(db, tenant, name, sender, "", "WhatsApp", text)
        _record(db, "whatsapp", mid, lead)
        _log("whatsapp", "message", mid, f"lead {lead.id}")
        counts["created"] += 1


def _handle_leadgen(db, tenant, value, counts):
    leadgen_id = str(value.get("leadgen_id") or "")
    if not leadgen_id:
        _log("facebook", "leadgen", "-", "ignored: no leadgen_id")
        counts["ignored"] += 1
        return
    event_id = f"leadgen:{leadgen_id}"
    if _already_seen(db, "facebook", event_id):
        _log("facebook", "leadgen", leadgen_id, "duplicate")
        counts["duplicates"] += 1
        return
    fields = _fetch_leadgen_fields(leadgen_id)
    if fields is None:
        # No Page token, or the fetch failed: stub lead so nothing is lost.
        note = (f"leadgen_id: {leadgen_id}; details fetch pending Page token"
                if not os.environ.get("META_PAGE_TOKEN")
                else f"leadgen_id: {leadgen_id}; Graph fetch failed, manual follow-up needed")
        lead = _create_lead(db, tenant, f"Facebook Lead Ads {leadgen_id}", "", "", "Facebook", note)
    else:
        name = fields.get("full_name") or " ".join(
            p for p in (fields.get("first_name", ""), fields.get("last_name", "")) if p) \
            or f"Facebook Lead Ads {leadgen_id}"
        phone = fields.get("phone_number") or fields.get("phone") or ""
        email = fields.get("email") or ""
        used = {"full_name", "first_name", "last_name", "phone_number", "phone", "email"}
        extra = "\n".join(f"{k}: {v}" for k, v in fields.items() if k not in used and v)
        note = f"leadgen_id: {leadgen_id}" + (f"\n{extra}" if extra else "")
        lead = _create_lead(db, tenant, name, phone, email, "Facebook", note)
    _record(db, "facebook", event_id, lead)
    _log("facebook", "leadgen", leadgen_id, f"lead {lead.id}")
    counts["created"] += 1


def _handle_dm(db, tenant, provider, source, messaging, counts):
    for item in messaging or []:
        message = item.get("message") or {}
        mid = message.get("mid") or ""
        text = message.get("text") or ""
        sender_id = (item.get("sender") or {}).get("id") or ""
        if not mid or not text:
            _log(provider, "message", mid or "-", "ignored: no mid or no text")
            counts["ignored"] += 1
            continue
        event_id = f"msg:{mid}"
        if _already_seen(db, provider, event_id):
            _log(provider, "message", mid, "duplicate")
            counts["duplicates"] += 1
            continue
        lead = _create_lead(db, tenant, f"{source} message {sender_id}", "", "", source, text)
        _record(db, provider, event_id, lead)
        _log(provider, "message", mid, f"lead {lead.id}")
        counts["created"] += 1


@router.post("/api/webhooks/meta")
async def meta_post(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    secret = os.environ.get("META_APP_SECRET", "")
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not secret or not sig.startswith("sha256="):
        return JSONResponse({"status": "unauthorized"}, status_code=401)
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig[7:], expected):
        return JSONResponse({"status": "unauthorized"}, status_code=401)
    try:
        payload = json.loads(raw or b"{}")
    except Exception:
        _log("meta", "unparseable", "-", "ignored")
        return {"status": "ignored", "reason": "invalid json"}
    obj = payload.get("object") or ""
    counts = {"created": 0, "duplicates": 0, "ignored": 0}
    tenant = _default_tenant(db)
    if tenant is None:
        _log("meta", obj, "-", "ignored: no tenant configured")
        return {"status": "ignored", "reason": "no tenant configured"}
    for entry in payload.get("entry", []) or []:
        if obj == "whatsapp_business_account":
            for change in entry.get("changes", []) or []:
                _handle_whatsapp(db, tenant, change.get("value") or {}, counts)
        elif obj in ("page", "instagram"):
            for change in entry.get("changes", []) or []:
                if change.get("field") == "leadgen" and obj == "page":
                    _handle_leadgen(db, tenant, change.get("value") or {}, counts)
                else:
                    _log(obj, f"change:{change.get('field')}", "-", "ignored")
                    counts["ignored"] += 1
            if entry.get("messaging"):
                provider = "facebook" if obj == "page" else "instagram"
                source = "Facebook" if obj == "page" else "Instagram"
                _handle_dm(db, tenant, provider, source, entry["messaging"], counts)
        else:
            _log("meta", f"object:{obj}", "-", "ignored")
            counts["ignored"] += 1
    return {"status": "ok", **counts}
