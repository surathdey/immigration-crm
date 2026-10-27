"""Phase 4 tenant/portal isolation probe (mirrors the Phase 3 probe).

Creates a second firm directly in the database (and a receptionist in
the demo firm), then verifies that:
- Firm B staff see empty invoice lists, 404 on every Firm A billing
  object (invoice, payment via invoice view, template), empty reports,
  and their own subscription row — never Firm A's money data.
- A portal client sees 404 on another client's invoice.
- A receptionist gets 403 on billing and report endpoints (design doc
  roles table: no access to billing internals).
- A portal token cannot call staff billing endpoints; a staff token
  cannot call portal invoice endpoints.

Usage: python scripts/phase4_isolation_probe.py [BASE_URL]
IMPORTANT: run with the SAME DATABASE_URL as the backend under test —
the probe creates Firm B directly in that database (like the Phase 2/3
probes). It signs in with DEV_OTP codes, so the backend needs
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


def portal_token(identifier, firm_slug):
    s, otp = call("POST", "/api/portal/request-otp",
                  body={"identifier": identifier, "firm_slug": firm_slug})
    s, auth = call("POST", "/api/portal/verify-otp",
                   body={"identifier": identifier, "firm_slug": firm_slug,
                         "code": otp.get("dev_code")})
    return auth.get("token")


token_a = staff_token("admin@demo.example")
s, invs_a = call("GET", "/api/invoices", token_a)
inv_a = invs_a[0] if isinstance(invs_a, list) and invs_a else None
check("Firm A has at least one invoice to isolate against", bool(inv_a), str(invs_a)[:200])

# Firm B + a receptionist in Firm A, created directly in the database.
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
    db.refresh(firm_b)
    branch_b = db.query(Branch).filter(Branch.tenant_id == firm_b.id).first()
firm_a = db.query(Tenant).filter(Tenant.slug == "demo-firm").first()
branch_a = db.query(Branch).filter(Branch.tenant_id == firm_a.id).first()
if not db.query(User).filter(User.email == "reception@probe.example").first():
    db.add(User(tenant_id=firm_a.id, branch_id=branch_a.id,
                email="reception@probe.example", full_name="Probe Receptionist",
                role="receptionist"))
    db.commit()
db.close()

token_b = staff_token("admin2@probe.example")
s, invs_b = call("GET", "/api/invoices", token_b)
check("Firm B sees an empty invoice list", s == 200 and invs_b == [], str(invs_b))
if inv_a:
    s, one = call("GET", f"/api/invoices/{inv_a['id']}", token_b)
    check("Firm B gets 404 on a Firm A invoice", s == 404, str(one))
    s, pay = call("POST", f"/api/invoices/{inv_a['id']}/payments", token_b, body={
        "method": "cash", "amount_cents": 1})
    check("Firm B cannot record a payment on a Firm A invoice (404)", s == 404, str(pay))
s, tmpl_b = call("GET", "/api/billing/templates", token_b)
check("Firm B sees no Firm A invoice templates", s == 200 and tmpl_b == [], str(tmpl_b))
s, rep_b = call("GET", "/api/reports/summary", token_b)
check("Firm B reports show no Firm A revenue",
      s == 200 and rep_b.get("revenue_by_month") == [] and rep_b.get("workload") == [],
      str(rep_b))
s, sub_b = call("GET", "/api/settings/subscription", token_b)
check("Firm B has its own subscription row (not Firm A's)",
      s == 200 and sub_b.get("plan") == "starter", str(sub_b))

token_r = staff_token("reception@probe.example")
s, rb = call("GET", "/api/invoices", token_r)
check("Receptionist gets 403 on billing lists", s == 403, str(rb))
s, rr = call("GET", "/api/reports/summary", token_r)
check("Receptionist gets 403 on reports", s == 403, str(rr))

ptoken = portal_token("aisha@example.com", "demo-firm")
s, p_bad = call("GET", "/api/invoices", ptoken)
check("Portal token cannot call staff billing endpoints (401)", s == 401, str(s))
s, clients_a = call("GET", "/api/clients", token_a)
aisha = next((c for c in clients_a if c["email"] == "aisha@example.com"), None) if isinstance(clients_a, list) else None
aisha_inv = next((i for i in invs_a if i["client_id"] == aisha["id"]), None) if (aisha and isinstance(invs_a, list)) else None
if aisha_inv:
    s, p_inv = call("GET", f"/api/portal/invoices/{aisha_inv['id']}", ptoken)
    check("Portal client opens her own invoice",
          s == 200 and p_inv.get("number") == aisha_inv["number"], str(p_inv))
    other_inv = next((i for i in invs_a if i["client_id"] != aisha["id"]), None)
    if other_inv:
        s, p_other = call("GET", f"/api/portal/invoices/{other_inv['id']}", ptoken)
        check("Portal client gets 404 on another client's invoice", s == 404, str(p_other))
else:
    print("SKIP portal own-invoice checks (no Aisha invoice — run smoke first)")
s, s_bad = call("GET", "/api/portal/invoices", token_a)
check("Staff token cannot call portal invoice endpoints (401)", s == 401, str(s))

print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED:", failed)
    sys.exit(1)
