"""Phase 5 tenant isolation probe (mirrors the Phase 4 probe).

Creates a second firm directly in the database (and a receptionist in
the demo firm), then verifies that:
- Firm B staff see empty retainer/form/chase lists, 404 on every Firm A
  Phase 5 object (retainer, form), and no Firm A pre-check results.
- A receptionist gets 403 on Phase 5 writes (retainer generate/sign,
  form generate, chasing job) and on retainer templates.
- A staff token cannot open another firm's retainer or form by id.

Usage: python scripts/phase5_isolation_probe.py [BASE_URL]
IMPORTANT: run with the SAME DATABASE_URL as the backend under test —
the probe creates Firm B directly in that database (like the Phase 2/3/4
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


token = staff_token("admin@demo.example")
check("firm A admin signs in", bool(token))

# Firm A objects: use the seed case (client Aisha Khan's first case).
s, cases = call("GET", "/api/cases", token)
case_a = cases[0]["id"] if cases else None
check("firm A has a case", bool(case_a), str(cases)[:200])
s, ret = call("POST", f"/api/cases/{case_a}/retainers", token, body={})
ret_a = ret.get("id")
check("firm A retainer created", s == 200 and bool(ret_a), str(ret))
s, form = call("POST", f"/api/cases/{case_a}/ircc-forms", token, body={"form_code": "IMM 0008"})
form_a = form.get("id")
check("firm A form created", s == 200 and bool(form_a), str(form))
s, pc = call("POST", "/api/staff/precheck", token, body={
    "answers": {"education": "bachelor", "language_clb": 8, "work_years": 4},
    "email": "probe5@example.com", "full_name": "Probe Five"})
pc_lead = pc.get("lead_id")
check("firm A staff pre-check recorded", s == 200 and bool(pc_lead), str(pc))

# Second firm + receptionist, directly in the database.
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
admin_b = db.query(User).filter(User.email == "admin2@probe.example").first()
recep = db.query(User).filter(User.email == "recep@demo.example").first()
if not recep:
    admin_a = db.query(User).filter(User.email == "admin@demo.example").first()
    recep = User(tenant_id=admin_a.tenant_id, branch_id=admin_a.branch_id,
                 email="recep@demo.example", full_name="Probe Receptionist", role="receptionist")
    db.add(recep)
    db.commit()
db.close()

token_b = staff_token("admin2@probe.example")
check("second firm admin signs in", bool(token_b))
token_r = staff_token("recep@demo.example")
check("receptionist signs in", bool(token_r))

s, rets_b = call("GET", f"/api/cases/{case_a}/retainers", token_b)
check("firm B cannot list firm A retainers (404)", s == 404, str(s))
s, ret_b = call("GET", f"/api/retainers/{ret_a}", token_b)
check("firm B cannot open firm A retainer by id (404)", s == 404, str(s))
s, form_b = call("GET", f"/api/ircc-forms/{form_a}", token_b)
check("firm B cannot open firm A form by id (404)", s == 404, str(s))
s, chases_b = call("GET", f"/api/cases/{case_a}/chases", token_b)
check("firm B cannot list firm A chases (404)", s == 404, str(s))
s, pc_b = call("GET", f"/api/leads/{pc_lead}/prechecks", token_b)
check("firm B cannot list firm A lead pre-checks (404)", s == 404, str(s))

s, r = call("POST", f"/api/cases/{case_a}/retainers", token_r, body={})
check("receptionist cannot generate retainers (403)", s == 403, str(s))
s, r = call("POST", f"/api/retainers/{ret_a}/sign", token_r, body={"signer_name": "X"})
check("receptionist cannot sign retainers (403)", s == 403, str(s))
s, r = call("POST", f"/api/cases/{case_a}/ircc-forms", token_r, body={"form_code": "IMM 0008"})
check("receptionist cannot generate forms (403)", s == 403, str(s))
s, r = call("POST", "/api/jobs/run-chasing", token_r, body={})
check("receptionist cannot run chasing (403)", s == 403, str(s))
s, r = call("POST", "/api/retainer-templates", token_r, body={"name": "X", "body": "Y"})
check("receptionist cannot create retainer templates (403)", s == 403, str(s))

print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED:", failed)
    sys.exit(1)
