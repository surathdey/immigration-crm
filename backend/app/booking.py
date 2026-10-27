"""Consultations, Calendly, Google Calendar sync, deadlines, reminders.

Features 13–16. Honesty notes (also in README):
- Google sync is a faithful state machine, not a live Google API call:
  a staff connection is recorded (no OAuth token is stored — the real
  OAuth flow needs the registered Google app, List B item 4), and when
  connected, sync actions are marked synced (simulated delivery). When
  not connected, sync stays pending and a failed sync surfaces as a
  dashboard action item. No real Google API call is made or claimed.
- Calendly bookings arrive via the webhook endpoint below (with an
  HMAC check when CALENDLY_WEBHOOK_SECRET is set; without it the
  endpoint is demo-only and says so).
- The CRM is the source of truth for consultation bookings. A Google-side
  change to a CRM-created event updates the CRM record; a Google-side
  deletion marks it 'cancelled externally' and notifies client + staff.
- Privacy: calendar event titles/descriptions NEVER contain client
  case details — only the consultation type and the consultant.
"""
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, time as dtime

from .models_phase2 import (Consultation, CalendarBlock, CalendarConnection,
                            EventType, Deadline, ReminderLog, ActionItem,
                            TestReminderFailure)
from . import messaging

DEFAULT_HOURS = {"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00"}


def parse_dt(s):
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)


def _hhmm(s):
    h, m = s.split(":")
    return dtime(int(h), int(m))


def hours_for(db, tenant_id, consultant_id):
    et = db.query(EventType).filter(
        EventType.tenant_id == tenant_id,
        EventType.consultant_id == consultant_id).order_by(EventType.id).first()
    if et:
        try:
            return json.loads(et.working_hours), et.buffer_minutes
        except (ValueError, TypeError):
            pass
    return DEFAULT_HOURS, 0


def within_hours(hours, starts_at, ends_at):
    if starts_at.weekday() not in hours.get("days", []):
        return False
    if starts_at.date() != ends_at.date():
        return False
    start, end = _hhmm(hours["start"]), _hhmm(hours["end"])
    return starts_at.time() >= start and ends_at.time() <= end


def overlaps(db, tenant_id, consultant_id, starts_at, ends_at, buffer_minutes=0, exclude_id=None):
    """True if the window (widened by buffer) hits a live booking or a block."""
    lo = starts_at - timedelta(minutes=buffer_minutes)
    hi = ends_at + timedelta(minutes=buffer_minutes)
    q = db.query(Consultation).filter(
        Consultation.tenant_id == tenant_id,
        Consultation.consultant_id == consultant_id,
        Consultation.status.in_(["booked", "rescheduled"]))
    if exclude_id:
        q = q.filter(Consultation.id != exclude_id)
    for c in q.all():
        if c.starts_at < hi and lo < c.ends_at:
            return True
    for b in db.query(CalendarBlock).filter(
            CalendarBlock.tenant_id == tenant_id,
            CalendarBlock.consultant_id == consultant_id).all():
        if b.starts_at < hi and lo < b.ends_at:
            return True
    return False


def google_event_payload(consultation, consultant_name):
    """Privacy: type + consultant only. NEVER client name, stream, or case."""
    return {"title": consultation.kind or "Consultation",
            "description": f"Consultant: {consultant_name}. Booking via CRM."}


def push_to_google(db, consultation):
    """Returns the sync_status. Connected -> synced (simulated delivery);
    not connected -> pending (the job retries; failure surfaces later)."""
    conn = db.query(CalendarConnection).filter(
        CalendarConnection.tenant_id == consultation.tenant_id,
        CalendarConnection.user_id == consultation.consultant_id,
        CalendarConnection.connected == True).first()  # noqa: E712
    return "synced" if conn else "pending"


def _contact_for(db, consultation):
    """Returns (name, phone, email) from the client, else the lead."""
    from .models import Client, Lead
    if consultation.client_id:
        c = db.query(Client).filter(Client.id == consultation.client_id).first()
        if c:
            return c.full_name, c.phone, c.email
    if consultation.lead_id:
        lead = db.query(Lead).filter(Lead.id == consultation.lead_id).first()
        if lead:
            return lead.full_name, lead.phone, lead.email
    return "", "", ""


def _client_id_for(db, consultation):
    return consultation.client_id


