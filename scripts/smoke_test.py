"""Phase 1 + Phase 2 acceptance smoke test. Boots nothing itself — run
against a live backend (see README). Exits non-zero if any check fails.
Usage: python scripts/smoke_test.py [BASE_URL]

Phase 2 checks run in log mode (the default): 'would send' records are
the proof, and no real message is delivered to any phone or inbox.
Failure-injection checks need ALLOW_TEST_HOOKS=true on the backend.
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
check("health 200 + phase 2", s == 200 and health.get("phase") == 2, str(health))

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

print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED:", failed)
    sys.exit(1)
