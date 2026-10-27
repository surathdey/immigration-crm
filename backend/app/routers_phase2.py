"""Phase 2 API routes (Features 11–17). Mounted by main.py.

Tenant scoping follows Phase 1 (auth.scope_filter). Settings gates
(sender verification, test receipt) are firm_admin-only and audited.
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db
from .models import Tenant, User, Lead, Client, Case
from .models_phase2 import (FirmSettings, MessageTemplate, SmsOptOut,
                            CaseMessage, EventType, Consultation, CalendarBlock,
                            CalendarConnection, Deadline, ActionItem, AiDraft,
                            AuditLog)
from . import auth, messaging, booking, ai_drafts

router = APIRouter()


def settings_out(s: FirmSettings):
    return {"sms_mode": s.sms_mode, "sms_sender": s.sms_sender,
            "sms_sender_verified": s.sms_sender_verified,
            "sms_test_received": s.sms_test_received,
            "email_mode": s.email_mode, "email_sender": s.email_sender,
            "email_sender_verified": s.email_sender_verified,
            "email_test_received": s.email_test_received,
            "opt_out_wording": s.opt_out_wording,
            "deadline_reminder_days": json.loads(s.deadline_reminder_days),
            "consultation_reminder_hours": json.loads(s.consultation_reminder_hours),
            "calendly_account": s.calendly_account}


def msg_out(m: CaseMessage):
    return {"id": m.id, "case_id": m.case_id, "lead_id": m.lead_id, "client_id": m.client_id,
            "channel": m.channel, "sender": m.sender, "recipient": m.recipient,
            "subject": m.subject, "body": m.body, "template_key": m.template_key,
            "status": m.status, "provider_status": m.provider_status,
            "source": m.source, "draft_id": m.draft_id, "at": str(m.created_at)}


def cons_out(c: Consultation):
    return {"id": c.id, "lead_id": c.lead_id, "client_id": c.client_id,
            "case_id": c.case_id, "consultant_id": c.consultant_id,
            "event_type_id": c.event_type_id, "kind": c.kind,
            "starts_at": str(c.starts_at), "ends_at": str(c.ends_at),
            "status": c.status, "source": c.source,
            "payment_status": c.payment_status, "sync_status": c.sync_status,
            "sync_error": c.sync_error, "google_event_id": c.google_event_id,
            "calendly_event_id": c.calendly_event_id}


def require_admin(user: User):
    if user.role != "firm_admin":
        raise HTTPException(403, "Firm admin only")


# ---------- communications settings ----------
@router.get("/api/settings/communications")
def get_comms(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    messaging.ensure_templates(db, user.tenant_id)
    s = messaging.get_settings(db, user.tenant_id)
    rows = db.query(MessageTemplate).filter(MessageTemplate.tenant_id == user.tenant_id).all()
    return {"settings": settings_out(s),
            "templates": [{"id": t.id, "key": t.key, "channel": t.channel,
                           "subject": t.subject, "body": t.body} for t in rows]}


class CommsPatch(BaseModel):
    sms_mode: str | None = None
    sms_sender: str | None = None
    email_mode: str | None = None
    email_sender: str | None = None
    opt_out_wording: str | None = None
    deadline_reminder_days: list | None = None
    consultation_reminder_hours: list | None = None
    calendly_account: str | None = None


@router.patch("/api/settings/communications")
def patch_comms(body: CommsPatch, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    require_admin(user)
    s = messaging.get_settings(db, user.tenant_id)
    data = body.model_dump(exclude_unset=True)
    if "sms_mode" in data and data["sms_mode"] not in ("log", "live"):
        raise HTTPException(400, "sms_mode must be log or live")
    if "email_mode" in data and data["email_mode"] not in ("log", "live"):
        raise HTTPException(400, "email_mode must be log or live")
    for k in ("deadline_reminder_days", "consultation_reminder_hours"):
        if k in data:
            data[k] = json.dumps(data[k])
    for k, v in data.items():
        setattr(s, k, v)
    messaging.audit(db, user.tenant_id, user.id, "comms_settings_changed",
                    "firm_settings", s.id, ", ".join(sorted(data.keys())))
    db.commit()
    db.refresh(s)
    return {"settings": settings_out(s)}


class GateBody(BaseModel):
    channel: str  # sms | email


@router.post("/api/settings/communications/verify-sender")
def verify_sender(body: GateBody, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """Records the firm's attestation that its sender identity is verified
    at the provider (Twilio number ownership / SendGrid domain auth).
    Verification itself happens at the provider; this flag is the CRM's
    record of it, and the send adapter refuses live sending without it."""
    require_admin(user)
    if body.channel not in ("sms", "email"):
        raise HTTPException(400, "channel must be sms or email")
    s = messaging.get_settings(db, user.tenant_id)
    if body.channel == "sms":
        if not s.sms_sender:
            raise HTTPException(400, "Set an SMS sender first.")
        s.sms_sender_verified = True
    else:
        if not s.email_sender:
            raise HTTPException(400, "Set an email sender first.")
        s.email_sender_verified = True
    messaging.audit(db, user.tenant_id, user.id, "sender_verified",
                    "firm_settings", s.id, body.channel)
    db.commit()
    return {"settings": settings_out(s)}


@router.post("/api/settings/communications/confirm-test-received")
def confirm_test(body: GateBody, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """Staff confirms a test message was actually received under the
    firm's own sender identity. Live sending stays off until this and
    verification both pass."""
    require_admin(user)
    if body.channel not in ("sms", "email"):
        raise HTTPException(400, "channel must be sms or email")
    s = messaging.get_settings(db, user.tenant_id)
    if body.channel == "sms":
        s.sms_test_received = True
    else:
        s.email_test_received = True
    messaging.audit(db, user.tenant_id, user.id, "test_received_confirmed",
                    "firm_settings", s.id, body.channel)
    db.commit()
    return {"settings": settings_out(s)}


class OptOutBody(BaseModel):
    phone: str


@router.post("/api/settings/communications/opt-out")
def record_opt_out(body: OptOutBody, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    if not db.query(SmsOptOut).filter(
            SmsOptOut.tenant_id == user.tenant_id, SmsOptOut.phone == body.phone).first():
        db.add(SmsOptOut(tenant_id=user.tenant_id, phone=body.phone))
        messaging.audit(db, user.tenant_id, user.id, "sms_opt_out",
                        "sms_opt_out", None, body.phone)
        db.commit()
    return {"opted_out": body.phone}


class TemplatePatch(BaseModel):
    subject: str | None = None
    body: str | None = None


@router.patch("/api/settings/communications/templates/{template_id}")
def patch_template(template_id: int, body: TemplatePatch, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    require_admin(user)
    t = db.query(MessageTemplate).filter(
        MessageTemplate.id == template_id, MessageTemplate.tenant_id == user.tenant_id).first()
    if not t:
        raise HTTPException(404, "Template not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(t, k, v)
    messaging.audit(db, user.tenant_id, user.id, "template_edited",
                    "message_template", t.id, t.key)
    db.commit()
    return {"id": t.id, "key": t.key, "channel": t.channel, "subject": t.subject, "body": t.body}


# ---------- messages ----------
def _case_for(user, db, case_id):
    case = auth.scope_filter(user, db.query(Case), Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    return case


def _lead_for(user, db, lead_id):
    lead = auth.scope_filter(user, db.query(Lead), Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead


@router.get("/api/cases/{case_id}/messages")
def case_messages(case_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    _case_for(user, db, case_id)
    rows = db.query(CaseMessage).filter(
        CaseMessage.tenant_id == user.tenant_id, CaseMessage.case_id == case_id
    ).order_by(CaseMessage.created_at, CaseMessage.id).all()
    return [msg_out(m) for m in rows]


@router.get("/api/clients/{client_id}/messages")
def client_messages(client_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    client = auth.scope_filter(user, db.query(Client), Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(404, "Client not found")
    rows = db.query(CaseMessage).filter(
        CaseMessage.tenant_id == user.tenant_id, CaseMessage.client_id == client_id
    ).order_by(CaseMessage.created_at, CaseMessage.id).all()
    return [msg_out(m) for m in rows]


@router.get("/api/leads/{lead_id}/messages")
def lead_messages(lead_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    _lead_for(user, db, lead_id)
    rows = db.query(CaseMessage).filter(
        CaseMessage.tenant_id == user.tenant_id, CaseMessage.lead_id == lead_id
    ).order_by(CaseMessage.created_at, CaseMessage.id).all()
    return [msg_out(m) for m in rows]


class ComposeBody(BaseModel):
    channel: str  # sms | email
    template_key: str = ""
    body: str = ""
    subject: str = ""


def _compose(user, db, case, lead, body: ComposeBody):
    if body.channel not in ("sms", "email"):
        raise HTTPException(400, "channel must be sms or email")
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    firm_name = tenant.name if tenant else ""
    if case:
        client = db.query(Client).filter(Client.id == case.client_id).first()
        name, stream = (client.full_name, case.stream) if client else ("", case.stream)
        case_id, lead_id = case.id, None
        phone, email = (client.phone, client.email) if client else ("", "")
        compose_client_id = client.id if client else None
    else:
        name, stream = lead.full_name, lead.stream_of_interest
        case_id, lead_id = None, lead.id
        phone, email = lead.phone, lead.email
        compose_client_id = None
    text, subject = body.body, body.subject
    if body.template_key:
        messaging.ensure_templates(db, user.tenant_id)
        t = db.query(MessageTemplate).filter(
            MessageTemplate.tenant_id == user.tenant_id,
            MessageTemplate.key == body.template_key,
            MessageTemplate.channel == body.channel).first()
        if not t:
            raise HTTPException(400, f"Unknown template: {body.template_key}")
        text = messaging.render(t.body, name, stream, case_id or lead_id, firm_name)
        subject = messaging.render(t.subject, name, stream, case_id or lead_id, firm_name)
    try:
        if body.channel == "sms":
            msg = messaging.send_sms(db, user.tenant_id, firm_name, phone, text,
                                     case_id=case_id, lead_id=lead_id,
                                     template_key=body.template_key, source="staff",
                                     user_id=user.id, client_id=compose_client_id)
        else:
            msg = messaging.send_email(db, user.tenant_id, firm_name, email, subject, text,
                                       case_id=case_id, lead_id=lead_id,
                                       template_key=body.template_key, source="staff",
                                       user_id=user.id, client_id=compose_client_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return msg_out(msg)


@router.post("/api/cases/{case_id}/messages")
def compose_case_message(case_id: int, body: ComposeBody, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    return _compose(user, db, _case_for(user, db, case_id), None, body)


@router.post("/api/leads/{lead_id}/messages")
def compose_lead_message(lead_id: int, body: ComposeBody, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    return _compose(user, db, None, _lead_for(user, db, lead_id), body)


# ---------- event types ----------
class EventTypeIn(BaseModel):
    consultant_id: int
    name: str = "Consultation"
    slot_minutes: int = 30
    buffer_minutes: int = 0
    working_hours: dict | None = None
    paid: bool = False
    price_cents: int = 0


@router.get("/api/event-types")
def list_event_types(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    rows = db.query(EventType).filter(EventType.tenant_id == user.tenant_id).all()
    return [{"id": e.id, "consultant_id": e.consultant_id, "name": e.name,
             "slot_minutes": e.slot_minutes, "buffer_minutes": e.buffer_minutes,
             "working_hours": json.loads(e.working_hours), "paid": e.paid,
             "price_cents": e.price_cents, "slug": e.slug,
             "booking_link": f"/book/{e.slug}" if e.slug else None} for e in rows]


@router.post("/api/event-types")
def create_event_type(body: EventTypeIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    consultant = db.query(User).filter(
        User.id == body.consultant_id, User.tenant_id == user.tenant_id).first()
    if not consultant:
        raise HTTPException(404, "Consultant not found")
    slug = f"{consultant.full_name.lower().replace(' ', '-')}-{body.name.lower().replace(' ', '-')}"
    et = EventType(tenant_id=user.tenant_id, consultant_id=body.consultant_id,
                   name=body.name, slot_minutes=body.slot_minutes,
                   buffer_minutes=body.buffer_minutes,
                   working_hours=json.dumps(body.working_hours or booking.DEFAULT_HOURS),
                   paid=body.paid, price_cents=body.price_cents, slug=slug)
    db.add(et)
    messaging.audit(db, user.tenant_id, user.id, "event_type_created",
                    "event_type", None, slug)
    db.commit()
    db.refresh(et)
    return {"id": et.id, "slug": et.slug, "booking_link": f"/book/{et.slug}"}


# ---------- consultations ----------
class ConsIn(BaseModel):
    consultant_id: int
    starts_at: str
    ends_at: str
    lead_id: int | None = None
    client_id: int | None = None
    case_id: int | None = None
    event_type_id: int | None = None
    kind: str = "Consultation"
    payment_status: str = "pending"
    google_event_id: str = ""
    calendly_event_id: str = ""


@router.get("/api/consultations")
def list_consultations(consultant_id: int | None = None, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    q = auth.scope_filter(user, db.query(Consultation), Consultation)
    if consultant_id:
        q = q.filter(Consultation.consultant_id == consultant_id)
    return [cons_out(c) for c in q.order_by(Consultation.starts_at).all()]


@router.post("/api/consultations")
def create_consultation(body: ConsIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    if body.lead_id:
        _lead_for(user, db, body.lead_id)
    if body.client_id and not db.query(Client).filter(
            Client.id == body.client_id, Client.tenant_id == user.tenant_id).first():
        raise HTTPException(404, "Client not found")
    if body.case_id:
        _case_for(user, db, body.case_id)
    try:
        cons = booking.book_consultation(db, user, body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return cons_out(cons)


@router.get("/api/consultations/{cons_id}")
def get_consultation(cons_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    cons = auth.scope_filter(user, db.query(Consultation), Consultation).filter(Consultation.id == cons_id).first()
    if not cons:
        raise HTTPException(404, "Consultation not found")
    return cons_out(cons)


class ConsPatch(BaseModel):
    starts_at: str | None = None
    ends_at: str | None = None
    status: str | None = None  # cancelled | completed | no_show


@router.patch("/api/consultations/{cons_id}")
def patch_consultation(cons_id: int, body: ConsPatch, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    cons = auth.scope_filter(user, db.query(Consultation), Consultation).filter(Consultation.id == cons_id).first()
    if not cons:
        raise HTTPException(404, "Consultation not found")
    if body.starts_at or body.ends_at:
        if cons.status in ("cancelled", "cancelled_externally", "completed"):
            raise HTTPException(400, f"Cannot reschedule a {cons.status} consultation.")
        new_start = booking.parse_dt(body.starts_at) if body.starts_at else cons.starts_at
        new_end = booking.parse_dt(body.ends_at) if body.ends_at else cons.ends_at
        hours, buffer_minutes = booking.hours_for(db, user.tenant_id, cons.consultant_id)
        if cons.event_type_id:
            et = db.query(EventType).filter(EventType.id == cons.event_type_id).first()
            if et:
                try:
                    hours = json.loads(et.working_hours)
                except (ValueError, TypeError):
                    pass
                buffer_minutes = et.buffer_minutes
        if not booking.within_hours(hours, new_start, new_end):
            raise HTTPException(400, "Reschedule outside working hours is refused.")
        if booking.overlaps(db, user.tenant_id, cons.consultant_id, new_start, new_end,
                            buffer_minutes, exclude_id=cons.id):
            raise HTTPException(400, "Rescheduled slot overlaps an existing booking.")
        cons.starts_at, cons.ends_at, cons.status = new_start, new_end, "rescheduled"
        cons.sync_status = booking.push_to_google(db, cons)
        booking.notify_consultation(db, cons, "rescheduled", user_id=user.id)
        messaging.audit(db, user.tenant_id, user.id, "consultation_rescheduled",
                        "consultation", cons.id, f"to {new_start}")
    elif body.status == "cancelled":
        if cons.status in ("cancelled", "cancelled_externally"):
            raise HTTPException(400, "Already cancelled.")
        cons.status = "cancelled"
        cons.sync_status = booking.push_to_google(db, cons)
        booking.notify_consultation(db, cons, "cancelled", user_id=user.id)
        messaging.audit(db, user.tenant_id, user.id, "consultation_cancelled",
                        "consultation", cons.id, "")
    elif body.status == "completed":
        cons.status = "completed"
        messaging.audit(db, user.tenant_id, user.id, "consultation_completed",
                        "consultation", cons.id, "")
    elif body.status == "no_show":
        cons.status = "no_show"
        booking.notify_consultation(db, cons, "no_show_reschedule", user_id=user.id)
        messaging.audit(db, user.tenant_id, user.id, "consultation_no_show",
                        "consultation", cons.id, "")
    elif body.status is not None:
        raise HTTPException(400, f"Unknown status: {body.status}")
    db.commit()
    db.refresh(cons)
    return cons_out(cons)


@router.post("/api/consultations/{cons_id}/confirm-payment")
def confirm_payment(cons_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    cons = auth.scope_filter(user, db.query(Consultation), Consultation).filter(Consultation.id == cons_id).first()
    if not cons:
        raise HTTPException(404, "Consultation not found")
    if cons.status != "payment_pending":
        raise HTTPException(400, f"Consultation is {cons.status}, not awaiting payment.")
    cons.status, cons.payment_status = "booked", "paid"
    cons.sync_status = booking.push_to_google(db, cons)
    booking.notify_consultation(db, cons, "confirmation", user_id=user.id)
    messaging.audit(db, user.tenant_id, user.id, "consultation_payment_confirmed",
                    "consultation", cons.id, "")
    db.commit()
    db.refresh(cons)
    return cons_out(cons)


# ---------- week view + calendar connection + Google webhook ----------
@router.get("/api/calendar/week")
def week_view(consultant_id: int, from_date: str, to_date: str,
              user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    frm, to = booking.parse_dt(from_date), booking.parse_dt(to_date)
    cons = auth.scope_filter(user, db.query(Consultation), Consultation).filter(
        Consultation.consultant_id == consultant_id,
        Consultation.starts_at >= frm, Consultation.starts_at < to).all()
    blocks = db.query(CalendarBlock).filter(
        CalendarBlock.tenant_id == user.tenant_id,
        CalendarBlock.consultant_id == consultant_id,
        CalendarBlock.starts_at >= frm, CalendarBlock.starts_at < to).all()
    dls = db.query(Deadline).filter(
        Deadline.tenant_id == user.tenant_id, Deadline.done == False,
        Deadline.due_date >= frm, Deadline.due_date < to).all()  # noqa: E712
    return {"consultations": [cons_out(c) for c in cons],
            "blocked_slots": [{"id": b.id, "starts_at": str(b.starts_at),
                               "ends_at": str(b.ends_at), "title": b.title} for b in blocks],
            "deadlines": [{"id": d.id, "case_id": d.case_id, "title": d.title,
                           "due_date": str(d.due_date), "deadline_type": d.deadline_type} for d in dls]}


class ConnectBody(BaseModel):
    calendar_id: str = "primary"


@router.post("/api/calendar/connect")
def connect_calendar(body: ConnectBody, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """Records a staff calendar connection (stub OAuth: the real Google
    OAuth flow needs the registered Google app — List B item 4. No token
    is stored here, ever)."""
    conn = db.query(CalendarConnection).filter(
        CalendarConnection.tenant_id == user.tenant_id,
        CalendarConnection.user_id == user.id).first()
    if not conn:
        conn = CalendarConnection(tenant_id=user.tenant_id, user_id=user.id)
        db.add(conn)
    conn.connected, conn.calendar_id = True, body.calendar_id
    messaging.audit(db, user.tenant_id, user.id, "calendar_connected",
                    "calendar_connection", conn.id, body.calendar_id)
    db.commit()
    return {"connected": True, "calendar_id": body.calendar_id,
            "note": "Stub connection: real Google OAuth arrives with the registered Google app."}


class GoogleWebhookBody(BaseModel):
    firm_slug: str
    consultant_id: int
    google_event_id: str
    action: str  # created | moved | deleted
    starts_at: str | None = None
    ends_at: str | None = None


@router.post("/api/calendar/google-webhook")
def google_webhook(body: GoogleWebhookBody, db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.slug == body.firm_slug).first()
    if not tenant:
        raise HTTPException(404, "Firm not found")
    tid = tenant.id
    if body.action == "created":
        if not body.starts_at or not body.ends_at:
            raise HTTPException(400, "starts_at and ends_at required for created.")
        starts_at, ends_at = booking.parse_dt(body.starts_at), booking.parse_dt(body.ends_at)
        hours, _ = booking.hours_for(db, tid, body.consultant_id)
        if not booking.within_hours(hours, starts_at, ends_at):
            return {"ignored": "outside working hours — personal events are never imported"}
        if db.query(CalendarBlock).filter(
                CalendarBlock.google_event_id == body.google_event_id,
                CalendarBlock.tenant_id == tid).first():
            return {"ignored": "already recorded"}
        db.add(CalendarBlock(tenant_id=tid, consultant_id=body.consultant_id,
                            google_event_id=body.google_event_id,
                            starts_at=starts_at, ends_at=ends_at))
        db.commit()
        return {"blocked": True}
    if body.action == "moved":
        cons = db.query(Consultation).filter(
            Consultation.tenant_id == tid,
            Consultation.google_event_id == body.google_event_id).first()
        if cons and body.starts_at and body.ends_at:
            cons.starts_at, cons.ends_at, cons.status = (
                booking.parse_dt(body.starts_at), booking.parse_dt(body.ends_at), "rescheduled")
            messaging.audit(db, tid, None, "consultation_moved_from_google",
                            "consultation", cons.id, "")
            db.commit()
            return {"updated": "consultation"}
        block = db.query(CalendarBlock).filter(
            CalendarBlock.tenant_id == tid,
            CalendarBlock.google_event_id == body.google_event_id).first()
        if block and body.starts_at and body.ends_at:
            block.starts_at, block.ends_at = booking.parse_dt(body.starts_at), booking.parse_dt(body.ends_at)
            db.commit()
            return {"updated": "blocked slot"}
        raise HTTPException(404, "Google event not found")
    if body.action == "deleted":
        cons = db.query(Consultation).filter(
            Consultation.tenant_id == tid,
            Consultation.google_event_id == body.google_event_id).first()
        if cons:
            cons.status = "cancelled_externally"
            db.commit()
            # Notify client + assigned staff (never silently disappears).
            booking.notify_consultation(db, cons, "cancelled")
            consultant = db.query(User).filter(User.id == cons.consultant_id).first()
            if consultant and consultant.email:
                from .models import Tenant as _T
                firm = db.query(_T).filter(_T.id == tid).first()
                messaging.send_email(db, tid, firm.name if firm else "",
                                     consultant.email, "Consultation cancelled externally",
                                     f"A consultation on {cons.starts_at} was deleted on Google Calendar and marked cancelled externally.",
                                     case_id=cons.case_id, lead_id=cons.lead_id,
                                     source="system")
            messaging.audit(db, tid, None, "consultation_cancelled_externally",
                            "consultation", cons.id, "")
            db.commit()
            return {"cancelled_externally": True}
        block = db.query(CalendarBlock).filter(
            CalendarBlock.tenant_id == tid,
            CalendarBlock.google_event_id == body.google_event_id).first()
        if block:
            db.delete(block)
            db.commit()
            return {"unblocked": True}
        raise HTTPException(404, "Google event not found")
    raise HTTPException(400, f"Unknown action: {body.action}")


# ---------- Calendly webhook ----------
@router.post("/api/bookings/calendly")
async def calendly_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    payload = json.loads(raw or b"{}")
    signature = request.headers.get("X-Calendly-Signature")
    if not booking.verify_calendly_signature(raw, signature):
        raise HTTPException(401, "Invalid Calendly signature.")
    tenant = db.query(Tenant).filter(Tenant.slug == payload.get("firm_slug", "")).first()
    if not tenant:
        raise HTTPException(404, "Firm not found")
    et = db.query(EventType).filter(
        EventType.tenant_id == tenant.id,
        EventType.slug == payload.get("event_type_slug", "")).first()
    if not et:
        raise HTTPException(404, "Event type not found")
    email = payload.get("invitee_email", "")
    client = db.query(Client).filter(Client.tenant_id == tenant.id, Client.email == email).first()
    lead = None if client else db.query(Lead).filter(
        Lead.tenant_id == tenant.id, Lead.email == email).first()
    if not client and not lead:
        raise HTTPException(404, "No lead or client matches the invitee email — staff never retype; the booking needs a matching record.")
    # Book through the same validation as a CRM booking (hours + overlap).
    pseudo = type("U", (), {"tenant_id": tenant.id, "branch_id": (client or lead).branch_id, "id": None})()
    try:
        cons = booking.book_consultation(db, pseudo, {
            "consultant_id": et.consultant_id, "event_type_id": et.id,
            "starts_at": payload["starts_at"], "ends_at": payload["ends_at"],
            "lead_id": lead.id if lead else None,
            "client_id": client.id if client else None,
            "source": "calendly",
            "calendly_event_id": payload.get("calendly_event_id", ""),
            "payment_status": payload.get("payment_status", "pending"),
        })
    except ValueError as e:
        raise HTTPException(400, str(e))
    return cons_out(cons)


# ---------- deadlines ----------
class DeadlineIn(BaseModel):
    title: str
    due_date: str
    deadline_type: str = "general"
    remind_for: str = "both"


@router.get("/api/cases/{case_id}/deadlines")
def list_deadlines(case_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    _case_for(user, db, case_id)
    rows = db.query(Deadline).filter(
        Deadline.tenant_id == user.tenant_id, Deadline.case_id == case_id
    ).order_by(Deadline.due_date).all()
    return [{"id": d.id, "title": d.title, "due_date": str(d.due_date),
             "deadline_type": d.deadline_type, "remind_for": d.remind_for,
             "done": d.done} for d in rows]


@router.post("/api/cases/{case_id}/deadlines")
def create_deadline(case_id: int, body: DeadlineIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    case = _case_for(user, db, case_id)
    if body.remind_for not in ("staff", "client", "both"):
        raise HTTPException(400, "remind_for must be staff, client, or both")
    dl = Deadline(tenant_id=user.tenant_id, case_id=case.id, title=body.title,
                  deadline_type=body.deadline_type, remind_for=body.remind_for,
                  due_date=booking.parse_dt(body.due_date))
    db.add(dl)
    messaging.audit(db, user.tenant_id, user.id, "deadline_created",
                    "deadline", None, body.title)
    db.commit()
    db.refresh(dl)
    return {"id": dl.id, "title": dl.title, "due_date": str(dl.due_date)}


class DeadlinePatch(BaseModel):
    done: bool | None = None


@router.patch("/api/deadlines/{dl_id}")
def patch_deadline(dl_id: int, body: DeadlinePatch, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    dl = db.query(Deadline).filter(
        Deadline.id == dl_id, Deadline.tenant_id == user.tenant_id).first()
    if not dl:
        raise HTTPException(404, "Deadline not found")
    if body.done is not None:
        dl.done = body.done
    db.commit()
    return {"id": dl.id, "done": dl.done}


# ---------- jobs / action items / drafts / audit ----------
@router.post("/api/jobs/run-outbox")
def job_outbox(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    return messaging.run_outbox(db, user.tenant_id)


@router.post("/api/jobs/run-reminders")
def job_reminders(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    return booking.run_reminders(db, user.tenant_id)


@router.post("/api/jobs/run-sync")
def job_sync(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """Retries pending Google syncs. Still unconnected -> failed + a
    dashboard action item; connected -> synced (simulated delivery)."""
    synced, failed = 0, 0
    for cons in db.query(Consultation).filter(
            Consultation.tenant_id == user.tenant_id,
            Consultation.sync_status == "pending").all():
        status = booking.push_to_google(db, cons)
        if status == "synced":
            cons.sync_status = "synced"
            synced += 1
            for item in db.query(ActionItem).filter(
                    ActionItem.tenant_id == user.tenant_id, ActionItem.resolved == False,
                    ActionItem.detail.like(f"%consultation #{cons.id}%")).all():
                item.resolved = True
        else:
            cons.sync_status = "failed"
            cons.sync_error = "Google Calendar not connected for this consultant."
            failed += 1
            existing = db.query(ActionItem).filter(
                ActionItem.tenant_id == user.tenant_id, ActionItem.resolved == False,
                ActionItem.detail.like(f"%consultation #{cons.id}%")).first()
            if not existing:
                db.add(ActionItem(tenant_id=user.tenant_id, kind="failed_sync",
                                  title=f"Calendar sync failed for consultation #{cons.id}",
                                  detail=f"consultation #{cons.id} could not sync to Google Calendar — consultant calendar not connected."))
    db.commit()
    return {"synced": synced, "failed": failed}


@router.get("/api/action-items")
def list_action_items(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    rows = db.query(ActionItem).filter(
        ActionItem.tenant_id == user.tenant_id, ActionItem.resolved == False
    ).order_by(ActionItem.id.desc()).all()
    return [{"id": a.id, "kind": a.kind, "title": a.title, "detail": a.detail,
             "at": str(a.created_at)} for a in rows]


@router.post("/api/action-items/{item_id}/resolve")
def resolve_action_item(item_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    item = db.query(ActionItem).filter(
        ActionItem.id == item_id, ActionItem.tenant_id == user.tenant_id).first()
    if not item:
        raise HTTPException(404, "Action item not found")
    item.resolved = True
    db.commit()
    return {"resolved": item.id}


class DraftIn(BaseModel):
    kind: str  # document_request | deadline_summary
    channel: str  # sms | email


@router.get("/api/cases/{case_id}/drafts")
def list_drafts(case_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    _case_for(user, db, case_id)
    rows = db.query(AiDraft).filter(
        AiDraft.tenant_id == user.tenant_id, AiDraft.case_id == case_id
    ).order_by(AiDraft.id.desc()).all()
    return [{"id": d.id, "kind": d.kind, "channel": d.channel, "subject": d.subject,
             "body": d.body, "source": d.source, "status": d.status} for d in rows]


@router.post("/api/cases/{case_id}/drafts")
def create_draft(case_id: int, body: DraftIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    case = _case_for(user, db, case_id)
    if body.kind not in ("document_request", "deadline_summary"):
        raise HTTPException(400, "Unknown draft kind")
    if body.channel not in ("sms", "email"):
        raise HTTPException(400, "channel must be sms or email")
    try:
        draft = ai_drafts.create_draft(db, user.tenant_id, case, body.kind, body.channel, user_id=user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": draft.id, "kind": draft.kind, "channel": draft.channel,
            "subject": draft.subject, "body": draft.body, "source": draft.source,
            "status": draft.status}


@router.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    draft = db.query(AiDraft).filter(
        AiDraft.id == draft_id, AiDraft.tenant_id == user.tenant_id).first()
    if not draft:
        raise HTTPException(404, "Draft not found")
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    try:
        draft, msg = ai_drafts.approve_draft(db, user.tenant_id, draft, user,
                                             tenant.name if tenant else "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"draft_id": draft.id, "status": draft.status,
            "sent_message": msg_out(msg)}


@router.post("/api/drafts/{draft_id}/discard")
def discard_draft(draft_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    draft = db.query(AiDraft).filter(
        AiDraft.id == draft_id, AiDraft.tenant_id == user.tenant_id).first()
    if not draft:
        raise HTTPException(404, "Draft not found")
    if draft.status != "draft":
        raise HTTPException(400, f"Draft is {draft.status}.")
    draft.status = "discarded"
    messaging.audit(db, user.tenant_id, user.id, "draft_discarded",
                    "ai_draft", draft.id, "")
    db.commit()
    return {"draft_id": draft.id, "status": draft.status}


@router.get("/api/audit-log")
def list_audit(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    rows = db.query(AuditLog).filter(
        AuditLog.tenant_id == user.tenant_id
    ).order_by(AuditLog.id.desc()).limit(100).all()
    return [{"id": a.id, "user_id": a.user_id, "action": a.action,
             "entity": a.entity, "entity_id": a.entity_id, "detail": a.detail,
             "at": str(a.created_at)} for a in rows]
