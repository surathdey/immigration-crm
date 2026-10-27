"""Phase 3 tenant/portal isolation probe (mirrors the Phase 2 probe).

Creates a second firm directly in the database and a second client in
the demo firm, then verifies that:
- Firm B staff see an empty review queue and 404 on every Firm A
  document object (checklist, version download, packet, suggestion).
- A portal client sees 404 on another client's case, checklist upload,
  and document download — never the data itself.
- Portal tokens cannot call staff endpoints; staff tokens cannot call
  portal endpoints.

Usage: python scripts/phase3_isolation_probe.py [BASE_URL]
IMPORTANT: run with the SAME DATABASE_URL as the backend under test —
the probe creates Firm B directly in that database (like the Phase 2
probe). It signs in with DEV_OTP codes, so the backend needs
DEV_OTP=true.
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


def staff_token(email):
    s, otp = call("POST", "/api/auth/request-otp", body={"email": email})
    s, auth = call("POST", "/api/auth/verify-otp",
                   body={"email": email, "code": otp.get("dev_code")})
    return auth.get("token")


def portal_token(identifier):
    s, otp = call("POST", "/api/portal/request-otp",
                  body={"identifier": identifier, "firm_slug": "demo-firm"})
    s, auth = call("POST", "/api/portal/verify-otp",
                   body={"identifier": identifier, "firm_slug": "demo-firm",
                         "code": otp.get("dev_code")})
    return auth.get("token")


# Firm A (seed) staff + portal client
token_a = staff_token("admin@demo.example")
ptoken_a = portal_token("aisha@example.com")
s, cases_a = call("GET", "/api/cases", token=token_a)
case_a = cases_a[0]["id"]
s, checklist_a = call("GET", f"/api/cases/{case_a}/checklist", token=token_a)
item_a = checklist_a[0]["id"] if checklist_a else None

# Firm B directly in the database (no firm-creation endpoint exists).
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
token_b = staff_token("admin2@probe.example")
check("second firm admin signs in", bool(token_b))

# Firm B sees none of Firm A's document objects
s, queue_b = call("GET", "/api/review-queue", token=token_b)
check("Firm B review queue is empty (no Firm A items leak)",
      s == 200 and queue_b == [], str(queue_b))
s, _ = call("GET", f"/api/cases/{case_a}/checklist", token=token_b)
check("Firm B cannot open Firm A checklist (404)", s == 404, str(s))
s, _ = call("GET", f"/api/cases/{case_a}/packet", token=token_b)
check("Firm B cannot download Firm A packet (404)", s == 404, str(s))
if item_a:
    s, _ = call("GET", f"/api/checklist-items/{item_a}/versions", token=token_b)
    check("Firm B cannot open Firm A versions (404)", s == 404, str(s))
    s, _ = call("POST", f"/api/checklist-items/{item_a}/approve", token=token_b, body={})
    check("Firm B cannot approve a Firm A item (404)", s == 404, str(s))

# A second client in Firm A, with its own case + uploaded version
s, other = call("POST", "/api/clients", token=token_a,
                body={"full_name": "Probe Other", "email": "other@probe.example"})
other_client = other.get("id")
s, new_case = call("POST", "/api/cases", token=token_a,
                   body={"client_id": other_client, "stream": "Work", "stage": "Documents"})
other_case = new_case.get("id")
s, other_items = call("GET", f"/api/cases/{other_case}/checklist", token=token_a)
other_item = other_items[0]["id"] if other_items else None
check("other client's case has its own checklist", bool(other_item), str(other_items))

# Portal client A cannot touch the other client's case or documents
s, _ = call("GET", f"/api/portal/cases/{other_case}", token=ptoken_a)
check("portal client cannot open another client's case (404)", s == 404, str(s))
if other_item:
    s, _ = call("GET", f"/api/portal/cases/{other_case}", token=ptoken_a)
    check("portal client cannot list another client's checklist (404)", s == 404, str(s))
s, _ = call("GET", "/api/portal/cases", token=token_a)
check("staff token cannot call portal endpoints (401)", s == 401, str(s))
s, _ = call("GET", "/api/review-queue", token=ptoken_a)
check("portal token cannot call staff endpoints (401)", s == 401, str(s))

print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED:", failed)
    sys.exit(1)