def notify_consultation(db, consultation, kind, user_id=None):
    """kind: confirmation | rescheduled | cancelled | no_show_reschedule.
    Sends by SMS (if a phone is on record) and email (if an email is).
    In log mode these are 'would send' records, never deliveries."""
    from .models import Case
    name, phone, email = _contact_for(db, consultation)
    tenant_id = consultation.tenant_id
    firm = ""
    from .models import Tenant
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    firm = t.name if t else ""
    when = consultation.starts_at.strftime("%d %B %Y at %H:%M")
    texts = {
        "confirmation": (f"Hi {name}, your consultation is confirmed for {when}.",
                         "Consultation confirmed",
                         f"Hi {name}, your consultation is confirmed for {when}."),
        "rescheduled": (f"Hi {name}, your consultation has been rescheduled to {when}.",
                        "Consultation rescheduled",
                        f"Hi {name}, your consultation has been rescheduled to {when}."),
        "cancelled": (f"Hi {name}, your consultation on {when} has been cancelled. Please contact the firm to rebook.",
                      "Consultation cancelled",
                      f"Hi {name}, your consultation on {when} has been cancelled. Please contact the firm to rebook."),
        "no_show_reschedule": (f"Hi {name}, we missed you at your consultation. Please reply to reschedule.",
                               "Missed consultation — reschedule",
                               f"Hi {name}, we missed you at your consultation. Please reply to reschedule."),
    }
    sms_body, subject, email_body = texts[kind]
    if phone:
        messaging.send_sms(db, tenant_id, firm, phone, sms_body,
                           case_id=consultation.case_id, lead_id=consultation.lead_id,
                           template_key="status_update", source="system", user_id=user_id,
                           client_id=consultation.client_id)
    if email:
        messaging.send_email(db, tenant_id, firm, email, subject, email_body,
                             case_id=consultation.case_id, lead_id=consultation.lead_id,
                             template_key="status_update", source="system", user_id=user_id,
                             client_id=consultation.client_id)


def book_consultation(db, user, data):
    """Validates hours + overlap, then books. A paid event type without
    payment stays payment_pending — the slot is NOT confirmed."""
    from .models import User
    starts_at, ends_at = parse_dt(data["starts_at"]), parse_dt(data["ends_at"])
    if ends_at <= starts_at:
        raise ValueError("End time must be after start time.")
    consultant_id = data["consultant_id"]
    et = None
    if data.get("event_type_id"):
        et = db.query(EventType).filter(
            EventType.id == data["event_type_id"],
            EventType.tenant_id == user.tenant_id).first()
        if not et:
            raise ValueError("Unknown event type.")
    hours, buffer_minutes = hours_for(db, user.tenant_id, consultant_id)
    if et:
        try:
            hours = json.loads(et.working_hours)
        except (ValueError, TypeError):
            pass
        buffer_minutes = et.buffer_minutes
    if not within_hours(hours, starts_at, ends_at):
        raise ValueError("Booking outside working hours is refused.")
    if overlaps(db, user.tenant_id, consultant_id, starts_at, ends_at, buffer_minutes):
        raise ValueError("Slot overlaps an existing booking and is refused.")
    status, payment_status = "booked", "free"
    if et and et.paid:
        payment_status = data.get("payment_status", "pending")
        if payment_status != "paid":
            status, payment_status = "payment_pending", "pending"
    cons = Consultation(tenant_id=user.tenant_id, branch_id=user.branch_id,
                        lead_id=data.get("lead_id"), client_id=data.get("client_id"),
                        case_id=data.get("case_id"), consultant_id=consultant_id,
                        event_type_id=et.id if et else None,
                        kind=data.get("kind", "Consultation"),
                        starts_at=starts_at, ends_at=ends_at, status=status,
                        source=data.get("source", "crm"), payment_status=payment_status,
                        google_event_id=data.get("google_event_id", ""),
                        calendly_event_id=data.get("calendly_event_id", ""))
    db.add(cons)
    db.flush()
    cons.sync_status = push_to_google(db, cons)
    if status == "booked":
        notify_consultation(db, cons, "confirmation", user_id=user.id)
    messaging.audit(db, user.tenant_id, user.id, "consultation_booked",
                    "consultation", cons.id, f"{cons.kind} {starts_at} status={status}")
    db.commit()
    db.refresh(cons)
    return cons


