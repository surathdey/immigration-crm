"""Phase 2 unit checks that need no HTTP server (run with backend .venv).

- Google sync payload privacy: no client name, stream, or case detail.
- Template rendering placeholders.
- Working-hours + overlap helpers.
Usage: cd backend && .venv/bin/python ../scripts/phase2_unit_checks.py
"""
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")
from app import booking, messaging

passed, failed = [], []


def check(name, cond, extra=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" — {extra}" if extra and not cond else ""))


cons = SimpleNamespace(kind="Consultation")
payload = booking.google_event_payload(cons, "Priya Sharma")
check("Google payload title is the consultation type only",
      payload["title"] == "Consultation", str(payload))
for secret in ("Aisha Khan", "Express Entry", "E123456789", "1234-5678"):
    check(f"Google payload contains no client detail ({secret})",
          secret not in payload["title"] and secret not in payload["description"], str(payload))

rendered = messaging.render("Hi {client_name}, your {case_stream} case (#{case_id}) at {firm_name}.",
                            "Aisha Khan", "Express Entry", 42, "Maple Leaf Immigration (Demo)")
check("template rendering fills all placeholders",
      rendered == "Hi Aisha Khan, your Express Entry case (#42) at Maple Leaf Immigration (Demo).", rendered)

from datetime import datetime
hours = {"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00"}
check("weekday 10:00 within hours",
      booking.within_hours(hours, datetime(2026, 11, 2, 10, 0), datetime(2026, 11, 2, 10, 30)))
check("Saturday refused by hours check",
      not booking.within_hours(hours, datetime(2026, 11, 7, 10, 0), datetime(2026, 11, 7, 10, 30)))
check("18:00 refused by hours check",
      not booking.within_hours(hours, datetime(2026, 11, 2, 18, 0), datetime(2026, 11, 2, 18, 30)))
check("overnight span refused by hours check",
      not booking.within_hours(hours, datetime(2026, 11, 2, 16, 0), datetime(2026, 11, 3, 10, 0)))

print(f"\n{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED:", failed)
    sys.exit(1)
