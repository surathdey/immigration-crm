"""AI-drafted staff messages — Feature 17. Human gate, never auto-sent.

Provider choice (List B item 5, decided at build start): the built-in
template adapter (AI_PROVIDER=template, the default). It drafts ONLY
from stored case data — the stream template's checklist and the case's
own deadlines — so it cannot invent a case fact, cannot train on firm
or client data (no data leaves the firm), and is reversible: swapping
to a managed model API later is a configuration change behind this
module's build_* functions, and no provider change may alter the human
gate below.

The gate, enforced here:
- A draft is a row, not a send. Nothing is sent by creating a draft.
- Only a staff approve action sends, through the normal message path,
  and the sent message is logged as a STAFF message (source="staff")
  with the draft id recorded — never as an AI message.
- In log mode an approved draft is recorded as 'would send' and
  delivered to nobody, exactly as Features 11 and 12 require.
- Drafts are tenant-scoped: a draft is built only from a case the
  staff member's firm owns.
"""
import json
import os
from datetime import datetime, timedelta

from .models_phase2 import AiDraft, Deadline
from .models import StreamTemplate, Client
from . import messaging

AI_PROVIDER = os.environ.get("AI_PROVIDER", "template")


def _require_template_provider():
    if AI_PROVIDER != "template":
        raise ValueError(
            f"AI provider '{AI_PROVIDER}' is not configured. Set AI_PROVIDER=template "
            "(built-in, uses only stored case data) or configure a managed provider.")


def build_document_request_draft(db, tenant_id, case):
    """Names exactly the stream template's checklist items. Phase 2 has
    no per-case checklist tracking (that arrives in Phase 3), so the
    template checklist is the missing-items list — stated, not hidden."""
    _require_template_provider()
    template = db.query(StreamTemplate).filter(
        StreamTemplate.tenant_id == tenant_id,
        StreamTemplate.stream == case.stream).first()
    client = db.query(Client).filter(Client.id == case.client_id).first()
    name = client.full_name if client else ""
    if not template:
        body = (f"Hi {name}, for your {case.stream} case we need to confirm "
                "which documents are still outstanding — no checklist is on "
                "file for this stream, so please review the case before sending.")
        return body, "document_request"
    items = json.loads(template.checklist)
    lines = "\n".join(f"- {item}" for item in items)
    body = (f"Hi {name}, for your {case.stream} case we still need the "
            f"following documents:\n{lines}\n"
            "Please send them at your earliest convenience.")
    return body, "document_request"


def build_deadline_summary_draft(db, tenant_id, case):
    """Names the case's real upcoming deadlines (next 30 days)."""
    _require_template_provider()
    client = db.query(Client).filter(Client.id == case.client_id).first()
    name = client.full_name if client else ""
    horizon = datetime.utcnow() + timedelta(days=30)
    rows = db.query(Deadline).filter(
        Deadline.tenant_id == tenant_id, Deadline.case_id == case.id,
        Deadline.done == False, Deadline.due_date <= horizon).order_by(Deadline.due_date).all()  # noqa: E712
    if not rows:
        return (f"Hi {name}, there are no upcoming deadlines in the next 30 "
                f"days for your {case.stream} case."), "deadline_summary"
    lines = "\n".join(f"- {d.title}: due {d.due_date.strftime('%d %B %Y')}" for d in rows)
    body = (f"Hi {name}, here is a summary of upcoming deadlines for your "
            f"{case.stream} case:\n{lines}")
    return body, "deadline_summary"


def create_draft(db, tenant_id, case, kind, channel, user_id=None):
    if kind == "document_request":
        body, _ = build_document_request_draft(db, tenant_id, case)
        subject = "Documents needed for your case"
    elif kind == "deadline_summary":
        body, _ = build_deadline_summary_draft(db, tenant_id, case)
        subject = "Upcoming deadlines for your case"
    else:
        raise ValueError(f"Unknown draft kind: {kind}")
    draft = AiDraft(tenant_id=tenant_id, case_id=case.id, kind=kind, channel=channel,
                    subject=subject if channel == "email" else "", body=body,
                    source=f"ai_{AI_PROVIDER}_adapter", status="draft")
    db.add(draft)
    db.flush()
    messaging.audit(db, tenant_id, user_id, "draft_created", "ai_draft", draft.id,
                    f"{kind} ({channel}) for case {case.id}")
    db.commit()
    db.refresh(draft)
    return draft


def draft_case_client_id(db, draft):
    from .models import Case
    case = db.query(Case).filter(Case.id == draft.case_id).first()
    return case.client_id if case else None


def approve_draft(db, tenant_id, draft, user, firm_name):
    """Staff presses send: the draft goes through the normal message
    path and is logged as a STAFF message with the draft id recorded.
    The draft itself never sends."""
    if draft.status != "draft":
        raise ValueError(f"Draft is {draft.status}, not open for approval.")
    case_client = db.query(Client).filter(Client.id == draft_case_client_id(db, draft)).first()
    if draft.channel == "sms":
        if not case_client or not case_client.phone:
            raise ValueError("No phone number on record for this client.")
        msg = messaging.send_sms(db, tenant_id, firm_name, case_client.phone, draft.body,
                                 case_id=draft.case_id, template_key="",
                                 source="staff", draft_id=draft.id, user_id=user.id,
                                 client_id=case_client.id)
    else:
        if not case_client or not case_client.email:
            raise ValueError("No email address on record for this client.")
        msg = messaging.send_email(db, tenant_id, firm_name, case_client.email,
                                   draft.subject, draft.body,
                                   case_id=draft.case_id, template_key="",
                                   source="staff", draft_id=draft.id, user_id=user.id,
                                   client_id=case_client.id)
    draft.status = "approved"
    messaging.audit(db, tenant_id, user.id, "draft_approved", "ai_draft", draft.id,
                    f"sent as staff message #{msg.id} ({msg.status})")
    db.commit()
    db.refresh(draft)
    return draft, msg