def verify_calendly_signature(raw_body: bytes, signature: str | None):
    """HMAC check when CALENDLY_WEBHOOK_SECRET is set; otherwise the
    endpoint is demo-only (documented, not claimed as verified)."""
    secret = os.environ.get("CALENDLY_WEBHOOK_SECRET", "")
    if not secret:
        return True
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def run_reminders(db, tenant_id, now=None):
    """Background-job entry point (also POST /api/jobs/run-reminders).

    Consultation reminders at the firm's configured hour-windows before
    the meeting; deadline reminders at the configured day-windows before
    the due date. Idempotent per (record, channel, window). Failed
    reminders retry once, then become dashboard action items."""
    from .models import Client, Case, User, Tenant
    now = now or datetime.utcnow()
    sent, failed, actioned = 0, 0, 0
    settings = messaging.get_settings(db, tenant_id)
    try:
        hour_windows = json.loads(settings.consultation_reminder_hours)
    except (ValueError, TypeError):
        hour_windows = [24, 1]
    try:
        day_windows = json.loads(settings.deadline_reminder_days)
    except (ValueError, TypeError):
        day_windows = [7, 3, 1]
    firm = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    firm_name = firm.name if firm else ""

    # --- consultation reminders ---
    for cons in db.query(Consultation).filter(
            Consultation.tenant_id == tenant_id,
            Consultation.status.in_(["booked", "rescheduled"])).all():
        for hrs in hour_windows:
            window_start = cons.starts_at - timedelta(hours=hrs)
            if not (window_start <= now < cons.starts_at):
                continue
            for channel in ("sms", "email"):
                key = f"consult:{hrs}h"
                if db.query(ReminderLog).filter(
                        ReminderLog.consultation_id == cons.id,
                        ReminderLog.channel == channel,
                        ReminderLog.window_key == key).first():
                    continue
                name, phone, email = _contact_for(db, cons)
                recipient = phone if channel == "sms" else email
                if not recipient:
                    continue
                when = cons.starts_at.strftime("%d %B %Y at %H:%M")
                try:
                    if channel == "sms":
                        sent_msg = messaging.send_sms(db, tenant_id, firm_name, phone,
                                                      f"Hi {name}, a reminder: your consultation is on {when}.",
                                                      case_id=cons.case_id, lead_id=cons.lead_id,
                                                      template_key="status_update", source="system",
                                                      client_id=cons.client_id)
                    else:
                        sent_msg = messaging.send_email(db, tenant_id, firm_name, email,
                                                        "Consultation reminder",
                                                        f"Hi {name}, a reminder: your consultation is on {when}.",
                                                        case_id=cons.case_id, lead_id=cons.lead_id,
                                                        template_key="status_update", source="system",
                                                        client_id=cons.client_id)
                    db.add(ReminderLog(tenant_id=tenant_id, consultation_id=cons.id,
                                       channel=channel, window_key=key,
                                       recipient=recipient, status=sent_msg.status))
                    sent += 1
                except ValueError as e:
                    db.add(ReminderLog(tenant_id=tenant_id, consultation_id=cons.id,
                                       channel=channel, window_key=key,
                                       recipient=recipient, status="failed"))
                    failed += 1
    # --- deadline reminders ---
    for dl in db.query(Deadline).filter(
            Deadline.tenant_id == tenant_id, Deadline.done == False).all():  # noqa: E712
        case = db.query(Case).filter(Case.id == dl.case_id).first()
        client = db.query(Client).filter(Client.id == case.client_id).first() if case else None
        consultant = (db.query(User).filter(User.id == case.assigned_consultant_id).first()
                      if case and case.assigned_consultant_id else None)
        for days in day_windows:
            if now.date() != (dl.due_date - timedelta(days=days)).date():
                continue
            targets = []
            if dl.remind_for in ("client", "both") and client:
                if client.phone:
                    targets.append(("sms", client.phone))
                if client.email:
                    targets.append(("email", client.email))
            if dl.remind_for in ("staff", "both") and consultant and consultant.email:
                targets.append(("email", consultant.email))
            for channel, recipient in targets:
                key = f"deadline:{days}d"
                if db.query(ReminderLog).filter(
                        ReminderLog.deadline_id == dl.id, ReminderLog.channel == channel,
                        ReminderLog.window_key == key).first():
                    continue
                try:
                    if channel == "sms":
                        sent_msg = messaging.send_sms(db, tenant_id, firm_name, recipient,
                                                      f"Hi {client.full_name}, a reminder: '{dl.title}' for your {case.stream if case else ''} case is due on {dl.due_date.strftime('%d %B %Y')}.",
                                                      case_id=dl.case_id, template_key="status_update",
                                                      source="system",
                                                      client_id=client.id if client else None)
                    else:
                        sent_msg = messaging.send_email(db, tenant_id, firm_name, recipient,
                                                        f"Reminder: {dl.title}",
                                                        f"Reminder: '{dl.title}' is due on {dl.due_date.strftime('%d %B %Y')}.",
                                                        case_id=dl.case_id, template_key="status_update",
                                                        source="system",
                                                        client_id=client.id if client else None)
                    db.add(ReminderLog(tenant_id=tenant_id, deadline_id=dl.id,
                                       channel=channel, window_key=key,
                                       recipient=recipient, status=sent_msg.status))
                    sent += 1
                except ValueError:
                    db.add(ReminderLog(tenant_id=tenant_id, deadline_id=dl.id,
                                       channel=channel, window_key=key,
                                       recipient=recipient, status="failed"))
                    failed += 1
    db.commit()

    # --- failed-reminder retry-once, then action item ---
    for log in db.query(ReminderLog).filter(
            ReminderLog.tenant_id == tenant_id, ReminderLog.status == "failed").all():
        if db.query(TestReminderFailure).filter(
                TestReminderFailure.reminder_log_id == log.id).first():
            # Deterministic test path: the retry keeps failing.
            if log.retry_count >= 1:
                existing = db.query(ActionItem).filter(
                    ActionItem.tenant_id == tenant_id, ActionItem.resolved == False,
                    ActionItem.detail.like(f"%reminder #{log.id}%")).first()
                if not existing:
                    db.add(ActionItem(tenant_id=tenant_id, kind="failed_reminder",
                                      title=f"Reminder #{log.id} failed after retry",
                                      detail=f"reminder #{log.id} ({log.channel} to {log.recipient}) failed after one retry — staff action needed."))
                    actioned += 1
            else:
                log.retry_count += 1
            continue
        ok = _resend_reminder(db, tenant_id, log, firm_name)
        if ok:
            log.status = "would_send" if messaging.get_settings(db, tenant_id).sms_mode == "log" else "queued"
        else:
            log.retry_count += 1
            if log.retry_count >= 1:
                existing = db.query(ActionItem).filter(
                    ActionItem.tenant_id == tenant_id, ActionItem.resolved == False,
                    ActionItem.detail.like(f"%reminder #{log.id}%")).first()
                if not existing:
                    db.add(ActionItem(tenant_id=tenant_id, kind="failed_reminder",
                                      title=f"Reminder #{log.id} failed after retry",
                                      detail=f"reminder #{log.id} ({log.channel} to {log.recipient}) failed after one retry — staff action needed."))
                    actioned += 1
    db.commit()
    return {"reminders_sent": sent, "reminders_failed": failed,
            "reminder_action_items": actioned}


