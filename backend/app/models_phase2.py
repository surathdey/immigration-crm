"""Phase 2 data model. Extends Phase 1 — no Phase 1 table is altered.

Tenant rule (same as Phase 1): every firm-owned row carries tenant_id and
every query filters on it at the data layer. Nothing here stores a real
provider credential: sender identities are names/addresses only, and the
Google connection records a connected flag plus a calendar id — never an
OAuth token (real OAuth token storage arrives with the registered Google
app; see README).
"""
import json
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, func
from sqlalchemy.orm import relationship
from .db import Base


def _json_default_list():
    return json.dumps([])


class FirmSettings(Base):
    """One row per tenant. Log mode is the default for both channels.

    Real sending for a channel is enabled only when BOTH gates pass:
    sender_verified AND test_received. The adapter enforces this; the UI
    cannot bypass it. Test/demo environments never send real messages:
    live mode additionally requires provider credentials in env, which
    this codebase never ships (see .env.example placeholders).
    """
    __tablename__ = "firm_settings"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, unique=True)
    sms_mode = Column(String, default="log")  # log | live
    sms_sender = Column(String, default="")
    sms_sender_verified = Column(Boolean, default=False)
    sms_test_received = Column(Boolean, default=False)
    email_mode = Column(String, default="log")  # log | live
    email_sender = Column(String, default="")
    email_sender_verified = Column(Boolean, default=False)
    email_test_received = Column(Boolean, default=False)
    opt_out_wording = Column(String, default="Reply STOP to opt out.")
    # JSON lists: days before a deadline / hours before a consultation.
    deadline_reminder_days = Column(Text, default='[7, 3, 1]')
    consultation_reminder_hours = Column(Text, default='[24, 1]')
    calendly_account = Column(String, default="")


class MessageTemplate(Base):
    """Firm-editable templates (List B item 6). Placeholders:
    {client_name}, {case_stream}, {case_id}, {firm_name}. SMS templates
    always carry the firm's opt-out wording, appended at send time."""
    __tablename__ = "message_templates"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    key = Column(String, nullable=False)  # welcome, document_request, ...
    channel = Column(String, nullable=False)  # sms | email
    subject = Column(String, default="")
    body = Column(Text, nullable=False)


TEMPLATE_KEYS = ["welcome", "document_request", "submission_confirmation",
                 "status_update", "biometrics_medical_request", "approval",
                 "refusal", "payment_reminder"]

DEFAULT_TEMPLATES = {
    ("welcome", "sms"): "Welcome to {firm_name}, {client_name}! Your {case_stream} case (#{case_id}) is open. We will keep you updated here.",
    ("welcome", "email"): "Welcome to {firm_name}",
    ("document_request", "sms"): "Hi {client_name}, for your {case_stream} case (#{case_id}) we still need documents from you. Please reply to this message or contact the firm.",
    ("document_request", "email"): "Documents needed for your {case_stream} case",
    ("submission_confirmation", "sms"): "Hi {client_name}, your {case_stream} case (#{case_id}) has been submitted.",
    ("submission_confirmation", "email"): "Your {case_stream} case has been submitted",
    ("status_update", "sms"): "Hi {client_name}, an update on your {case_stream} case (#{case_id}): see your email for details.",
    ("status_update", "email"): "Update on your case",
    ("biometrics_medical_request", "sms"): "Hi {client_name}, biometrics or a medical exam is now requested for your {case_stream} case (#{case_id}). Details by email.",
    ("biometrics_medical_request", "email"): "Biometrics / medical request",
    ("approval", "sms"): "Hi {client_name}, good news on your {case_stream} case (#{case_id})! Details by email.",
    ("approval", "email"): "Decision on your case",
    ("refusal", "sms"): "Hi {client_name}, there is a decision on your {case_stream} case (#{case_id}). Please contact the firm to discuss next steps.",
    ("refusal", "email"): "Decision on your case",
    ("payment_reminder", "sms"): "Hi {client_name}, a payment reminder for your {case_stream} case (#{case_id}). Please contact the firm.",
    ("payment_reminder", "email"): "Payment reminder",
}

DEFAULT_EMAIL_BODIES = {
    "welcome": "Welcome to {firm_name}, {client_name}! Your {case_stream} case (#{case_id}) is open. We will keep you updated.",
    "document_request": "Hi {client_name}, for your {case_stream} case (#{case_id}) we still need documents from you. Please contact the firm with them.",
    "submission_confirmation": "Hi {client_name}, your {case_stream} case (#{case_id}) has been submitted.",
    "status_update": "Hi {client_name}, an update on your {case_stream} case (#{case_id}).",
    "biometrics_medical_request": "Hi {client_name}, biometrics or a medical exam is now requested for your {case_stream} case (#{case_id}).",
    "approval": "Hi {client_name}, good news on your {case_stream} case (#{case_id})!",
    "refusal": "Hi {client_name}, there is a decision on your {case_stream} case (#{case_id}). Please contact the firm to discuss next steps.",
    "payment_reminder": "Hi {client_name}, a payment reminder for your {case_stream} case (#{case_id}). Please contact the firm.",
}


