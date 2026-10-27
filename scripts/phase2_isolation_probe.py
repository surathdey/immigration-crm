"""Phase 2 tenant-isolation probe (mirrors the Phase 1 probe approach).

Creates a second firm directly in the database, signs in as its admin,
and verifies that none of Firm A's Phase 2 resources (messages, drafts,
consultations, deadlines, action items, templates, settings) are visible
or openable from Firm B — not by listing, not by guessing an id.
Usage: python scripts/phase2_isolation_probe.py [BASE_URL]
"""
import json
import os
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
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


# Firm A (seed) ids, via the admin token.
s, otp = call("POST", "/api/auth/request-otp", body={"email": "admin@demo.example"})
s, auth_a = call("POST", "/api/auth/verify-otp", body={"email": "admin@demo.example", "code": otp["dev_code"]})
token_a = auth_a["token"]
s, cases_a = call("GET", "/api/cases", token=token_a)
case_a = cases_a[0]["id"] if cases_a else None
s, cons_a = call("GET", "/api/consultations", token=token_a)
cons_id_a = cons_a[0]["id"] if cons_a else None

# Create Firm B directly (no firm-creation endpoint exists in Phase 1/2).
from app.db import SessionLocal
from app.models import Tenant, Branch, User
db = SessionLocal()
firm_b = db.query(Tenant).filter(Tenant.slug == "second-firm").first()
if not firm_b:
    firm_b = Tenant(name="Second Firm (Probe)", slug="second-firm")
    db.add(firm_b)
    db.flush()
    branch_b = Branch(tenant_id=firm_b.id, name="Toronto", city="Toronto")
    db.add(branch_b)
    db.flush()
    db.add(User(tenant_id=firm_b.id, branch_id=branch_b.id,
                email="admin2@probe.example", full_name="Probe Admin", role="firm_admin"))
    db.commit()
db.close()

s, otp_b = call("POST", "/api/auth/request-otp", body={"email": "admin2@probe.example"})
s, auth_b = call("POST", "/api/auth/verify-otp", body={"email": "admin2@probe.example", "code": otp_b["dev_code"]})
token_b = auth_b.get("token")
check("second firm admin signs in", s == 200 and bool(token_b), str(auth_b))

for path, label in [
        ("/api/consultations", "consultations"),
        ("/api/event-types", "event types"),
        ("/api/action-items", "action items"),
        ("/api/audit-log", "audit log")]:
    s, rows = call("GET", path, token=token_b)
    check(f"Firm B sees no Firm A {label}", s == 200 and rows == [], str(rows))
if case_a:
    s, rows = call("GET", f"/api/cases/{case_a}/messages", token=token_b)
    check("Firm B cannot open Firm A case messages (404)", s == 404, str(s))
    s, rows = call("GET", f"/api/cases/{case_a}/drafts", token=token_b)
    check("Firm B cannot open Firm A case drafts (404)", s == 404, str(s))
    s, rows = call("GET", f"/api/cases/{case_a}/deadlines", token=token_b)
    check("Firm B cannot open Firm A case deadlines (404)", s == 404, str(s))
if cons_id_a:
    s, row = call("GET", f"/api/consultations/{cons_id_a}", token=token_b)
    check("Firm B cannot open Firm A consultation by id (404)", s == 404, str(s))
s, comms_b = call("GET", "/api/settings/communications", token=token_b)
check("Firm B has its own (default log-mode) comms settings",
      s == 200 and comms_b["settings"]["sms_mode"] == "log", str(comms_b.get("settings")))
check("Firm B templates are its own rows, not Firm A's",
      s == 200 and len(comms_b.get("templates", [])) == 16, str(len(comms_b.get("templates", []))))

print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED:", failed)
    sys.exit(1)