def _resend_reminder(db, tenant_id, log, firm_name):
    """Rebuilds a failed reminder from its record and re-sends it through
    the normal message path. Returns True on success."""
    from .models import Client, Case
    try:
        if log.consultation_id:
            cons = db.query(Consultation).filter(Consultation.id == log.consultation_id).first()
            if not cons:
                return False
            name, phone, email = _contact_for(db, cons)
            when = cons.starts_at.strftime("%d %B %Y at %H:%M")
            if log.channel == "sms":
                messaging.send_sms(db, tenant_id, firm_name, phone,
                                   f"Hi {name}, a reminder: your consultation is on {when}.",
                                   case_id=cons.case_id, lead_id=cons.lead_id,
                                   template_key="status_update", source="system",
                                   client_id=cons.client_id)
            else:
                messaging.send_email(db, tenant_id, firm_name, email,
                                     "Consultation reminder",
                                     f"Hi {name}, a reminder: your consultation is on {when}.",
                                     case_id=cons.case_id, lead_id=cons.lead_id,
                                     template_key="status_update", source="system",
                                     client_id=cons.client_id)
            return True
        if log.deadline_id:
            dl = db.query(Deadline).filter(Deadline.id == log.deadline_id).first()
            if not dl:
                return False
            case = db.query(Case).filter(Case.id == dl.case_id).first()
            client = db.query(Client).filter(Client.id == case.client_id).first() if case else None
            if log.channel == "sms":
                messaging.send_sms(db, tenant_id, firm_name, log.recipient,
                                   f"Hi {client.full_name if client else ''}, a reminder: '{dl.title}' is due on {dl.due_date.strftime('%d %B %Y')}.",
                                   case_id=dl.case_id, template_key="status_update",
                                   source="system",
                                   client_id=client.id if client else None)
            else:
                messaging.send_email(db, tenant_id, firm_name, log.recipient,
                                     f"Reminder: {dl.title}",
                                     f"Reminder: '{dl.title}' is due on {dl.due_date.strftime('%d %B %Y')}.",
                                     case_id=dl.case_id, template_key="status_update",
                                     source="system",
                                     client_id=client.id if client else None)
            return True
    except ValueError:
        return False
    return False
