# Immigration Consultant CRM — Phase 1 + Phase 2 + Phase 3

Staff CRM for immigration consultants: leads, clients, cases, dashboard,
stream templates, firm/team settings (Phase 1), plus communications and
calendar (Phase 2): SMS via Twilio and email via SendGrid in log mode by
default, Calendly booking links, Google Calendar two-way sync,
consultation booking/reminders/reschedule/cancel, deadline reminders,
and AI-drafted staff messages behind a human gate. Plus documents and
the client portal (Phase 3): per-stream document checklists, upload +
version history, review queue with approve/reject-with-reason, expiry
alerts, submission packet download, AI document reading behind a human
gate, and a client portal with OTP sign-in. No billing (Phase 4).

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

## Client portal login (works out of the box, dev mode only)

From the sign-in screen, choose "I am a client — open the client
portal". Enter the client email (`aisha@example.com` for the demo
client) and the firm slug (`demo-firm`), request a code, and sign in
with the returned code. The portal shows only that client's own cases,
checklist, uploads, and messages — never another client's data. A
portal token cannot call staff endpoints (401), and a staff token
cannot call portal endpoints (401).

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

## Phase 3 — documents and client portal (W7, W10, W11, Section 6.1)

**Checklists:** every case starts with its stream template's document
checklist (auto-created on case open; `POST /cases/{id}/checklist/init`
backfills older cases). Statuses follow the design doc's fixed ladder:
Not Started / Requested / Uploaded / Under Review / Approved /
Rejected / Expired.

**Uploads + versions:** files live under `backend/data/uploads/` (a
gitignored dir), referenced from the database — never stored as blobs.
Every upload is a new version; the full history (with each version's
review decision and reason) is kept. Staff and clients upload through
separate endpoints with separate auth; a client uploads only against
checklist items on their own cases.

**Review queue (W7):** items in Uploaded or Under Review, oldest
first. Staff request → start review → approve, or reject with a
reason (a reason is required; an empty reason is refused). The client
sees the reason in the portal and re-uploads; the queue empties as
items are decided. Review decisions notify the client through the
Phase 2 log-mode adapters (no new senders).

**AI document reading (6.1):** the same template-adapter pattern as
Phase 2 drafts (`AI_PROVIDER=template`, default). When a readable text
file is uploaded, the adapter proposes case-field values (UCI, IRCC
file number, expiry date) and mismatch flags (name differs from the
file, expiry already past) into the W7 AI suggestions panel. A proposal
is NEVER a case value until a consultant approves it: approving a value
suggestion writes the field, approving a mismatch only acknowledges it,
and rejecting dismisses it. Binary/unreadable uploads produce no
suggestions, by design — the panel is simply empty.

**Expiry alerts + packet:** `POST /api/jobs/run-expiry-alerts` flips
past-expiry items to Expired and alerts items expiring within 30 days,
each expiry date alerted once (re-runs never spam). `GET
/api/cases/{id}/packet` downloads a ZIP of the latest APPROVED version
of each item plus a manifest (items without an approved version are
listed as missing, not silently dropped).

**Portal (W10/W11):** clients sign in with an email/phone OTP
(firm-scoped via slug); portal home shows their cases with checklist
counts and the next deadline; portal documents show each item's
status, rejection reasons, and the firm's messages (read-only).

## Phase 4 — billing, deadline engine, reports, portal AI assistant (W9, W2 complete, W12 subscription, Section 6.2)

**Billing (W9):** invoice templates with line items and an instalment
plan (shares must sum to 1; the last instalment takes rounding
remainder). Invoices number per firm (INV-0001, …), carry instalments
with due dates, and move Draft → Sent → Partially Paid → Paid; the
billing job flips past-due Sent/Partially Paid invoices to Overdue and
sends one overdue reminder per invoice per day (log mode by default,
via the Phase 2 adapters — no new senders). Payments record card,
e-transfer, or cash with a per-firm receipt number (RCP-0001, …) and
allocate oldest-pending-instalment-first; overpayments and payments on
Draft invoices are refused. **Card payments are recorded, not
charged:** live Stripe charging is NOT implemented — no Stripe
credential exists anywhere in this repo, and the `STRIPE_SECRET_KEY`
placeholder stays empty.

**Subscription (W12):** one row per firm (plan starter/growth/scale,
status trialing/active/past_due/cancelled, seats, dates), firm-admin
only. Mechanics are deliberately simple: the design doc names
subscription management but specifies no proration, trial, or dunning
flow, and none is invented here.

**Deadline engine:** firm rules derive deadlines from case creation,
stage entry, or submission date (idempotent — a second run never
duplicates an open deadline). The alert job sends 30/14/7-day alerts
through the Phase 2 adapters (one per deadline per window, never
repeated) and escalates overdue deadlines to a dashboard action item
for the branch manager / firm admin (deduped while unresolved).

**Reports (W2 complete):** approval rate by stream (decided cases with
closure "Approved" over "Approved"+"Refused"; null, never 0%, when no
case is decided), average days per stage from the timeline, workload
(open cases per assignee), revenue by month (payments received +
invoices issued). `GET /api/reports/export.xlsx` downloads a workbook
(Summary, Revenue by month, Workload, Stage durations, Invoices,
Payments) for the accountant.

