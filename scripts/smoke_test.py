"""Phase 1 + Phase 2 + Phase 3 + Phase 4 + Phase 5 acceptance smoke test. Boots nothing
itself — run against a live backend (see README). Exits non-zero if
any check fails.
Usage: python scripts/smoke_test.py [BASE_URL]

Phase 2/3 checks run in log mode (the default): 'would send' records
are the proof, and no real message is delivered to any phone or inbox.
Failure-injection checks need ALLOW_TEST_HOOKS=true on the backend.
Phase 3 uploads are small text files (readable by the template AI
adapter); binary uploads produce no suggestions, by design.
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
passed, failed = [], []


def check(name, cond, extra=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" — {extra}" if extra and not cond else ""))


def call(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def next_weekday(hour, minute, min_days_ahead=3):
    """A weekday (Mon-Fri) UTC slot at hour:minute, at least min_days_ahead out."""
    d = datetime.utcnow() + timedelta(days=min_days_ahead)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


s, health = call("GET", "/api/health")
check("health 200 + phase 5", s == 200 and health.get("phase") == 5, str(health))

s, otp = call("POST", "/api/auth/request-otp", body={"email": "admin@demo.example"})
code = otp.get("dev_code")
check("OTP issued in dev mode", s == 200 and bool(code), str(otp))
s, auth = call("POST", "/api/auth/verify-otp", body={"email": "admin@demo.example", "code": code})
token = auth.get("token")
check("OTP verify returns JWT", s == 200 and bool(token), str(auth))
s, me = call("GET", "/api/me", token=token)
check("me returns admin + firm", s == 200 and me.get("role") == "firm_admin", str(me))
s, leads = call("GET", "/api/leads", token=token)
check("seed leads listed", s == 200 and len(leads) >= 4, f"count={len(leads) if isinstance(leads, list) else leads}")
s, new_lead = call("POST", "/api/leads", token=token, body={
    "full_name": "Smoke Test Person", "email": "smoke@example.com", "source": "Website",
    "stream_of_interest": "Express Entry", "stage": "New"})
lid = new_lead.get("id")
check("create lead", s == 200 and bool(lid), str(new_lead))
s, conv = call("POST", f"/api/leads/{lid}/convert", token=token)
check("convert lead -> client + case, no retyping", s == 200 and conv.get("client_id")
      and conv.get("case", {}).get("stream") == "Express Entry", str(conv))
cid = conv.get("client_id")
s, view = call("GET", f"/api/clients/{cid}", token=token)
check("client 360 shows case", s == 200 and len(view.get("cases", [])) == 1, str(view))
case_id = view["cases"][0]["id"]
s, blocked = call("PATCH", f"/api/cases/{case_id}", token=token, body={"stage": "Documents"})
check("P5 unsigned retainer blocks leaving the opening stage", s == 400, str(blocked))
s, ret = call("POST", f"/api/cases/{case_id}/retainers", token=token, body={})
check("P5 retainer generated (draft, standard template)", s == 200 and ret.get("status") == "draft"
      and "Smoke Test Person" in ret.get("body", ""), str(ret))
s, signed = call("POST", f"/api/retainers/{ret['id']}/sign", token=token, body={"signer_name": "Smoke Test Person"})
check("P5 retainer signed in-app (typed name + audit)", s == 200 and signed.get("status") == "signed"
      and signed.get("method") == "in-app-typed" and bool(signed.get("signed_at")), str(signed))
s, moved = call("PATCH", f"/api/cases/{case_id}", token=token, body={"stage": "Documents"})
check("case stage move appends timeline", s == 200 and len(moved.get("events", [])) >= 2, str(moved))
s, dash = call("GET", "/api/dashboard", token=token)
check("dashboard core cards live", s == 200 and dash.get("active_cases", 0) >= 2
      and dash.get("total_leads", 0) >= 5, str(dash))
s, tmpl = call("GET", "/api/templates", token=token)
check("6 stream templates", s == 200 and len(tmpl) == 6, f"count={len(tmpl) if isinstance(tmpl, list) else tmpl}")
s, settings = call("GET", "/api/settings", token=token)
check("settings: firm + branches + team", s == 200 and len(settings.get("branches", [])) == 2
      and len(settings.get("team", [])) >= 3, str(settings))
s, bad = call("GET", "/api/leads", token="bogus")
check("unauthenticated request rejected", s == 401, str(s))
s, bad_stage = call("POST", "/api/leads", token=token, body={"full_name": "X", "stage": "Bogus"})
check("invalid lead stage rejected", s == 400, str(s))

# ---------- Phase 2 ----------
s, settings = call("GET", "/api/settings", token=token)
team = {u["email"]: u["id"] for u in settings.get("team", [])}
consultant_id = team.get("consultant@demo.example")
admin_id = team.get("admin@demo.example")
check("team ids resolved", bool(consultant_id and admin_id), str(team))
s, clients = call("GET", "/api/clients", token=token)
seed_client = next((c for c in clients if c["email"] == "aisha@example.com"), None)
s, view = call("GET", f"/api/clients/{seed_client['id']}", token=token)
seed_case = next((c for c in view["cases"] if c["stream"] == "Express Entry"), None)
case_id, client_id = seed_case["id"], seed_client["id"]
s, all_leads = call("GET", "/api/leads", token=token)
david = next((x for x in all_leads if x["full_name"] == "David Okafor"), None)

def case_msgs():
    s, rows = call("GET", f"/api/cases/{case_id}/messages", token=token)
    return rows if isinstance(rows, list) else []

# F11/F12: log-mode defaults, templates, would-send, chronological log
s, comms = call("GET", "/api/settings/communications", token=token)
check("F11/F12 comms default to log mode", s == 200
      and comms["settings"]["sms_mode"] == "log" and comms["settings"]["email_mode"] == "log",
      str(comms.get("settings")))
check("F11/F12 16 default templates (8 keys x sms+email)", s == 200 and len(comms.get("templates", [])) == 16,
      f"count={len(comms.get('templates', []))}")
n0 = len(case_msgs())
s, sms = call("POST", f"/api/cases/{case_id}/messages", token=token,
              body={"channel": "sms", "template_key": "document_request"})
check("F11 log-mode SMS recorded as would send, personalised + opt-out wording",
      s == 200 and sms.get("status") == "would_send" and "Aisha Khan" in sms.get("body", "")
      and "Express Entry" in sms.get("body", "") and "STOP" in sms.get("body", ""), str(sms))
s, email = call("POST", f"/api/cases/{case_id}/messages", token=token,
                body={"channel": "email", "template_key": "status_update"})
check("F12 log-mode email recorded as would send", s == 200 and email.get("status") == "would_send", str(email))
msgs = case_msgs()
check("F12 one chronological case log (sms then email)", len(msgs) >= n0 + 2
      and msgs[-2]["channel"] == "sms" and msgs[-1]["channel"] == "email", str([m["channel"] for m in msgs[-3:]]))
# F12: unverified sender blocked before any attempt
n_before = len(case_msgs())
s, patched = call("PATCH", "/api/settings/communications", token=token, body={"email_mode": "live"})
s, blocked = call("POST", f"/api/cases/{case_id}/messages", token=token,
                  body={"channel": "email", "template_key": "status_update"})
check("F12 unverified live sender blocked with clear error, no message recorded",
      s == 400 and "not verified" in blocked.get("detail", "") and len(case_msgs()) == n_before, str(blocked))
call("PATCH", "/api/settings/communications", token=token, body={"email_mode": "log"})
# F11: opt-out honoured (isolated on David Okafor's number, not the seed client's)
s, opt = call("POST", "/api/settings/communications/opt-out", token=token, body={"phone": david["phone"]})
s, suppressed = call("POST", f"/api/leads/{david['id']}/messages", token=token,
                     body={"channel": "sms", "body": "Hello David"})
check("F11 opted-out number receives no further SMS (suppressed, recorded)",
      s == 200 and suppressed.get("status") == "suppressed_opt_out", str(suppressed))
# F11: failed send retries once, then dashboard action item
s, hook = call("POST", "/api/test-hooks/fail-message", token=token, body={"message_id": sms["id"]})
check("test hook marks message failed", s == 200 and hook.get("status") == "failed", str(hook))
call("POST", "/api/jobs/run-outbox", token=token, body={})
s, after_retry = call("GET", f"/api/cases/{case_id}/messages", token=token)
failed_msg = next((m for m in after_retry if m["id"] == sms["id"]), {})
check("F11 failed send retried once (outbox-retry marker, still failed)",
      failed_msg.get("status") == "failed" and "outbox-retry" in failed_msg.get("provider_status", ""), str(failed_msg))
call("POST", "/api/jobs/run-outbox", token=token, body={})
s, items = call("GET", "/api/action-items", token=token)
check("F11 failed send surfaces as dashboard action item, never silently dropped",
      any(a["kind"] == "failed_send" for a in items), str(items))
s, dash2 = call("GET", "/api/dashboard", token=token)
check("dashboard carries open action items", s == 200 and len(dash2.get("action_items", [])) >= 1, str(dash2.get("action_items")))

# F13: event type, Calendly booking (no retyping), paid hold, refusals
s, et = call("POST", "/api/event-types", token=token, body={
    "consultant_id": consultant_id, "name": "Consultation", "slot_minutes": 30,
    "buffer_minutes": 15, "working_hours": {"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00"},
    "paid": False})
check("F13 event type configured, booking link reflects it",
      s == 200 and et.get("slug") and et.get("booking_link") == f"/book/{et['slug']}", str(et))
slot = next_weekday(10, 0)
s, cal = call("POST", "/api/bookings/calendly", token=token, body={
    "firm_slug": "demo-firm", "invitee_email": "aisha@example.com",
    "event_type_slug": et["slug"], "starts_at": iso(slot), "ends_at": iso(slot + timedelta(minutes=30)),
    "calendly_event_id": "cal-1", "payment_status": "free"})
check("F13 Calendly booking creates consultation on matching client, no retyping",
      s == 200 and cal.get("source") == "calendly" and cal.get("status") == "booked"
      and cal.get("client_id") == client_id, str(cal))
s, paid_et = call("POST", "/api/event-types", token=token, body={
    "consultant_id": consultant_id, "name": "Paid Consultation", "slot_minutes": 30,
    "buffer_minutes": 0, "working_hours": {"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00"},
    "paid": True, "price_cents": 5000})
slot2 = next_weekday(11, 0)
s, paid_cal = call("POST", "/api/bookings/calendly", token=token, body={
    "firm_slug": "demo-firm", "invitee_email": "aisha@example.com",
    "event_type_slug": paid_et["slug"], "starts_at": iso(slot2), "ends_at": iso(slot2 + timedelta(minutes=30)),
    "calendly_event_id": "cal-2", "payment_status": "pending"})
check("F13 paid consultation NOT confirmed until payment taken",
      s == 200 and paid_cal.get("status") == "payment_pending", str(paid_cal))
s, paid_ok = call("POST", f"/api/consultations/{paid_cal['id']}/confirm-payment", token=token, body={})
check("F13 payment confirmation books the slot", s == 200 and paid_ok.get("status") == "booked", str(paid_ok))
sat = next_weekday(10, 0)
while sat.weekday() != 5:
    sat += timedelta(days=1)
s, refused = call("POST", "/api/bookings/calendly", token=token, body={
    "firm_slug": "demo-firm", "invitee_email": "aisha@example.com",
    "event_type_slug": et["slug"], "starts_at": iso(sat), "ends_at": iso(sat + timedelta(minutes=30)),
    "calendly_event_id": "cal-3", "payment_status": "free"})
check("F13 booking outside working hours refused", s == 400, str(refused))
s, overlap = call("POST", "/api/bookings/calendly", token=token, body={
    "firm_slug": "demo-firm", "invitee_email": "aisha@example.com",
    "event_type_slug": et["slug"], "starts_at": iso(slot), "ends_at": iso(slot + timedelta(minutes=30)),
    "calendly_event_id": "cal-4", "payment_status": "free"})
check("F13 overlapping booking refused", s == 400, str(overlap))

# F14: connect, Google block, Google delete -> cancelled externally
s, conn = call("POST", "/api/calendar/connect", token=token, body={"calendar_id": "primary"})
check("F14 staff calendar connection recorded", s == 200 and conn.get("connected") is True, str(conn))
block_slot = next_weekday(11, 0, min_days_ahead=4)
s, gw = call("POST", "/api/calendar/google-webhook", token=token, body={
    "firm_slug": "demo-firm", "consultant_id": admin_id, "google_event_id": "g-block-1",
    "action": "created", "starts_at": iso(block_slot), "ends_at": iso(block_slot + timedelta(minutes=30))})
check("F14 Google-side working-hours event blocks the slot", s == 200 and gw.get("blocked") is True, str(gw))
s, week = call("GET", f"/api/calendar/week?consultant_id={admin_id}&from_date={iso(block_slot - timedelta(days=1))}&to_date={iso(block_slot + timedelta(days=1))}", token=token)
check("F14 week view reflects the Google block, title carries no client detail",
      s == 200 and len(week.get("blocked_slots", [])) == 1
      and "Aisha" not in str(week["blocked_slots"]), str(week))
s, blocked_book = call("POST", "/api/consultations", token=token, body={
    "consultant_id": admin_id, "starts_at": iso(block_slot), "ends_at": iso(block_slot + timedelta(minutes=30))})
check("F14 blocked slot cannot be booked from the CRM", s == 400, str(blocked_book))
# CRM booking with a Google event id, then Google-side delete
del_slot = next_weekday(14, 0, min_days_ahead=5)
s, gcons = call("POST", "/api/consultations", token=token, body={
    "consultant_id": admin_id, "client_id": client_id, "case_id": case_id,
    "starts_at": iso(del_slot), "ends_at": iso(del_slot + timedelta(minutes=30)),
    "google_event_id": "g-crm-1"})
check("F14 CRM booking with Google event id records (sync simulated as connected)",
      s == 200 and gcons.get("sync_status") == "synced", str(gcons))
n_before_del = len(case_msgs())
s, gdel = call("POST", "/api/calendar/google-webhook", token=token, body={
    "firm_slug": "demo-firm", "consultant_id": admin_id, "google_event_id": "g-crm-1",
    "action": "deleted"})
s, gcons_after = call("GET", f"/api/consultations/{gcons['id']}", token=token)
check("F14 Google-side delete -> cancelled externally + client notified, not silent",
      s == 200 and gcons_after.get("status") == "cancelled_externally"
      and len(case_msgs()) > n_before_del, str(gcons_after))

# F15: CRM booking confirmation, reminder, reschedule, cancel, outage-proof booking
book_slot = next_weekday(14, 0, min_days_ahead=6)
n_before_book = len(case_msgs())
s, booked = call("POST", "/api/consultations", token=token, body={
    "consultant_id": consultant_id, "client_id": client_id, "case_id": case_id,
    "starts_at": iso(book_slot), "ends_at": iso(book_slot + timedelta(minutes=30))})
check("F15 CRM booking records + confirmation by SMS and email (log mode)",
      s == 200 and booked.get("status") == "booked" and len(case_msgs()) >= n_before_book + 2, str(booked))
rem_slot = next_weekday(10, 0, min_days_ahead=8)
# Wide window so the reminder fires whatever weekday the run lands on.
call("PATCH", "/api/settings/communications", token=token, body={"consultation_reminder_hours": [200]})
s, rem_cons = call("POST", "/api/consultations", token=token, body={
    "consultant_id": consultant_id, "client_id": client_id, "case_id": case_id,
    "starts_at": iso(rem_slot), "ends_at": iso(rem_slot + timedelta(minutes=30))})
n_before_rem = len(case_msgs())
s, rem = call("POST", "/api/jobs/run-reminders", token=token, body={})
after_rem = case_msgs()
check("F15 reminder arrives at configured interval, both channels, log mode",
      s == 200 and len(after_rem) >= n_before_rem + 2
      and any("reminder" in m["body"].lower() for m in after_rem[n_before_rem:]), str(rem))
s, rem2 = call("POST", "/api/jobs/run-reminders", token=token, body={})
check("F15 reminder is idempotent per window (no duplicate on second run)",
      len(case_msgs()) == len(after_rem), str(len(case_msgs())))
call("PATCH", "/api/settings/communications", token=token, body={"consultation_reminder_hours": [24, 1]})
new_slot = next_weekday(15, 0, min_days_ahead=6)
n_before_res = len(case_msgs())
s, resched = call("PATCH", f"/api/consultations/{booked['id']}", token=token,
                  body={"starts_at": iso(new_slot), "ends_at": iso(new_slot + timedelta(minutes=30))})
check("F15 reschedule updates + re-notifies by both channels",
      s == 200 and resched.get("status") == "rescheduled" and len(case_msgs()) >= n_before_res + 2, str(resched))
n_before_can = len(case_msgs())
s, cancelled = call("PATCH", f"/api/consultations/{booked['id']}", token=token, body={"status": "cancelled"})
check("F15 cancel re-notifies by both channels",
      s == 200 and cancelled.get("status") == "cancelled" and len(case_msgs()) >= n_before_can + 2, str(cancelled))
out_slot = next_weekday(16, 0, min_days_ahead=7)
s, outage_book = call("POST", "/api/consultations", token=token, body={
    "consultant_id": team.get("filing@demo.example"), "client_id": client_id, "case_id": case_id,
    "starts_at": iso(out_slot), "ends_at": iso(out_slot + timedelta(minutes=30))})
check("F15 booking still records when Google is unreachable (sync pending)",
      s == 200 and outage_book.get("sync_status") == "pending", str(outage_book))
s, sync = call("POST", "/api/jobs/run-sync", token=token, body={})
s, items2 = call("GET", "/api/action-items", token=token)
check("F15 sync failure surfaces on the dashboard as an action item",
      s == 200 and any(a["kind"] == "failed_sync" for a in items2), str(items2))

# F16: deadline reminders by SMS + email, failed -> action item
due = datetime.utcnow() + timedelta(days=7)
s, dl = call("POST", f"/api/cases/{case_id}/deadlines", token=token, body={
    "title": "Passport submission", "due_date": iso(due), "deadline_type": "document",
    "remind_for": "both"})
check("F16 deadline created", s == 200 and dl.get("id"), str(dl))
n_before_dl = len(case_msgs())
call("POST", "/api/jobs/run-reminders", token=token, body={})
dl_msgs = case_msgs()[n_before_dl:]
check("F16 deadline reminder delivered by SMS + email, logged against the case",
      len([m for m in dl_msgs if "Passport submission" in m["body"]]) >= 2
      and all(m["status"] == "would_send" for m in dl_msgs), str(dl_msgs))
s, fail_rem = call("POST", "/api/test-hooks/fail-reminder", token=token,
                   body={"deadline_id": dl["id"], "channel": "sms"})
call("POST", "/api/jobs/run-reminders", token=token, body={})
s, items3 = call("GET", "/api/action-items", token=token)
check("F16 failed reminder retried once first (no action item yet)",
      not any(a["kind"] == "failed_reminder" for a in items3), str(items3))
call("POST", "/api/jobs/run-reminders", token=token, body={})
s, items4 = call("GET", "/api/action-items", token=token)
check("F16 failed reminder surfaces as action item after its retry",
      any(a["kind"] == "failed_reminder" for a in items4), str(items4))

# F17: AI drafts, human gate
n_before_draft = len(case_msgs())
s, draft = call("POST", f"/api/cases/{case_id}/drafts", token=token,
                body={"kind": "document_request", "channel": "sms"})
check("F17 document-request draft pre-filled naming exactly the checklist items, nothing sent",
      s == 200 and all(item in draft.get("body", "") for item in
                       ["Passport", "IELTS result", "ECA report", "Police clearance", "Proof of funds"])
      and len(case_msgs()) == n_before_draft, str(draft))
s, draft2 = call("POST", f"/api/cases/{case_id}/drafts", token=token,
                 body={"kind": "deadline_summary", "channel": "email"})
check("F17 deadline-summary draft names the correct deadlines",
      s == 200 and "Passport submission" in draft2.get("body", ""), str(draft2))
s, approved = call("POST", f"/api/drafts/{draft['id']}/approve", token=token, body={})
check("F17 approved draft sends as a STAFF message (log mode: would send, draft id recorded)",
      s == 200 and approved.get("sent_message", {}).get("status") == "would_send"
      and approved.get("sent_message", {}).get("source") == "staff"
      and approved.get("sent_message", {}).get("draft_id") == draft["id"], str(approved))
s, again = call("POST", f"/api/drafts/{draft['id']}/approve", token=token, body={})
check("F17 draft cannot approve twice (never sends itself)", s == 400, str(again))
s, draft3 = call("POST", f"/api/cases/{case_id}/drafts", token=token,
                 body={"kind": "document_request", "channel": "email"})
s, discarded = call("POST", f"/api/drafts/{draft3['id']}/discard", token=token, body={})
check("F17 draft discard works", s == 200 and discarded.get("status") == "discarded", str(discarded))
s, audit = call("GET", "/api/audit-log", token=token)
check("audit trail records Phase 2 actions", s == 200 and any(
    a["action"] in ("message_sent", "draft_approved", "consultation_booked") for a in audit), str(len(audit)))

# ---------- Phase 3: documents + client portal ----------
import uuid as _uuid


def upload_file(path, token, filename, content, content_type="text/plain"):
    boundary = _uuid.uuid4().hex
    head = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n").encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + path, method="POST", data=head + content + tail,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                          "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"detail": raw.decode(errors="replace")}


def call_raw(method, path, token):
    req = urllib.request.Request(BASE + path, method=method,
                                 headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def patch_raw(path, token, body):
    # call() forces POST when a body is given, so PATCH needs raw urllib.
    req = urllib.request.Request(BASE + path, method="PATCH",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def checklist():
    s, rows = call("GET", f"/api/cases/{case_id}/checklist", token)
    return rows if isinstance(rows, list) else []


def item_named(name):
    return next((it for it in checklist() if it["document_name"] == name), None)


def suggestions_of(item):
    lv = (item or {}).get("latest_version") or {}
    return lv.get("suggestions", [])


# Checklist init from the stream template (seed case: Express Entry)
s, items = call("POST", f"/api/cases/{case_id}/checklist/init", token, body={})
check("P3 checklist init from stream template: 5 items, all Not Started",
      s == 200 and len(items) == 5
      and [i["document_name"] for i in items] == ["Passport", "IELTS result", "ECA report",
                                                  "Police clearance", "Proof of funds"]
      and all(i["status"] == "Not Started" for i in items), str(items))
s, items2 = call("POST", f"/api/cases/{case_id}/checklist/init", token, body={})
check("P3 checklist init is idempotent (no duplicates)",
      s == 200 and len(items2) == 5, str(len(items2) if isinstance(items2, list) else items2))
passport = item_named("Passport")
n_msgs = len(case_msgs())
s, req_item = call("POST", f"/api/checklist-items/{passport['id']}/request", token, body={})
check("P3 staff requests a document: Requested + log-mode notification recorded",
      s == 200 and req_item.get("status") == "Requested"
      and len(case_msgs()) > n_msgs, str(req_item))

# Portal sign-in (W10): OTP by email, firm-scoped
s, potp = call("POST", "/api/portal/request-otp",
               body={"identifier": "aisha@example.com", "firm_slug": "demo-firm"})
pcode = potp.get("dev_code")
check("P3 portal OTP issued in dev mode", s == 200 and bool(pcode), str(potp))
s, pauth = call("POST", "/api/portal/verify-otp",
                body={"identifier": "aisha@example.com", "firm_slug": "demo-firm", "code": pcode})
ptoken = pauth.get("token")
check("P3 portal OTP verify returns a portal JWT", s == 200 and bool(ptoken), str(pauth))
s, pme = call("GET", "/api/portal/me", token=ptoken)
check("P3 portal me shows only the client's own cases",
      s == 200 and pme.get("full_name") == "Aisha Khan"
      and any(c["id"] == case_id for c in pme.get("cases", [])), str(pme))
s, pcases = call("GET", "/api/portal/cases", token=ptoken)
pcase = next((c for c in pcases if c["id"] == case_id), None)
check("P3 portal home lists the case with checklist counts",
      s == 200 and pcase and pcase["checklist_counts"].get("Requested") == 1, str(pcase))
s, pdetail = call("GET", f"/api/portal/cases/{case_id}", token=ptoken)
check("P3 portal case detail shows the Requested item",
      s == 200 and any(i["document_name"] == "Passport" and i["status"] == "Requested"
                       for i in pdetail.get("checklist", [])), str(pdetail))

# Demo gate, step 1: client uploads in the portal (W11)
doc_v1 = b"Name: Aisha Khan\nUCI: 9999-8888\nExpiry: 2030-05-01\n"
s, v1 = upload_file(f"/api/portal/cases/{case_id}/checklist/{passport['id']}/upload",
                    ptoken, "passport.txt", doc_v1)
check("P3 client uploads in portal: version 1 created, item Uploaded",
      s == 200 and v1.get("version_no") == 1
      and item_named("Passport")["status"] == "Uploaded", str(v1))
sugs = suggestions_of(item_named("Passport"))
check("P3 upload produces AI proposals (expiry + UCI) that stay Pending",
      any(s["proposed_field"] == "expiry_date" and s["proposed_value"] == "2030-05-01"
          and s["status"] == "Pending" for s in sugs)
      and any(s["proposed_field"] == "uci" and s["proposed_value"] == "9999-8888"
              and s["status"] == "Pending" for s in sugs), str(sugs))
check("P3 proposals are NOT applied yet (item expiry null, case UCI unchanged)",
      item_named("Passport")["expiry_date"] is None
      and call("GET", f"/api/cases/{case_id}", token)[1].get("uci") == "1234-5678",
      str(item_named("Passport")))

# Demo gate, step 2: staff review queue -> reject with reason
s, queue = call("GET", "/api/review-queue", token)
check("P3 review queue holds the uploaded item (oldest first)",
      s == 200 and any(q["id"] == passport["id"] for q in queue), str(len(queue)))
s, reviewing = call("POST", f"/api/checklist-items/{passport['id']}/start-review", token, body={})
check("P3 staff starts review: Under Review", s == 200 and reviewing.get("status") == "Under Review",
      str(reviewing))
s, bad_reject = call("POST", f"/api/checklist-items/{passport['id']}/reject", token, body={"reason": "  "})
check("P3 reject without a reason is refused", s == 400, str(bad_reject))
s, rejected = call("POST", f"/api/checklist-items/{passport['id']}/reject", token,
                   body={"reason": "Blurry scan, please re-upload a clear copy"})
check("P3 staff rejects with reason: Rejected + reason stored",
      s == 200 and rejected.get("status") == "Rejected"
      and rejected.get("rejection_reason") == "Blurry scan, please re-upload a clear copy",
      str(rejected))
s, pdetail = call("GET", f"/api/portal/cases/{case_id}", token=ptoken)
p_passport = next((i for i in pdetail["checklist"] if i["document_name"] == "Passport"), None)
check("P3 client sees the rejection reason in the portal",
      p_passport and p_passport["status"] == "Rejected"
      and "Blurry scan" in p_passport["rejection_reason"], str(p_passport))

# Demo gate, step 3: client re-uploads, staff approves, queue empties
s, v2 = upload_file(f"/api/portal/cases/{case_id}/checklist/{passport['id']}/upload",
                    ptoken, "passport-clear.txt", doc_v1)
check("P3 client re-uploads: version 2, item back to Uploaded",
      s == 200 and v2.get("version_no") == 2
      and item_named("Passport")["status"] == "Uploaded", str(v2))
s, versions = call("GET", f"/api/checklist-items/{passport['id']}/versions", token)
check("P3 version history keeps both versions with their decisions",
      s == 200 and len(versions) == 2
      and versions[0]["review_decision"] == "rejected"
      and versions[1]["review_decision"] == "pending", str(versions))
s, approved = call("POST", f"/api/checklist-items/{passport['id']}/approve", token, body={})
check("P3 staff approves: Approved", s == 200 and approved.get("status") == "Approved", str(approved))
s, queue = call("GET", "/api/review-queue", token)
check("P3 review queue empties for the approved item",
      s == 200 and not any(q["id"] == passport["id"] for q in queue), str(len(queue)))
s, again = call("POST", f"/api/checklist-items/{passport['id']}/approve", token, body={})
check("P3 approving an Approved item is refused", s == 400, str(again))

# Demo gate, step 4: AI proposals apply ONLY on consultant approval
sugs = suggestions_of(item_named("Passport"))
exp_sug = next((s for s in sugs if s["proposed_field"] == "expiry_date"
                and s["status"] == "Pending"), None)
uci_sug = next((s for s in sugs if s["proposed_field"] == "uci"
                and s["status"] == "Pending"), None)
check("P3 pending proposals found on the approved version",
      bool(exp_sug and uci_sug), str(sugs))
s, dec = call("POST", f"/api/suggestions/{exp_sug['id']}/approve", token, body={})
check("P3 approving the expiry proposal writes it to the item",
      s == 200 and dec.get("status") == "Approved"
      and item_named("Passport")["expiry_date"] == "2030-05-01", str(dec))
s, dec2 = call("POST", f"/api/suggestions/{uci_sug['id']}/approve", token, body={})
check("P3 approving the UCI proposal writes it to the case",
      s == 200 and dec2.get("status") == "Approved"
      and call("GET", f"/api/cases/{case_id}", token)[1].get("uci") == "9999-8888", str(dec2))
s, dec3 = call("POST", f"/api/suggestions/{exp_sug['id']}/approve", token, body={})
check("P3 a decided suggestion cannot be decided twice", s == 400, str(dec3))

# Mismatch flag: document name differs from the file -> acknowledged, never written
ielts = item_named("IELTS result")
s, v3 = upload_file(f"/api/portal/cases/{case_id}/checklist/{ielts['id']}/upload",
                    ptoken, "ielts.txt", b"Name: Aisha Khanne\nScore: 8.0\n")
mm = next((s for s in suggestions_of(item_named("IELTS result"))
           if s["kind"] == "mismatch" and s["proposed_field"] == "name_mismatch"), None)
check("P3 name mismatch flagged as a Pending mismatch suggestion",
      s == 200 and bool(mm), str(suggestions_of(item_named("IELTS result"))))
s, dec4 = call("POST", f"/api/suggestions/{mm['id']}/reject", token, body={})
s, view = call("GET", f"/api/clients/{client_id}", token)
check("P3 dismissing a mismatch changes no client data",
      s == 200 and dec4.get("status") == "Rejected"
      and view.get("full_name") == "Aisha Khan", str(dec4))

# Staff upload path + downloads
police = item_named("Police clearance")
s, v4 = upload_file(f"/api/checklist-items/{police['id']}/upload",
                    token, "police.txt", b"Police clearance certificate\n")
check("P3 staff upload works (Uploaded, staff as uploader)",
      s == 200 and v4.get("uploaded_by_kind") == "staff"
      and item_named("Police clearance")["status"] == "Uploaded", str(v4))
s, headers, data = call_raw("GET", f"/api/documents/versions/{v4['id']}/download", token)
check("P3 staff download returns the uploaded bytes",
      s == 200 and data == b"Police clearance certificate\n", f"status={s} len={len(data)}")
s, headers, data = call_raw("GET", f"/api/portal/cases/{case_id}/documents/{v4['id']}/download", ptoken)
check("P3 portal download of own document works",
      s == 200 and data == b"Police clearance certificate\n", f"status={s} len={len(data)}")

# Expiry alerts + packet
eca = item_named("ECA report")
s, patched = patch_raw(f"/api/checklist-items/{eca['id']}", token, {"expiry_date": "2020-01-01"})
check("P3 staff sets an expiry date on an item",
      s == 200 and patched.get("expiry_date") == "2020-01-01", str(patched))
n_before = len(case_msgs())
s, job = call("POST", "/api/jobs/run-expiry-alerts", token, body={})
check("P3 expiry job flips past-expiry items to Expired + notifies",
      s == 200 and job.get("expired") == 1
      and item_named("ECA report")["status"] == "Expired", str(job))
soon = (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%d")
s, patched2 = patch_raw(f"/api/checklist-items/{police['id']}", token, {"expiry_date": soon})
s, job2 = call("POST", "/api/jobs/run-expiry-alerts", token, body={})
s, expiring = call("GET", "/api/documents/expiring", token)
n_after = len(case_msgs())
s, job3 = call("POST", "/api/jobs/run-expiry-alerts", token, body={})
check("P3 expiring-soon item alerts once (no duplicate on re-run)",
      s == 200 and job2.get("alerted") == 1
      and any(e["id"] == police["id"] for e in expiring)
      and len(case_msgs()) == n_after, str(job2))
import zipfile as _zf
import io as _io
s, headers, data = call_raw("GET", f"/api/cases/{case_id}/packet", token)
ok_zip = s == 200 and data[:2] == b"PK"
manifest = ""
if ok_zip:
    with _zf.ZipFile(_io.BytesIO(data)) as zf:
        manifest = zf.read("manifest.txt").decode(errors="replace")
check("P3 submission packet is a ZIP with a manifest naming the approved Passport",
      ok_zip and "INCLUDED: Passport" in manifest, manifest[:300])

# Token separation: portal tokens are not staff tokens and vice versa
s, q_bad = call("GET", "/api/review-queue", token=ptoken)
check("P3 portal token cannot call staff endpoints (401)", s == 401, str(s))
s, p_bad = call("GET", "/api/portal/cases", token=token)
check("P3 staff token cannot call portal endpoints (401)", s == 401, str(s))

# ---------- Phase 4: billing, deadline engine, reports, portal assistant ----------
# W9: invoice template + invoice from template, numbering, instalments
s, tmpl = call("POST", "/api/billing/templates", token, body={
    "name": "Express Entry retainer", "currency": "CAD",
    "line_items": [{"description": "Retainer", "amount_cents": 100000},
                   {"description": "Filing fee", "amount_cents": 50000}],
    "instalments": [{"offset_days": 0, "share": 0.5}, {"offset_days": 30, "share": 0.5}]})
check("P4 invoice template created", s == 200 and tmpl.get("id"), str(tmpl))
s, bad_tmpl = call("POST", "/api/billing/templates", token, body={
    "name": "Bad shares",
    "line_items": [{"description": "X", "amount_cents": 1000}],
    "instalments": [{"offset_days": 0, "share": 0.5}, {"offset_days": 30, "share": 0.4}]})
check("P4 template with shares != 1 rejected (400)", s == 400, str(bad_tmpl))
s, inv = call("POST", f"/api/cases/{case_id}/invoices", token, body={
    "template_id": tmpl["id"]})
inv_id = inv.get("id")
check("P4 invoice from template: number, total, 2 instalments, Draft",
      s == 200 and inv.get("number", "").startswith("INV-")
      and inv.get("total_cents") == 150000 and len(inv.get("instalments", [])) == 2
      and inv.get("status") == "Draft", str(inv))
s, inv_pay = call("POST", f"/api/invoices/{inv_id}/payments", token, body={
    "method": "e-transfer", "amount_cents": 1000, "proof": "too early"})
check("P4 payment on Draft invoice refused (400)", s == 400, str(inv_pay))
s, sent = call("POST", f"/api/invoices/{inv_id}/send", token, body={})
check("P4 invoice send: Draft -> Sent", s == 200 and sent.get("status") == "Sent", str(sent))
s, pay1 = call("POST", f"/api/invoices/{inv_id}/payments", token, body={
    "method": "e-transfer", "amount_cents": 75000, "proof": "ETR-001"})
check("P4 partial payment -> Partially Paid + receipt + first instalment paid",
      s == 200 and pay1.get("status") == "Partially Paid"
      and pay1.get("paid_cents") == 75000
      and pay1["payments"][0]["receipt_no"].startswith("RCP-")
      and pay1["instalments"][0]["status"] == "paid"
      and pay1["instalments"][1]["status"] == "pending", str(pay1))
s, over = call("POST", f"/api/invoices/{inv_id}/payments", token, body={
    "method": "cash", "amount_cents": 999999, "proof": "too much"})
check("P4 overpayment refused (400)", s == 400, str(over))

# W9 demo gate: issued, partially paid, reminded when overdue, reconciled
past = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
s, inv2 = call("POST", f"/api/cases/{case_id}/invoices", token, body={
    "template_id": tmpl["id"], "due_date": past})
inv2_id = inv2.get("id")
call("POST", f"/api/invoices/{inv2_id}/send", token, body={})
n_before_bill = len(case_msgs())
s, job = call("POST", "/api/jobs/run-billing", token, body={})
check("P4 billing job marks past-due invoice Overdue + reminds once",
      s == 200 and job.get("overdue") == 1 and job.get("reminded") == 1, str(job))
s, job2 = call("POST", "/api/jobs/run-billing", token, body={})
check("P4 billing job is idempotent within the day (no second reminder)",
      s == 200 and job2.get("reminded") == 0, str(job2))
s, inv2_now = call("GET", f"/api/invoices/{inv2_id}", token)
check("P4 overdue invoice reads back Overdue", s == 200 and inv2_now.get("status") == "Overdue", str(inv2_now))
s, pay2 = call("POST", f"/api/invoices/{inv_id}/payments", token, body={
    "method": "card", "amount_cents": 75000, "proof": "CARD-001"})
check("P4 final payment reconciles invoice to Paid, balance zero",
      s == 200 and pay2.get("status") == "Paid" and pay2.get("balance_cents") == 0
      and pay2["instalments"][1]["status"] == "paid", str(pay2))
s, pay3 = call("POST", f"/api/invoices/{inv2_id}/payments", token, body={
    "method": "cash", "amount_cents": 150000, "proof": "CASH-001"})
check("P4 overdue invoice paid in full by cash -> Paid",
      s == 200 and pay3.get("status") == "Paid", str(pay3))
s, view360 = call("GET", f"/api/clients/{client_id}", token)
check("P4 client 360 view lists invoices",
      s == 200 and any(i["number"] == inv["number"] for i in view360.get("invoices", [])),
      str(view360.get("invoices")))

# W12: platform subscription (firm-admin only, simple mechanics)
s, sub = call("GET", "/api/settings/subscription", token)
check("P4 subscription defaults exist (trialing/starter)", s == 200 and sub.get("status") == "trialing"
      and sub.get("plan") == "starter", str(sub))
# call() forces POST when a body is given, so PATCH needs patch_raw
s, sub2 = patch_raw("/api/settings/subscription", token, {"plan": "growth", "status": "active"})
check("P4 subscription plan/status updated by firm admin", s == 200 and sub2.get("plan") == "growth"
      and sub2.get("status") == "active", str(sub2))
s, cotp = call("POST", "/api/auth/request-otp", body={"email": "consultant@demo.example"})
s, cauth = call("POST", "/api/auth/verify-otp", body={"email": "consultant@demo.example", "code": cotp.get("dev_code")})
ctoken = cauth.get("token")
s, sub_bad = patch_raw("/api/settings/subscription", ctoken, {"plan": "scale"})
check("P4 non-admin cannot change subscription (403)", s == 403, str(sub_bad))

# Deadline engine: rule -> derive (idempotent) -> 30/14/7 alerts -> escalation
s, rule = call("POST", "/api/deadline-rules", token, body={
    "name": "Submission follow-up", "trigger": "case_created", "offset_days": 30,
    "deadline_type": "follow_up", "title": "Submission follow-up"})
check("P4 deadline rule created", s == 200 and rule.get("id"), str(rule))
s, der = call("POST", f"/api/cases/{case_id}/derive-deadlines", token, body={})
check("P4 derive creates one deadline from the rule", s == 200 and der.get("created") == 1, str(der))
s, der2 = call("POST", f"/api/cases/{case_id}/derive-deadlines", token, body={})
check("P4 derive is idempotent (no duplicate)", s == 200 and der2.get("created") == 0, str(der2))
due30 = datetime.utcnow() + timedelta(days=30)
s, dl30 = call("POST", f"/api/cases/{case_id}/deadlines", token, body={
    "title": "Thirty-day check", "due_date": iso(due30), "deadline_type": "general",
    "remind_for": "both"})
n_before_alert = len(case_msgs())
s, alerts = call("POST", "/api/jobs/run-deadline-alerts", token, body={})
check("P4 30-day alert fires once via log-mode messaging",
      s == 200 and alerts.get("alerted", 0) >= 1, str(alerts))
s, alerts2 = call("POST", "/api/jobs/run-deadline-alerts", token, body={})
check("P4 deadline alerts do not repeat on re-run",
      s == 200 and alerts2.get("alerted") == 0, str(alerts2))
due_past = datetime.utcnow() - timedelta(days=2)
s, dl_old = call("POST", f"/api/cases/{case_id}/deadlines", token, body={
    "title": "Overdue test deadline", "due_date": iso(due_past), "deadline_type": "general",
    "remind_for": "both"})
s, esc = call("POST", "/api/jobs/run-deadline-alerts", token, body={})
s, dash2 = call("GET", "/api/dashboard", token)
check("P4 overdue deadline escalates to a dashboard action item",
      s == 200 and esc.get("escalated", 0) >= 1
      and any(a["kind"] == "deadline_escalation" for a in dash2.get("action_items", [])),
      str(esc))
s, esc2 = call("POST", "/api/jobs/run-deadline-alerts", token, body={})
check("P4 escalation is deduped while unresolved", s == 200 and esc2.get("escalated") == 0, str(esc2))

# W2 complete: reports + spreadsheet export
s, rep = call("GET", "/api/reports/summary", token)
check("P4 reports summary has all four sections",
      s == 200 and "approval_rate_by_stream" in rep and "days_per_stage" in rep
      and "workload" in rep and "revenue_by_month" in rep, str(sorted(rep.keys()) if isinstance(rep, dict) else rep))
rev = next((r for r in rep.get("revenue_by_month", []) if r["payments"] > 0), None)
check("P4 revenue by month counts the recorded payments",
      rev is not None and rev["received_cents"] == 300000, str(rev))
s, headers, data = call_raw("GET", "/api/reports/export.xlsx", token)
import openpyxl as _oxl
import io as _io2
wb = None
if s == 200 and data[:2] == b"PK":
    wb = _oxl.load_workbook(_io2.BytesIO(data))
check("P4 spreadsheet export is a valid .xlsx with all six sheets",
      wb is not None and set(wb.sheetnames) == {"Summary", "Revenue by month", "Workload",
      "Stage durations", "Invoices", "Payments"},
      str(wb.sheetnames if wb else s))

# Portal assistant (6.2): own data cited, law/eligibility routed, others' cases refused
s, ask1 = call("POST", "/api/portal/assistant/ask", ptoken, body={
    "question": "What is happening with my application?", "case_id": case_id})
check("P4 assistant answers a status question from own case data, not routed",
      s == 200 and ask1.get("routed") is False and "Documents" in ask1.get("answer", ""),
      str(ask1))
s, ask2 = call("POST", "/api/portal/assistant/ask", ptoken, body={
    "question": "Am I eligible for Express Entry and what are my chances?"})
check("P4 assistant routes eligibility questions to the consultant",
      s == 200 and ask2.get("routed") is True and "consultant" in ask2.get("answer", "").lower(),
      str(ask2))
s, ask3 = call("POST", "/api/portal/assistant/ask", ptoken, body={
    "question": "What is happening?", "case_id": 999999})
check("P4 assistant refuses a case that is not the client's (404)", s == 404, str(ask3))
s, turns = call("GET", f"/api/cases/{case_id}/assistant-turns", token)
check("P4 staff can review assistant turns on the case",
      s == 200 and len(turns) >= 2 and any(t["routed"] for t in turns), str(turns))

# Portal invoices: own only
s, pinv = call("GET", "/api/portal/invoices", ptoken)
check("P4 portal lists the client's own invoices",
      s == 200 and any(i["number"] == inv["number"] for i in pinv), str(pinv))
s, lead2 = call("POST", "/api/leads", token, body={
    "full_name": "Other Person", "email": "other@example.com", "source": "Website",
    "stream_of_interest": "Study", "stage": "New"})
s, conv2 = call("POST", f"/api/leads/{lead2['id']}/convert", token)
other_case = conv2["case"]["id"]
s, inv_other = call("POST", f"/api/cases/{other_case}/invoices", token, body={
    "line_items": [{"description": "Fee", "amount_cents": 1000}]})
s, pinv_bad = call("GET", f"/api/portal/invoices/{inv_other['id']}", ptoken)
check("P4 portal cannot open another client's invoice (404)", s == 404, str(pinv_bad))

# ---------- Phase 5 ----------
# Fresh case for the Phase 5 checks (the ambient case_id is the seed
# case by now — Phase 2 rebound it — so do not reuse it here).
s, p5_lead = call("POST", "/api/leads", token=token, body={
    "full_name": "Phase Five Person", "email": "p5@example.com", "source": "Website",
    "stream_of_interest": "Express Entry", "stage": "New"})
s, p5_conv = call("POST", f"/api/leads/{p5_lead['id']}/convert", token=token)
p5_case = p5_conv["case"]["id"]
check("P5 fresh case for phase checks", s == 200 and bool(p5_case), str(p5_conv))
# Standard retainer first (no custom template exists yet), then sign it.
s, ret_std = call("POST", f"/api/cases/{p5_case}/retainers", token=token, body={})
check("P5 retainer generated (draft, standard template)", s == 200 and ret_std.get("status") == "draft"
      and "Phase Five Person" in ret_std.get("body", "")
      and "CUSTOM-MARKER" not in ret_std.get("body", ""), str(ret_std))
s, ret_signed = call("POST", f"/api/retainers/{ret_std['id']}/sign", token=token, body={"signer_name": "Phase Five Person"})
check("P5 retainer signed in-app (typed name + audit)", s == 200 and ret_signed.get("status") == "signed"
      and ret_signed.get("method") == "in-app-typed" and bool(ret_signed.get("signed_at")), str(ret_signed))
# Retainer templates: firm-admin custom template replaces the standard one.
s, tmpl5 = call("POST", "/api/retainer-templates", token=token, body={
    "name": "Smoke firm retainer", "body": "CUSTOM-MARKER retainer for {client_name} at {firm_name}."})
check("P5 firm retainer template created (firm admin)", s == 200 and tmpl5.get("id"), str(tmpl5))
s, ret2 = call("POST", f"/api/cases/{p5_case}/retainers", token=token, body={"template_id": tmpl5["id"]})
check("P5 retainer from firm template carries the custom body", s == 200 and "CUSTOM-MARKER" in ret2.get("body", ""), str(ret2))
s, again = call("POST", f"/api/retainers/{ret_std['id']}/sign", token=token, body={"signer_name": "Again"})
check("P5 signed retainer cannot be re-signed", s == 400, str(again))
s, audit = call("GET", "/api/audit-log", token=token)
check("P5 retainer signature is in the audit log", s == 200 and any(a.get("action") == "retainer_signed" for a in audit), str(audit)[:200])
s, rets = call("GET", f"/api/cases/{p5_case}/retainers", token=token)
check("P5 retainer list shows draft + signed", s == 200 and len(rets) >= 2
      and any(r.get("status") == "signed" for r in rets), str(rets))

# Gate proof on a fresh case (case_id already moved past its opening stage).
s, g_lead = call("POST", "/api/leads", token=token, body={
    "full_name": "Gate Person", "email": "gate@example.com", "source": "Website",
    "stream_of_interest": "Express Entry", "stage": "New"})
s, g_conv = call("POST", f"/api/leads/{g_lead['id']}/convert", token=token)
gate_case = g_conv["case"]["id"]
s, g_blocked = call("PATCH", f"/api/cases/{gate_case}", token=token, body={"stage": "Documents"})
check("P5 gate: fresh case cannot leave Consultation unsigned", s == 400, str(g_blocked))
s, g_ret = call("POST", f"/api/cases/{gate_case}/retainers", token=token, body={})
s, g_signed = call("POST", f"/api/retainers/{g_ret['id']}/sign", token=token, body={"signer_name": "Gate Person"})
s, g_moved = call("PATCH", f"/api/cases/{gate_case}", token=token, body={"stage": "Documents"})
check("P5 gate: signed retainer lets the case move", s == 200 and g_moved.get("stage") == "Documents", str(g_moved))

# IRCC forms: generate, correct (new version), render, all five codes.
s, form = call("POST", f"/api/cases/{p5_case}/ircc-forms", token=token, body={"form_code": "IMM 0008"})
check("P5 IMM 0008 generated from case data", s == 200 and form.get("version_no") == 1
      and form.get("data", {}).get("applicant_name") == "Phase Five Person", str(form))
s, bad_form = call("POST", f"/api/cases/{p5_case}/ircc-forms", token=token, body={"form_code": "IMM 9999"})
check("P5 unknown IRCC form code rejected", s == 400, str(bad_form))
s, corrected = call("PATCH", f"/api/ircc-forms/{form['id']}", token=token, body={"corrections": {"uci": "9999-8888"}, "note": "test correction"})
check("P5 consultant correction is a new version", s == 200 and corrected.get("version_no") == 2
      and corrected.get("status") == "corrected" and corrected.get("data", {}).get("uci") == "9999-8888", str(corrected))
s, forms = call("GET", f"/api/cases/{p5_case}/ircc-forms", token=token)
v1 = [f for f in forms if f["form_code"] == "IMM 0008" and f["version_no"] == 1]
check("P5 v1 unchanged after correction (versioned, never overwritten)", s == 200 and len(v1) == 1
      and v1[0]["data"].get("uci") != "9999-8888", str(v1))
s, detail = call("GET", f"/api/ircc-forms/{form['id']}", token=token)
check("P5 form rendering is plainly not an official IRCC PDF", s == 200
      and "NOT AN OFFICIAL IRCC PDF" in detail.get("rendering", "")
      and "IMM 0008" in detail.get("rendering", ""), str(detail)[:200])
for code in ["IMM 5669", "IMM 5257", "IMM 1294", "IMM 5476"]:
    s, f = call("POST", f"/api/cases/{p5_case}/ircc-forms", token=token, body={"form_code": code})
    check(f"P5 {code} generates", s == 200 and f.get("version_no") == 1, str(f))
s, bad_corr = call("PATCH", f"/api/ircc-forms/{form['id']}", token=token, body={"corrections": {"nope": "x"}})
check("P5 correction of an unknown field rejected", s == 400, str(bad_corr))

# Document chasing: log mode, idempotent, stops when the item arrives.
s, chase1 = call("POST", "/api/jobs/run-chasing", token=token, body={})
check("P5 chasing run chases missing items (log mode)", s == 200 and chase1.get("chased", 0) >= 1, str(chase1))
s, chase2 = call("POST", "/api/jobs/run-chasing", token=token, body={})
check("P5 chasing is idempotent within 7 days", s == 200 and chase2.get("chased") == 0
      and chase2.get("skipped_recent", 0) >= 1, str(chase2))
s, chases = call("GET", f"/api/cases/{case_id}/chases", token=token)
check("P5 chase log recorded per item/channel, log mode only", s == 200 and len(chases) >= 1
      and all(c.get("message_status") == "would_send" for c in chases), str(chases))
s, a_lead = call("POST", "/api/leads", token=token, body={
    "full_name": "Arrival Person", "email": "arrival@example.com", "phone": "+1 416 555 0199",
    "source": "Website", "stream_of_interest": "Express Entry", "stage": "New"})
s, a_conv = call("POST", f"/api/leads/{a_lead['id']}/convert", token=token)
arr_case = a_conv["case"]["id"]
s, arr_items = call("GET", f"/api/cases/{arr_case}/checklist", token=token)
first_item = arr_items[0]
s, up = upload_file(f"/api/checklist-items/{first_item['id']}/upload", token, "passport.txt", b"passport data")
check("P5 arrival upload moves the item to Uploaded", s == 200 and up.get("review_decision") == "pending", str(up))
s, chase3 = call("POST", "/api/jobs/run-chasing", token=token, body={})
s, arr_chases = call("GET", f"/api/cases/{arr_case}/chases", token=token)
chased_ids = {c["checklist_item_id"] for c in arr_chases}
check("P5 arrived item is not chased, missing siblings are", s == 200
      and first_item["id"] not in chased_ids and len(arr_chases) >= 1, str(arr_chases))

# Eligibility pre-check (6.4): public by firm_slug, staff by token, disclaimer always.
s, pc = call("POST", "/api/precheck", body={
    "firm_slug": "demo-firm",
    "answers": {"education": "bachelor", "language_clb": 8, "work_years": 4, "age_band": "under-30"},
    "full_name": "Precheck Prospect", "email": "precheck@example.com"})
check("P5 public pre-check ranks Express Entry first with disclaimer", s == 200
      and pc.get("ranked") and pc["ranked"][0]["stream"] == "Express Entry"
      and "not legal advice" in pc.get("disclaimer", "").lower()
      and "you are eligible" not in json.dumps(pc).lower(), str(pc))
pc_lead = pc.get("lead_id")
s, pc_rows = call("GET", f"/api/leads/{pc_lead}/prechecks", token=token)
check("P5 pre-check result arrives on the lead as a pre-check only", s == 200 and len(pc_rows) == 1
      and "not legal advice" in pc_rows[0].get("disclaimer", "").lower(), str(pc_rows))
s, pc_staff = call("POST", "/api/staff/precheck", token=token, body={
    "answers": {"family_in_canada": True}})
check("P5 staff pre-check surfaces Family Sponsorship", s == 200
      and any(r["stream"] == "Family Sponsorship" for r in pc_staff.get("ranked", [])), str(pc_staff))
s, pc_bad = call("POST", "/api/precheck", body={"firm_slug": "no-such-firm", "answers": {}})
check("P5 pre-check for an unknown firm is 404", s == 404, str(pc_bad))

print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED:", failed)
    sys.exit(1)
