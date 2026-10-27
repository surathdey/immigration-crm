# Immigration Consultant CRM — Phase 1 + Phase 2

Staff CRM for immigration consultants: leads, clients, cases, dashboard,
stream templates, firm/team settings (Phase 1), plus communications and
calendar (Phase 2): SMS via Twilio and email via SendGrid in log mode by
default, Calendly booking links, Google Calendar two-way sync,
consultation booking/reminders/reschedule/cancel, deadline reminders,
and AI-drafted staff messages behind a human gate. No client portal
(Phase 3), no billing (Phase 4).

Stack: FastAPI + React (Vite) + PostgreSQL + Docker. Tenancy is one
codebase with tenant-scoped rows (the design doc default;
database-per-tenant was flagged undecided and is NOT built here).

## Run (Docker — one command)

```sh
cp .env.example .env   # set SECRET_KEY
docker compose up --build
```

Open http://localhost (frontend) — API at http://localhost:8000/api/health.

## Run (local dev, no Docker)

```sh
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
DEV_OTP=true SECRET_KEY=dev-only .venv/bin/python -m uvicorn app.main:app --port 8000
cd ../frontend
npm install && npm run dev   # http://localhost:5173 (proxies /api)
```

## Test login (works out of the box, dev mode only)

1. Open the app, enter `admin@demo.example`, request a code.
2. In development mode the code is returned on screen (no message is
   sent — Phase 2 sends in log mode by default; live sending needs the
   firm's verified sender identity plus a received test message).
3. Sign in with the code. Other demo accounts: `consultant@demo.example`,
   `filing@demo.example`. Demo firm: "Maple Leaf Immigration (Demo)"
   (fictional), branches Toronto + Mississauga, 4 seed leads, 1 seed
   client, 2 seed cases, all 6 stream templates.

Do NOT enable DEV_OTP in production: with it on, anyone who knows a
staff email can sign in. Production OTP delivery needs the Phase 2
channel.

## Phase 2 — communications and calendar (Features 11–17)

**Safety first (enforced in the adapters, not the UI):**
- SMS and email ship in **log mode by default** for every firm: messages
  are composed, recorded against the case, and shown as "would send".
  Nothing is delivered to any phone or inbox.
- **Live sending is gated per firm, per channel**: the sender must be
  verified AND a test message received (both recorded in Settings →
  Comms, firm-admin only, audited). Without both, the adapter refuses
  with a clear error before any send is attempted. Unverified senders
  are blocked, never discovered as a bounce.
- Live mode additionally needs provider credentials in env
  (`TWILIO_*`, `SENDGRID_API_KEY` in `.env.example` — placeholders
  only, never committed with real values). Without them the adapter
  refuses rather than pretending.
- **Consent**: a phone number on a lead/client record counts as
  recorded consent; the opt-out list revokes it and is honoured
  automatically on the next send (recorded as `suppressed_opt_out`).
  Every SMS template carries the firm's opt-out wording.
- **Failed sends/reminders retry once** (jobs: `POST /api/jobs/run-outbox`,
  `POST /api/jobs/run-reminders`), then surface on the dashboard as an
  action item — never silently dropped. A slow provider never blocks a
  staff screen: booking works even when Google is unreachable
  (sync stays pending, `POST /api/jobs/run-sync` retries, failure
  becomes an action item).
- **One chronological log per case**: every SMS and email for a case
  (plus client-linked messages) in order, on the case and the client
  360 view. Messages for a consultation not linked to a case are
  recorded against the client/lead and visible on the client messages
  endpoint.
- **Google Calendar sync — honest scope**: the sync state machine is
  real (CRM is source of truth; a Google-side delete marks the
  consultation `cancelled_externally` and notifies client + staff; a
  Google-side working-hours event blocks the slot in the week view).
  The staff connection is recorded in Settings (no OAuth token is ever
  stored); when connected, sync actions are marked synced (simulated
  delivery). Real Google API calls need the registered Google OAuth app
  (List B item 4) and are NOT made or claimed here.
- **Calendly**: per-consultant event types (slot, buffer, working
  hours, paid/free) with a booking link. Bookings arrive via
  `POST /api/bookings/calendly` (payload must carry `firm_slug`;
  HMAC-checked when `CALENDLY_WEBHOOK_SECRET` is set, otherwise
  demo-only). A booking matches a lead/client by email — staff never
  retype it. Paid slots stay `payment_pending` until payment is
  confirmed (`POST /api/consultations/{id}/confirm-payment`).
  Out-of-hours and overlapping bookings are refused.
- **Calendar privacy**: event titles/descriptions contain only the
  consultation type and the consultant — never client names, streams,
  or case details (unit-checked).
- **AI drafts (Feature 17)**: provider is the built-in template adapter
  (`AI_PROVIDER=template`, the default) — it drafts ONLY from stored
  case data (stream-template checklist, the case's own deadlines), so it
  cannot invent a case fact and no firm/client data leaves the firm.
  Swapping providers is a config change behind `ai_drafts.py`. The
  human gate is absolute: a draft is a row, never a send; only staff
  Approve sends it, through the normal message path, logged as a STAFF
  message with the draft id recorded. In log mode an approved draft is
  recorded as "would send" and delivered to nobody. Drafts are
  tenant-scoped like everything else.
- **Test hooks**: `POST /api/test-hooks/fail-message` and
  `POST /api/test-hooks/fail-reminder` exist ONLY when
  `ALLOW_TEST_HOOKS=true` (default off, never on in production). They
  inject the failure states a real provider outage would produce, so
  the retry-then-action-item rules are verifiable without an outage.

Frontend pages added: Messages (case log + compose + AI drafts),
Calendar (week view + booking), Comms (settings, gates, templates),
lead-detail inline booking.

## Acceptance-test checklist (actually run, Oct 27, 2026)

Backend booted from `backend/` on a fresh SQLite file with
`DEV_OTP=true`, `ALLOW_TEST_HOOKS=true`; `python scripts/smoke_test.py`
(55 checks), `scripts/phase2_isolation_probe.py` (11 checks),
`scripts/phase2_unit_checks.py` (10 checks), and `vite build` — all
against the same build. Phase 1 checks 1–16 re-ran unchanged (health
now reports phase 2).

| # | Check | Result |
|---|-------|--------|
| 1–16 | Phase 1 checks (OTP, leads, convert, 360, stage timeline, dashboard, templates, settings, 401/400, tenant isolation) | PASS |
| 17 | Comms settings default to log mode; 16 default templates (8 keys × SMS+email) | PASS |
| 18 | Log-mode SMS recorded as would-send, personalised, opt-out wording attached | PASS |
| 19 | Log-mode email recorded as would-send; one chronological case log (SMS then email) | PASS |
| 20 | Unverified live sender blocked with clear error, no message recorded | PASS |
| 21 | Opted-out number receives no further SMS (suppressed, recorded) | PASS |
| 22 | Failed send retried once, then dashboard action item (never silently dropped) | PASS |
| 23 | Event type configured, booking link reflects it | PASS |
| 24 | Calendly booking creates consultation on matching client, no retyping | PASS |
| 25 | Paid consultation NOT confirmed until payment; confirm-payment books it | PASS |
| 26 | Out-of-hours and overlapping bookings refused | PASS |
| 27 | Staff calendar connection recorded; Google working-hours event blocks slot; week view reflects it with no client detail | PASS |
| 28 | Blocked slot cannot be booked from the CRM | PASS |
| 29 | Google-side delete → cancelled externally + client notified, not silent | PASS |
| 30 | CRM booking sends confirmation by SMS + email (log mode) | PASS |
| 31 | Reminder at configured interval, both channels, idempotent per window | PASS |
| 32 | Reschedule + cancel re-notify by both channels | PASS |
| 33 | Booking records when Google unreachable; sync failure surfaces as action item | PASS |
| 34 | Deadline created; reminder by SMS + email logged against the case (would-send in log mode) | PASS |
| 35 | Failed reminder retried once, then action item | PASS |
| 36 | AI document-request draft names exactly the checklist items, nothing sent | PASS |
| 37 | AI deadline-summary draft names the correct deadlines | PASS |
| 38 | Approved draft sends as a STAFF message (would-send in log mode, draft id recorded); cannot approve twice; discard works | PASS |
| 39 | Audit trail records message sends, draft approvals, bookings | PASS |
| 40 | Second firm sees none of the first firm's Phase 2 resources (11 probe checks) | PASS |
| 41 | Google payload privacy + template rendering + hours helpers (10 unit checks) | PASS |
| 42 | Frontend production build (`vite build`) | PASS |

Total: 55 smoke + 11 isolation + 10 unit, 0 failed. Docker Compose was
NOT run here (no Docker on the build machine) — it is provided
following the proven platform pattern and needs one
`docker compose up --build` on a Docker host before it counts as
verified.

## Still unverified (needs real provider accounts / a Docker host)

- Real Twilio SMS / SendGrid email delivery under a firm's own sender
  identity (log mode only here — no credentials exist in this repo).
- Real Google OAuth flow and live Google Calendar API calls (sync is a
  faithful state machine with simulated delivery when connected).
- Real Calendly webhook signature + live booking (webhook contract
  implemented; HMAC enforced when the secret is set).
- The Docker Compose run (see above).
- The Phase 2 demo gate with Surath (test SMS/email received, Calendly
  booking on a lead, Google event blocking a slot, reschedule
  notification, AI draft approval) — the user tests everything at once
  later; nothing here asks for testing now.

## Phase gate

Phase 2 is built and committed. Testing is deferred: the user tests
everything at once later.

