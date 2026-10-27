"""SMS (Twilio) + email (SendGrid) adapters — Features 11 and 12.

Safety contract (enforced here, not in the UI):
- Log mode is the default for every firm: messages are composed, recorded
  against the case, and marked 'would send'. Nothing is delivered.
- Live mode requires BOTH gates: sender verified AND a test message
  received (FirmSettings flags, set explicitly in settings). Without
  them the adapter refuses with a clear error before any send attempt.
- Live mode additionally requires provider credentials in env. This
  codebase ships none (see .env.example placeholders); without them
  the adapter refuses rather than pretending.
- An unverified sender address is blocked by the adapter, never
  discovered later as a bounce.
- SMS is sent only to numbers with recorded consent: a phone number on
  a lead/client record counts as consent; SmsOptOut revokes it and is
  honoured automatically on the next send (recorded as
  'suppressed_opt_out', never silently dropped).
- Every send — including log-mode would-sends — is recorded against
  its case (or lead) in one chronological log.
- A failed send retries once via run_outbox(), then surfaces on the
  dashboard as an action item, never silently dropped.
"""
import base64
import json
import os
import urllib.request
import urllib.parse
import urllib.error

from .models_phase2 import (FirmSettings, MessageTemplate, SmsOptOut,
                            CaseMessage, ActionItem, AuditLog,
                            TEMPLATE_KEYS, DEFAULT_TEMPLATES, DEFAULT_EMAIL_BODIES)

ALLOW_TEST_HOOKS = os.environ.get("ALLOW_TEST_HOOKS", "false").lower() == "true"


def audit(db, tenant_id, user_id, action, entity="", entity_id=None, detail=""):
    db.add(AuditLog(tenant_id=tenant_id, user_id=user_id, action=action,
                    entity=entity, entity_id=entity_id, detail=detail or ""))


def get_settings(db, tenant_id) -> FirmSettings:
    row = db.query(FirmSettings).filter(FirmSettings.tenant_id == tenant_id).first()
    if not row:
        row = FirmSettings(tenant_id=tenant_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def ensure_templates(db, tenant_id):
    existing = {(t.key, t.channel) for t in
                db.query(MessageTemplate).filter(MessageTemplate.tenant_id == tenant_id).all()}
    changed = False
    for key in TEMPLATE_KEYS:
        for channel in ("sms", "email"):
            if (key, channel) in existing:
                continue
            body = DEFAULT_TEMPLATES[(key, channel)] if channel == "sms" else DEFAULT_EMAIL_BODIES[key]
            subject = DEFAULT_TEMPLATES[(key, channel)] if channel == "email" else ""
            db.add(MessageTemplate(tenant_id=tenant_id, key=key, channel=channel,
                                   subject=subject, body=body))
            changed = True
    if changed:
        db.commit()


def render(text, client_name="", case_stream="", case_id="", firm_name=""):
    return (text.replace("{client_name}", client_name or "")
                .replace("{case_stream}", case_stream or "")
                .replace("{case_id}", str(case_id or ""))
                .replace("{firm_name}", firm_name or ""))


def is_opted_out(db, tenant_id, phone):
    if not phone:
        return False
    return db.query(SmsOptOut).filter(
        SmsOptOut.tenant_id == tenant_id, SmsOptOut.phone == phone).first() is not None


def _twilio_send(sender, to_phone, body):
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        raise ValueError("Twilio provider not configured: set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.")
    data = urllib.parse.urlencode({"From": sender, "To": to_phone, "Body": body}).encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=data, method="POST",
        headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode()})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read() or b"{}")
            return payload.get("status", "queued")
    except urllib.error.HTTPError as e:
        raise ValueError(f"Twilio rejected the send (HTTP {e.code}).")


