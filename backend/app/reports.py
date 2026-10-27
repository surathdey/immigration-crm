"""Full dashboard reports (W2 complete) + spreadsheet export.

Definitions, stated plainly because the design doc names the reports
but not their formulas:
- Approval rate by stream: among cases that reached the "Decision"
  stage, the share whose closure_reason is "Approved" over those whose
  closure_reason is "Approved" or "Refused". Other closure reasons are
  excluded; streams with no decided cases report null, never 0%.
- Days per stage: from CaseStageEvent timestamps — each event's stage
  runs until the next event (or now, for the current stage) — averaged
  per (stream, stage).
- Workload: open cases (no closure_reason) per assigned consultant,
  plus an "Unassigned" bucket.
- Revenue by month: payments received, grouped by payment month; and
  invoices issued, grouped by invoice month. Money is cents.
"""
import io
import json
from collections import defaultdict
from datetime import datetime

from .models import Case, CaseStageEvent, User
from .models_phase4 import Invoice, Payment


def _decided(cases):
    return [c for c in cases if c.stage == "Decision"]


def approval_rate_by_stream(db, tenant_id):
    out = {}
    cases = db.query(Case).filter(Case.tenant_id == tenant_id).all()
    by_stream = defaultdict(list)
    for c in _decided(cases):
        by_stream[c.stream].append(c)
    for stream, rows in by_stream.items():
        approved = sum(1 for c in rows if (c.closure_reason or "").strip().lower() == "approved")
        refused = sum(1 for c in rows if (c.closure_reason or "").strip().lower() in ("refused", "refusal"))
        denom = approved + refused
        out[stream] = {"decided": len(rows), "approved": approved, "refused": refused,
                       "rate": (approved / denom) if denom else None}
    return out


def days_per_stage(db, tenant_id):
    """Average days in each stage, per stream."""
    cases = db.query(Case).filter(Case.tenant_id == tenant_id).all()
    totals = defaultdict(lambda: [0.0, 0])
    now = datetime.utcnow()
    for case in cases:
        events = db.query(CaseStageEvent).filter(
            CaseStageEvent.case_id == case.id).order_by(
            CaseStageEvent.created_at, CaseStageEvent.id).all()
        for i, ev in enumerate(events):
            nxt = events[i + 1].created_at if i + 1 < len(events) else now
            start = ev.created_at or now
            days = max(0.0, (nxt - start).total_seconds() / 86400.0)
            key = (case.stream, ev.to_stage)
            totals[key][0] += days
            totals[key][1] += 1
    return [{"stream": s, "stage": st, "avg_days": round(total / n, 2), "cases": n}
            for (s, st), (total, n) in sorted(totals.items())]


def workload(db, tenant_id):
    cases = db.query(Case).filter(
        Case.tenant_id == tenant_id,
        (Case.closure_reason == "") | (Case.closure_reason.is_(None))).all()
    users = {u.id: u.full_name for u in db.query(User).filter(
        User.tenant_id == tenant_id).all()}
    counts = defaultdict(int)
    for c in cases:
        counts[users.get(c.assigned_consultant_id, "Unassigned")] += 1
    return [{"assignee": name, "open_cases": n} for name, n in sorted(counts.items())]


def revenue_by_month(db, tenant_id):
    received = defaultdict(lambda: {"cents": 0, "count": 0})
    for p in db.query(Payment).filter(Payment.tenant_id == tenant_id).all():
        key = (p.created_at or datetime.utcnow()).strftime("%Y-%m")
        received[key]["cents"] += p.amount_cents
        received[key]["count"] += 1
    issued = defaultdict(lambda: {"cents": 0, "count": 0})
    for inv in db.query(Invoice).filter(Invoice.tenant_id == tenant_id).all():
        key = (inv.created_at or datetime.utcnow()).strftime("%Y-%m")
        issued[key]["cents"] += inv.total_cents
        issued[key]["count"] += 1
    months = sorted(set(received) | set(issued))
    return [{"month": m,
             "received_cents": received[m]["cents"], "payments": received[m]["count"],
             "invoiced_cents": issued[m]["cents"], "invoices": issued[m]["count"]}
            for m in months]


def summary(db, tenant_id):
    return {"approval_rate_by_stream": approval_rate_by_stream(db, tenant_id),
            "days_per_stage": days_per_stage(db, tenant_id),
            "workload": workload(db, tenant_id),
            "revenue_by_month": revenue_by_month(db, tenant_id)}


def export_xlsx(db, tenant_id):
    """Spreadsheet export for the accountant: one workbook, one sheet
    per report plus the underlying invoice/payment rows."""
    from openpyxl import Workbook
    wb = Workbook()
    rep = summary(db, tenant_id)
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Report", "Value"])
    for stream, row in rep["approval_rate_by_stream"].items():
        ws.append([f"Approval rate — {stream}",
                   row["rate"] if row["rate"] is not None else "n/a"])
    ws2 = wb.create_sheet("Revenue by month")
    ws2.append(["Month", "Received (cents)", "Payments", "Invoiced (cents)", "Invoices"])
    for r in rep["revenue_by_month"]:
        ws2.append([r["month"], r["received_cents"], r["payments"],
                    r["invoiced_cents"], r["invoices"]])
    ws3 = wb.create_sheet("Workload")
    ws3.append(["Assignee", "Open cases"])
    for w in rep["workload"]:
        ws3.append([w["assignee"], w["open_cases"]])
    ws4 = wb.create_sheet("Stage durations")
    ws4.append(["Stream", "Stage", "Avg days", "Cases"])
    for d in rep["days_per_stage"]:
        ws4.append([d["stream"], d["stage"], d["avg_days"], d["cases"]])
    ws5 = wb.create_sheet("Invoices")
    ws5.append(["Number", "Client id", "Case id", "Total (cents)", "Paid (cents)", "Status"])
    for inv in db.query(Invoice).filter(Invoice.tenant_id == tenant_id).all():
        ws5.append([inv.number, inv.client_id, inv.case_id, inv.total_cents,
                    inv.paid_cents, inv.status])
    ws6 = wb.create_sheet("Payments")
    ws6.append(["Receipt", "Invoice id", "Method", "Amount (cents)", "Proof"])
    for p in db.query(Payment).filter(Payment.tenant_id == tenant_id).all():
        ws6.append([p.receipt_no, p.invoice_id, p.method, p.amount_cents, p.proof])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
