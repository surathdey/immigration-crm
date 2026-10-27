"""Billing helpers (W9): numbering, totals, instalment allocation,
overdue recompute, and overdue reminders. All money is integer cents.

Status honesty: an invoice's stored status is recomputed only by
record_payment() and run_billing_job() — the same job-driven pattern
Phase 3 uses for document expiry. Reading an invoice never rewrites it.
"""
import json
from datetime import date, datetime, timedelta

from .models import Client, Case
from .models_phase2 import ActionItem, ReminderLog
from .models_phase4 import Invoice, Instalment, Payment


def _next_number(db, tenant_id, model, prefix, field="number"):
    """Per-tenant sequential number: PREFIX-0001, PREFIX-0002, ..."""
    rows = db.query(model).filter(model.tenant_id == tenant_id).all()
    taken = set()
    for r in rows:
        val = getattr(r, field)
        if val and val.startswith(prefix + "-"):
            try:
                taken.add(int(val.split("-")[-1]))
            except ValueError:
                pass
    n = 1
    while n in taken:
        n += 1
    return f"{prefix}-{n:04d}"


def build_instalments(total_cents, plan, issued_on):
    """Split total_cents by plan [{"offset_days", "share"}]. Empty plan
    means a single instalment due on issue. The last instalment takes
    any rounding remainder so parts always sum to the total."""
    if not plan:
        return [(issued_on, total_cents)]
    parts = []
    acc = 0
    for i, leg in enumerate(plan):
        if i == len(plan) - 1:
            amount = total_cents - acc
        else:
            amount = round(total_cents * float(leg.get("share", 0)))
            acc += amount
        parts.append((issued_on + timedelta(days=int(leg.get("offset_days", 0))), amount))
    return parts


def invoice_out(db, inv):
    inst = db.query(Instalment).filter(Instalment.invoice_id == inv.id).order_by(
        Instalment.due_date, Instalment.id).all()
    pays = db.query(Payment).filter(Payment.invoice_id == inv.id).order_by(Payment.id).all()
    return {"id": inv.id, "number": inv.number, "client_id": inv.client_id,
            "case_id": inv.case_id, "template_id": inv.template_id,
            "line_items": json.loads(inv.line_items), "total_cents": inv.total_cents,
            "paid_cents": inv.paid_cents, "balance_cents": inv.total_cents - inv.paid_cents,
            "currency": inv.currency, "status": inv.status,
            "due_date": str(inv.due_date) if inv.due_date else None,
            "sent_at": str(inv.sent_at) if inv.sent_at else None,
            "paid_at": str(inv.paid_at) if inv.paid_at else None,
            "branch_id": inv.branch_id,
            "instalments": [{"id": i.id, "due_date": str(i.due_date),
                             "amount_cents": i.amount_cents, "paid_cents": i.paid_cents,
                             "status": i.status} for i in inst],
            "payments": [{"id": p.id, "method": p.method, "amount_cents": p.amount_cents,
                          "proof": p.proof, "receipt_no": p.receipt_no,
                          "at": str(p.created_at)} for p in pays]}


def record_payment(db, tenant_id, inv, method, amount_cents, proof, recorded_by_id):
    """Record a payment, allocate oldest-pending-instalment-first, and
    refresh the invoice status. Returns (payment, invoice). Raises
    ValueError on an overpayment or a non-positive amount."""
    if amount_cents <= 0:
        raise ValueError("Payment amount must be positive")
    if inv.paid_cents + amount_cents > inv.total_cents:
        raise ValueError("Payment exceeds the invoice balance")
    payment = Payment(tenant_id=tenant_id, invoice_id=inv.id, method=method,
                      amount_cents=amount_cents, proof=proof or "",
                      receipt_no=_next_number(db, tenant_id, Payment, "RCP", "receipt_no"),
                      recorded_by_id=recorded_by_id)
    db.add(payment)
    db.flush()
    remaining = amount_cents
    for inst in db.query(Instalment).filter(
            Instalment.invoice_id == inv.id).order_by(
            Instalment.due_date, Instalment.id).all():
        if remaining <= 0:
            break
        room = inst.amount_cents - inst.paid_cents
        if room <= 0:
            continue
        take = min(room, remaining)
        inst.paid_cents += take
        remaining -= take
        if inst.paid_cents >= inst.amount_cents:
            inst.status = "paid"
    inv.paid_cents += amount_cents
    if inv.paid_cents >= inv.total_cents:
        inv.status = "Paid"
        inv.paid_at = datetime.utcnow()
    elif inv.status in ("Sent", "Overdue"):
        inv.status = "Partially Paid"
    db.commit()
    db.refresh(inv)
    return payment, inv


def run_billing_job(db, tenant_id, firm_name, today=None):
    """Recompute overdue statuses and send one overdue reminder per
    invoice per day (log mode by default, via the Phase 2 adapters).
    Returns {"overdue": n, "reminded": m}. Idempotent within a day:
    a reminder is logged in ReminderLog under window
    "invoice-overdue:<invoice_id>:<date>" and never repeated."""
    from . import messaging  # deferred: messaging imports models_phase2 only
    today = today or date.today()
    overdue = reminded = 0
    for inv in db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(["Sent", "Partially Paid"])).all():
        if inv.due_date and inv.due_date < today and inv.paid_cents < inv.total_cents:
            inv.status = "Overdue"
            overdue += 1
    db.commit()
    for inv in db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id, Invoice.status == "Overdue").all():
        window = f"invoice-overdue:{inv.id}:{today.isoformat()}"
        if db.query(ReminderLog).filter(
                ReminderLog.tenant_id == tenant_id,
                ReminderLog.window_key == window).first():
            continue
        client = db.query(Client).filter(Client.id == inv.client_id).first()
        case = db.query(Case).filter(Case.id == inv.case_id).first() if inv.case_id else None
        balance = inv.total_cents - inv.paid_cents
        body = (f"Hi {client.full_name if client else 'there'}, invoice {inv.number} "
                f"for ${balance / 100:.2f} is now overdue. Please contact the firm "
                f"to arrange payment.")
        sent = False
        if client and client.phone:
            try:
                messaging.send_sms(db, tenant_id, firm_name, client.phone, body,
                                   case_id=inv.case_id, template_key="payment_reminder",
                                   source="system", client_id=inv.client_id)
                sent = True
            except ValueError:
                pass
        if client and client.email:
            try:
                messaging.send_email(db, tenant_id, firm_name, client.email,
                                     f"Invoice {inv.number} overdue", body,
                                     case_id=inv.case_id, template_key="payment_reminder",
                                     source="system", client_id=inv.client_id)
                sent = True
            except ValueError:
                pass
        db.add(ReminderLog(tenant_id=tenant_id, channel="sms",
                           window_key=window, recipient=client.phone if client else "",
                           status="would_send" if sent else "failed"))
        if sent:
            reminded += 1
    db.commit()
    return {"overdue": overdue, "reminded": reminded}