class SmsOptOut(Base):
    """A phone number that must receive no further SMS, honoured on the
    next send. Consent model (documented in README): a phone number on a
    lead/client record counts as recorded consent; this table is the
    revocation of that consent."""
    __tablename__ = "sms_opt_outs"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    phone = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class CaseMessage(Base):
    """One chronological log per case (email + SMS, both directions where
    supported). case_id is nullable so a lead-only booking confirmation
    can be logged against the lead instead. Status: would_send (log mode),
    queued, delivered, failed, suppressed_opt_out."""
    __tablename__ = "case_messages"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    channel = Column(String, nullable=False)  # sms | email
    direction = Column(String, default="out")
    sender = Column(String, default="")
    recipient = Column(String, default="")
    subject = Column(String, default="")
    body = Column(Text, nullable=False)
    template_key = Column(String, default="")
    status = Column(String, default="would_send")
    provider_status = Column(String, default="")
    source = Column(String, default="staff")  # staff | ai_draft | system
    draft_id = Column(Integer, ForeignKey("ai_drafts.id"), nullable=True)
    simulate_failure = Column(Boolean, default=False)  # test hook only, see test_hooks.py
    created_at = Column(DateTime, server_default=func.now())


class TestFailure(Base):
    """Test-only failure injection (written only by the test-hooks
    endpoints, which exist only when ALLOW_TEST_HOOKS=true). Keeps the
    production message model free of test columns."""
    __tablename__ = "test_failures"
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("case_messages.id"), nullable=False, unique=True)


class TestReminderFailure(Base):
    """Same pattern for reminder retries: a failed ReminderLog listed
    here keeps failing its retry, so the retry-then-action-item rule is
    verifiable without a real provider outage."""
    __tablename__ = "test_reminder_failures"
    id = Column(Integer, primary_key=True)
    reminder_log_id = Column(Integer, ForeignKey("reminder_logs.id"), nullable=False, unique=True)


class EventType(Base):
    """Per-consultant Calendly event type (Feature 13). working_hours JSON:
    {"days": [0..6] (Mon=0), "start": "09:00", "end": "17:00"}."""
    __tablename__ = "event_types"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    consultant_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, default="Consultation")
    slot_minutes = Column(Integer, default=30)
    buffer_minutes = Column(Integer, default=0)
    working_hours = Column(Text, default='{"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00"}')
    paid = Column(Boolean, default=False)
    price_cents = Column(Integer, default=0)
    slug = Column(String, default="")


class Consultation(Base):
    """Booking. Source: crm | calendly | google. Status: booked,
    payment_pending (paid slot, payment not yet taken — NOT confirmed),
    rescheduled, cancelled, cancelled_externally (Google-side delete),
    completed, no_show. sync_status tracks the Google sync state."""
    __tablename__ = "consultations"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    consultant_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_type_id = Column(Integer, ForeignKey("event_types.id"), nullable=True)
    kind = Column(String, default="Consultation")
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=False)
    status = Column(String, default="booked")
    source = Column(String, default="crm")
    google_event_id = Column(String, default="")
    calendly_event_id = Column(String, default="")
    payment_status = Column(String, default="free")  # free | pending | paid
    sync_status = Column(String, default="pending")  # pending | synced | failed
    sync_error = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())


class CalendarBlock(Base):
    """A Google-side event inside working hours that is NOT a CRM
    booking: it blocks the slot in the week view and in overlap checks.
    Title is generic on purpose — no client data ever lands here."""
    __tablename__ = "calendar_blocks"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    consultant_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    google_event_id = Column(String, default="")
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=False)
    title = Column(String, default="Busy (Google Calendar)")
    created_at = Column(DateTime, server_default=func.now())


class CalendarConnection(Base):
    """Per-staff Google Calendar connection (Feature 14). Records the
    connected flag and calendar id ONLY — no OAuth token is stored here
    (real OAuth token storage arrives with the registered Google app)."""
    __tablename__ = "calendar_connections"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    provider = Column(String, default="google")
    connected = Column(Boolean, default=False)
    calendar_id = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())


class Deadline(Base):
    """A case deadline (Feature 16). remind_for: staff | client | both."""
    __tablename__ = "deadlines"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    title = Column(String, nullable=False)
    deadline_type = Column(String, default="general")
    due_date = Column(DateTime, nullable=False)
    remind_for = Column(String, default="both")
    done = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class ReminderLog(Base):
    """Every reminder sent (or would-sent in log mode), per window, so a
    reminder is never sent twice for the same window. status: would_send,
    queued, delivered, failed. retry_count drives the retry-once rule."""
    __tablename__ = "reminder_logs"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    deadline_id = Column(Integer, ForeignKey("deadlines.id"), nullable=True)
    consultation_id = Column(Integer, ForeignKey("consultations.id"), nullable=True)
    channel = Column(String, nullable=False)  # sms | email
    window_key = Column(String, nullable=False)  # e.g. "deadline:7d" / "consult:24h"
    recipient = Column(String, default="")
    status = Column(String, default="would_send")
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class AiDraft(Base):
    """An AI-drafted staff message. NEVER sent by itself: only a staff
    approve action sends it (via the normal message path, logged as a
    staff message with this draft as its source). Status: draft,
    approved, discarded."""
    __tablename__ = "ai_drafts"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    kind = Column(String, nullable=False)  # document_request | deadline_summary
    channel = Column(String, nullable=False)  # sms | email
    subject = Column(String, default="")
    body = Column(Text, nullable=False)
    source = Column(String, default="ai_template_adapter")
    status = Column(String, default="draft")
    created_at = Column(DateTime, server_default=func.now())


class ActionItem(Base):
    """Dashboard action items: failed sends/reminders/syncs after their
    retry, never silently dropped."""
    __tablename__ = "action_items"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    kind = Column(String, nullable=False)  # failed_send | failed_reminder | failed_sync
    title = Column(String, nullable=False)
    detail = Column(String, default="")
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class AuditLog(Base):
    """Who did what, when — for Phase 2 actions: message sends, booking
    changes, draft approvals, settings changes."""
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    entity = Column(String, default="")
    entity_id = Column(Integer, nullable=True)
    detail = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())