**Portal AI assistant (6.2):** the same template-adapter pattern as
Phases 2/3 — no external model call, no data leaves the firm. It
answers ONLY from the signed-in client's own case data (stage, next
step, deadline, outstanding documents, appointments, invoices) and
cites the fields used. Anything about eligibility, law, strategy, or
likely outcomes — or anything it cannot answer from the case file —
routes plainly to the consultant, and the turn is logged for staff
review on the case. It never invents a fact: no deadline, no invoice,
or no appointment is answered as such, not guessed.

**Roles:** the design doc's Receptionist ("no access to billing
internals") gets 403 on billing and report endpoints; subscription is
firm-admin only. Branch scoping from Phase 1 still applies to billing
rows.

## Acceptance-test checklist (actually run, Oct 27, 2026)

Backend booted from `backend/` on a fresh SQLite file with
`DEV_OTP=true`, `ALLOW_TEST_HOOKS=true`; `python scripts/smoke_test.py`
(123 checks), `scripts/phase4_isolation_probe.py` (13 checks),
`scripts/phase3_isolation_probe.py` (11 checks),
`scripts/phase2_unit_checks.py` (10 checks), and `vite build` — all
against the same build. Phase 1–3 checks re-ran unchanged
(health now reports phase 4).

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
| 43 | Checklist init from stream template (5 Express Entry items), idempotent | PASS |
| 44 | Staff requests a document; client notified in log mode | PASS |
| 45 | Portal OTP sign-in (email + firm slug); portal home shows only own cases + checklist counts | PASS |
| 46 | Client uploads in portal → version 1, item Uploaded, AI expiry + UCI proposals Pending (nothing applied yet) | PASS |
| 47 | Review queue holds the item; start review → Under Review; empty-reason reject refused | PASS |
| 48 | Reject with reason → client sees the reason in the portal | PASS |
| 49 | Client re-uploads → version 2; version history keeps both decisions; approve → queue empties for the item; double-approve refused | PASS |
| 50 | Approving AI proposals writes expiry date to the item and UCI to the case; a decided suggestion cannot be decided twice | PASS |
| 51 | Name-mismatch flag dismissed with no client data changed | PASS |
| 52 | Staff upload path; staff + portal download return the uploaded bytes | PASS |
| 53 | Expiry job: past-expiry → Expired + notified; expiring-soon alerts exactly once across re-runs | PASS |
| 54 | Submission packet ZIP with manifest naming the approved Passport | PASS |
| 55 | Token separation: portal token 401 on staff endpoints, staff token 401 on portal endpoints | PASS |
| 56 | Isolation probe: Firm B sees nothing of Firm A documents; portal client sees nothing of another client's case (11 probe checks) | PASS |
| 57 | Invoice template (shares must sum to 1) + invoice from template: number, total, 2 instalments, Draft; payment on Draft refused | PASS |
| 58 | Invoice send Draft → Sent; partial payment → Partially Paid + receipt + first instalment paid; overpayment refused | PASS |
| 59 | Billing job: past-due invoice → Overdue + one reminder, idempotent within the day; final payment reconciles to Paid, balance zero | PASS |
| 60 | Client 360 view lists invoices; subscription defaults + firm-admin update; non-admin change refused (403) | PASS |
| 61 | Deadline rule → derive creates one deadline, derive again creates none; 30-day alert fires once, never repeats | PASS |
| 62 | Overdue deadline escalates to a dashboard action item, deduped while unresolved | PASS |
| 63 | Reports summary has all four sections; revenue by month matches recorded payments; .xlsx export has all six sheets | PASS |
| 64 | Portal assistant: status answer cites own stage, not routed; eligibility question routed to consultant; another client's case refused (404); staff review turns on the case | PASS |
| 65 | Portal lists own invoices only; another client's invoice refused (404) | PASS |
| 66 | Isolation probe: Firm B sees no Firm A billing/reports/subscription; receptionist 403 on billing/reports; portal/staff token separation (13 probe checks) | PASS |

Total: 123 smoke + 13 + 11 isolation + 10 unit, 0 failed. Docker Compose was
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
- Real AI document reading (a managed model provider): the built-in
  template adapter reads only readable text files; scanned PDFs/images
  produce no suggestions until a real reader is configured.
- The Phase 2 demo gate with Surath (test SMS/email received, Calendly
  booking on a lead, Google event blocking a slot, reschedule
  notification, AI draft approval) — the user tests phase by phase
  later; nothing here asks for testing now.
- The Phase 3 demo gate with Surath (client uploads → staff rejects
  with reason → client sees reason and re-uploads → staff approves, end
  to end with no phone call; review queue empties top to bottom; an
  upload's proposed field values stay unsaved until consultant
  approval) — same deferred phase-by-phase testing.
- The Phase 4 demo gate with Surath (an invoice is issued, partially
  paid, reminded when overdue, and reconciled; an overdue deadline
  escalates to the branch manager; a report exports to spreadsheet for
  the accountant; a client asks the portal assistant about their own
  case and gets an answer drawn from their case data, or a routing to
  the consultant when the assistant does not know) — same deferred
  phase-by-phase testing.
- Live Stripe charging (card payments are recorded, not charged, in
  this build) and any proration/trial/dunning subscription flow (the
  design doc does not specify one).

## Phase gate

Phase 4 is built and committed locally (not yet pushed — the parent
pushes after verification). Testing is deferred: the user tests phase
by phase later.