def _sendgrid_send(sender, to_email, subject, body):
    key = os.environ.get("SENDGRID_API_KEY", "")
    if not key:
        raise ValueError("SendGrid provider not configured: set SENDGRID_API_KEY.")
    payload = {"personalizations": [{"to": [{"email": to_email}]}],
               "from": {"email": sender}, "subject": subject or "(no subject)",
               "content": [{"type": "text/plain", "value": body}]}
    req = urllib.request.Request("https://api.sendgrid.com/v3/mail/send",
                                 data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return "queued" if r.status in (200, 202) else f"http_{r.status}"
    except urllib.error.HTTPError as e:
        raise ValueError(f"SendGrid rejected the send (HTTP {e.code}).")


def _record(db, tenant_id, case_id, lead_id, channel, sender, recipient,
            subject, body, template_key, status, provider_status, source, draft_id,
            client_id=None):
    msg = CaseMessage(tenant_id=tenant_id, case_id=case_id, lead_id=lead_id,
                      client_id=client_id, channel=channel, sender=sender, recipient=recipient,
                      subject=subject, body=body, template_key=template_key,
                      status=status, provider_status=provider_status,
                      source=source, draft_id=draft_id)
    db.add(msg)
    db.flush()
    return msg


def send_sms(db, tenant_id, firm_name, to_phone, body, case_id=None, lead_id=None,
             template_key="", source="staff", draft_id=None, user_id=None, client_id=None):
    """Returns the recorded CaseMessage. Raises ValueError on gate failure."""
    settings = get_settings(db, tenant_id)
    if is_opted_out(db, tenant_id, to_phone):
        msg = _record(db, tenant_id, case_id, lead_id, "sms", settings.sms_sender,
                      to_phone, "", body, template_key, "suppressed_opt_out",
                      "recipient opted out — no SMS sent", source, draft_id,
                      client_id=client_id)
        db.commit()
        return msg
    if not to_phone:
        raise ValueError("No phone number on record for this recipient.")
    full_body = body if settings.opt_out_wording in body else f"{body} {settings.opt_out_wording}"
    sender = settings.sms_sender or ""
    if settings.sms_mode == "log":
        msg = _record(db, tenant_id, case_id, lead_id, "sms", sender, to_phone,
                      "", full_body, template_key, "would_send",
                      "log mode — not delivered", source, draft_id,
                      client_id=client_id)
    else:
        if not settings.sms_sender_verified:
            raise ValueError("SMS sender not verified for this firm — verify the sender in settings before enabling real sending.")
        if not settings.sms_test_received:
            raise ValueError("No test SMS received for this firm yet — receive a test message before enabling real sending.")
        if not sender:
            raise ValueError("No SMS sender configured for this firm.")
        try:
            status = _twilio_send(sender, to_phone, full_body)
            msg = _record(db, tenant_id, case_id, lead_id, "sms", sender, to_phone,
                          "", full_body, template_key, "queued", status, source, draft_id,
                          client_id=client_id)
        except ValueError as e:
            msg = _record(db, tenant_id, case_id, lead_id, "sms", sender, to_phone,
                          "", full_body, template_key, "failed", str(e), source, draft_id,
                          client_id=client_id)
    audit(db, tenant_id, user_id, "message_sent", "case_message", msg.id,
          f"sms {msg.status} to {to_phone} (template {template_key or '-'})")
    db.commit()
    db.refresh(msg)
    return msg


def send_email(db, tenant_id, firm_name, to_email, subject, body, case_id=None,
               lead_id=None, template_key="", source="staff", draft_id=None, user_id=None,
               client_id=None):
    """Returns the recorded CaseMessage. Raises ValueError on gate failure."""
    settings = get_settings(db, tenant_id)
    if not to_email:
        raise ValueError("No email address on record for this recipient.")
    sender = settings.email_sender or ""
    if settings.email_mode == "log":
        msg = _record(db, tenant_id, case_id, lead_id, "email", sender, to_email,
                      subject, body, template_key, "would_send",
                      "log mode — not delivered", source, draft_id,
                      client_id=client_id)
    else:
        if not settings.email_sender_verified:
            raise ValueError("Email sender not verified for this firm — verify the sender domain/address in settings before enabling real sending.")
        if not settings.email_test_received:
            raise ValueError("No test email received for this firm yet — receive a test message before enabling real sending.")
        if not sender:
            raise ValueError("No email sender configured for this firm.")
        try:
            status = _sendgrid_send(sender, to_email, subject, body)
            msg = _record(db, tenant_id, case_id, lead_id, "email", sender, to_email,
                          subject, body, template_key, "queued", status, source, draft_id,
                          client_id=client_id)
        except ValueError as e:
            msg = _record(db, tenant_id, case_id, lead_id, "email", sender, to_email,
                          subject, body, template_key, "failed", str(e), source, draft_id,
                          client_id=client_id)
    audit(db, tenant_id, user_id, "message_sent", "case_message", msg.id,
          f"email {msg.status} to {to_email} (template {template_key or '-'})")
    db.commit()
    db.refresh(msg)
    return msg


def _retry_message(db, msg):
    """One retry of a failed message. Returns True if it is no longer failed."""
    from .models_phase2 import TestFailure
    if msg.channel == "sms":
        if (db.query(TestFailure).filter(TestFailure.message_id == msg.id).first()
                or msg.simulate_failure):
            return False
        # Log-mode retry: a would-be send is the success state in log mode.
        settings = get_settings(db, msg.tenant_id)
        if settings.sms_mode == "log":
            msg.status = "would_send"
            msg.provider_status = "log mode — retried, not delivered"
            return True
        try:
            _twilio_send(msg.sender, msg.recipient, msg.body)
            msg.status = "queued"
            return True
        except ValueError as e:
            msg.provider_status = str(e)
            return False
    if (db.query(TestFailure).filter(TestFailure.message_id == msg.id).first()
            or msg.simulate_failure):
        return False
    settings = get_settings(db, msg.tenant_id)
    if settings.email_mode == "log":
        msg.status = "would_send"
        msg.provider_status = "log mode — retried, not delivered"
        return True
    try:
        _sendgrid_send(msg.sender, msg.recipient, msg.subject, msg.body)
        msg.status = "queued"
        return True
    except ValueError as e:
        msg.provider_status = str(e)
        return False


def run_outbox(db, tenant_id):
    """Background-job entry point (also exposed as POST /api/jobs/run-outbox
    for demo/operator use; production would run it on a schedule).

    Failed messages get exactly one retry. A message that is still failed
    after its retry becomes an open dashboard action item.
    """
    retried, actioned = 0, 0
    failed = db.query(CaseMessage).filter(
        CaseMessage.tenant_id == tenant_id, CaseMessage.status == "failed").all()
    for msg in failed:
        # Exactly one retry: the first outbox run appends the
        # "outbox-retry" marker to provider_status; a later run sees the
        # marker and creates an action item instead of retrying again.
        if "outbox-retry" in (msg.provider_status or ""):
            existing = db.query(ActionItem).filter(
                ActionItem.tenant_id == tenant_id, ActionItem.resolved == False,
                ActionItem.detail.like(f"%message #{msg.id}%")).first()
            if not existing:
                db.add(ActionItem(tenant_id=tenant_id, kind="failed_send",
                                  title=f"Message #{msg.id} failed after retry",
                                  detail=f"message #{msg.id} ({msg.channel} to {msg.recipient}) failed after one retry — staff action needed."))
                actioned += 1
            continue
        ok = _retry_message(db, msg)
        if not ok:
            msg.provider_status = (msg.provider_status or "") + " | outbox-retry"
            retried += 1
    db.commit()
    return {"retried": retried, "action_items_created": actioned}
