"""Phase 1 acceptance smoke test. Boots nothing itself — run against a
live backend (see README). Exits non-zero if any check fails.
Usage: python scripts/smoke_test.py [BASE_URL]
"""
import json
import sys
import urllib.request

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


s, health = call("GET", "/api/health")
check("health 200 + phase 1", s == 200 and health.get("phase") == 1, str(health))

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

print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED:", failed)
    sys.exit(1)
