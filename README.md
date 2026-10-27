# Immigration Consultant CRM — Phase 1

Staff CRM for immigration consultants: leads, clients, cases, dashboard,
stream templates, firm/team settings. Phase 1 only — no SMS/email
sending (Phase 2), no client portal (Phase 3), no billing (Phase 4).

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
   sent — Phase 1 has no sending channel; delivery arrives in Phase 2).
3. Sign in with the code. Other demo accounts: `consultant@demo.example`,
   `filing@demo.example`. Demo firm: "Maple Leaf Immigration (Demo)"
   (fictional), branches Toronto + Mississauga, 4 seed leads, 1 seed
   client, 2 seed cases, all 6 stream templates.

Do NOT enable DEV_OTP in production: with it on, anyone who knows a
staff email can sign in. Production OTP delivery needs the Phase 2
channel.

## Acceptance-test checklist (actually run, Oct 26, 2026)

Backend booted from `backend/` on SQLite; `python scripts/smoke_test.py`
against it, plus a separate tenant-isolation probe:

| # | Check | Result |
|---|-------|--------|
| 1 | Health endpoint 200, phase 1 | PASS |
| 2 | OTP issued in dev mode | PASS |
| 3 | OTP verify returns JWT | PASS |
| 4 | /api/me returns admin + firm | PASS |
| 5 | Seed leads listed (4+) | PASS |
| 6 | Create lead | PASS |
| 7 | Convert lead -> client + case, contact/stream copied, no retyping | PASS |
| 8 | Client 360 view shows the case | PASS |
| 9 | Case stage move appends timeline event | PASS |
| 10 | Dashboard core cards computed live | PASS |
| 11 | 6 stream templates | PASS |
| 12 | Settings: firm + 2 branches + team | PASS |
| 13 | Unauthenticated request rejected (401) | PASS |
| 14 | Invalid lead stage rejected (400) | PASS |
| 15 | Second firm sees none of the first firm's leads/cases/clients | PASS |
| 16 | Frontend production build (`vite build`) | PASS |

Total: 16 passed, 0 failed. Docker Compose was NOT run here (no Docker
on the build machine) — it is provided following the proven platform
pattern and needs one `docker compose up --build` on a Docker host
before it counts as verified.

## Phase gate

Phase 2 starts only after Surath sees the Phase 1 demo and approves.
Nothing in Phase 1 sends any real message anywhere.
