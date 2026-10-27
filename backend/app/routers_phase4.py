"""Phase 4 API routes — billing (W9), subscription (W12), deadline
engine, reports (W2 complete), portal AI assistant (6.2).

Role honesty (design doc roles table): the Receptionist has "no access
to billing internals", so billing and report endpoints refuse that
role with 403; subscription is firm-admin only. Every other staff role
keeps the Phase 1 branch scoping (auth.scope_filter) on firm rows.
Portal endpoints open only the owning client's own invoices and cases.
"""
import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db
from .models import Tenant, User, Client, Case
from .models_phase2 import ActionItem
from .models_phase4 import (InvoiceTemplate, Invoice, Instalment, Payment,
                            PlatformSubscription, DeadlineRule, AIAssistantTurn,
                            INVOICE_STATUSES, PAYMENT_METHODS,
                            SUBSCRIPTION_PLANS, SUBSCRIPTION_STATUSES)
from . import auth, messaging, billing, deadline_engine, assistant, reports
from .portal_auth import current_portal_client

router = APIRouter()


def require_billing(user: User):
    if user.role == "receptionist":
        raise HTTPException(403, "Billing is not available to this role")


def require_admin(user: User):
    if user.role != "firm_admin":
        raise HTTPException(403, "Firm admin only")


def firm_name(db, tenant_id):
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    return t.name if t else ""


def staff_case(user, db, case_id):
    case = auth.scope_filter(user, db.query(Case), Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    return case


def staff_invoice(user, db, invoice_id):
    inv = auth.scope_filter(user, db.query(Invoice), Invoice).filter(
        Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv


def template_out(t):
    return {"id": t.id, "name": t.name, "line_items": json.loads(t.line_items),
            "instalments": json.loads(t.instalments), "currency": t.currency}


# ---------- invoice templates ----------
class TemplateIn(BaseModel):
    name: str
    line_items: list = []
    instalments: list = []
    currency: str = "CAD"


@router.post("/api/billing/templates")
def create_template(body: TemplateIn, user: User = Depends(auth.current_user),
                    db: Session = Depends(get_db)):
    require_billing(user)
    total = sum(int(i.get("amount_cents", 0)) for i in body.line_items)
    if total <= 0:
        raise HTTPException(400, "Template needs line items with a positive total")
    shares = sum(float(i.get("share", 0)) for i in body.instalments)
    if body.instalments and abs(shares - 1.0) > 0.01:
        raise HTTPException(400, "Instalment shares must sum to 1")
    row = InvoiceTemplate(tenant_id=user.tenant_id, name=body.name,
                          line_items=json.dumps(body.line_items),
                          instalments=json.dumps(body.instalments),
                          currency=body.currency)
    db.add(row)
    db.commit()
    db.refresh(row)
    messaging.audit(db, user.tenant_id, user.id, "invoice_template_created",
                    "invoice_template", row.id, row.name)
    return template_out(row)


@router.get("/api/billing/templates")
def list_templates(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    require_billing(user)
    rows = db.query(InvoiceTemplate).filter(
        InvoiceTemplate.tenant_id == user.tenant_id).all()
    return [template_out(r) for r in rows]


# ---------- invoices ----------
class InvoiceIn(BaseModel):
    client_id: int | None = None
    template_id: int | None = None
    line_items: list | None = None
    instalments: list | None = None
    due_date: str | None = None
    currency: str = "CAD"


@router.post("/api/cases/{case_id}/invoices")
def create_invoice(case_id: int, body: InvoiceIn, user: User = Depends(auth.current_user),
                   db: Session = Depends(get_db)):
    require_billing(user)
    case = staff_case(user, db, case_id)
    items, plan = body.line_items, body.instalments
    if body.template_id:
        tmpl = db.query(InvoiceTemplate).filter(
            InvoiceTemplate.id == body.template_id,
            InvoiceTemplate.tenant_id == user.tenant_id).first()
        if not tmpl:
            raise HTTPException(404, "Invoice template not found")
        items = items if items is not None else json.loads(tmpl.line_items)
        plan = plan if plan is not None else json.loads(tmpl.instalments)
    if not items:
        raise HTTPException(400, "Invoice needs line items (or a template)")
    total = sum(int(i.get("amount_cents", 0)) for i in items)
    if total <= 0:
        raise HTTPException(400, "Invoice total must be positive")
    if plan:
        shares = sum(float(i.get("share", 0)) for i in plan)
        if abs(shares - 1.0) > 0.01:
            raise HTTPException(400, "Instalment shares must sum to 1")
    issued = date.today()
    due = date.fromisoformat(body.due_date) if body.due_date else issued + timedelta(days=30)
    inv = Invoice(tenant_id=user.tenant_id, branch_id=case.branch_id,
                  client_id=case.client_id, case_id=case.id,
                  template_id=body.template_id, number="",
                  line_items=json.dumps(items), total_cents=total,
                  currency=body.currency, status="Draft", due_date=due)
    inv.number = billing._next_number(db, user.tenant_id, Invoice, "INV")
    db.add(inv)
    db.flush()
    for due_d, amount in billing.build_instalments(total, plan or [], issued):
        db.add(Instalment(tenant_id=user.tenant_id, invoice_id=inv.id,
                          due_date=due_d, amount_cents=amount))
    db.commit()
    messaging.audit(db, user.tenant_id, user.id, "invoice_created",
                    "invoice", inv.id, f"{inv.number} ${total / 100:.2f}")
    return billing.invoice_out(db, inv)


@router.get("/api/invoices")
def list_invoices(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    require_billing(user)
    rows = auth.scope_filter(user, db.query(Invoice), Invoice).order_by(
        Invoice.id.desc()).all()
    return [billing.invoice_out(db, r) for r in rows]


@router.get("/api/invoices/{invoice_id}")
def get_invoice(invoice_id: int, user: User = Depends(auth.current_user),
                db: Session = Depends(get_db)):
    require_billing(user)
    return billing.invoice_out(db, staff_invoice(user, db, invoice_id))


@router.post("/api/invoices/{invoice_id}/send")
def send_invoice(invoice_id: int, user: User = Depends(auth.current_user),
                 db: Session = Depends(get_db)):
    require_billing(user)
    inv = staff_invoice(user, db, invoice_id)
    if inv.status != "Draft":
        raise HTTPException(400, f"Only a Draft invoice can be sent (now {inv.status})")
    inv.status = "Sent"
    inv.sent_at = datetime.utcnow()
    db.commit()
    messaging.audit(db, user.tenant_id, user.id, "invoice_sent", "invoice", inv.id, inv.number)
    return billing.invoice_out(db, inv)


class PaymentIn(BaseModel):
    method: str
    amount_cents: int
    proof: str = ""


@router.post("/api/invoices/{invoice_id}/payments")
def add_payment(invoice_id: int, body: PaymentIn, user: User = Depends(auth.current_user),
                db: Session = Depends(get_db)):
    require_billing(user)
    if body.method not in PAYMENT_METHODS:
        raise HTTPException(400, f"Method must be one of: {', '.join(PAYMENT_METHODS)}")
    inv = staff_invoice(user, db, invoice_id)
    if inv.status == "Draft":
        raise HTTPException(400, "Send the invoice before recording a payment")
    try:
        payment, inv = billing.record_payment(db, user.tenant_id, inv, body.method,
                                              body.amount_cents, body.proof, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    messaging.audit(db, user.tenant_id, user.id, "payment_recorded",
                    "payment", payment.id,
                    f"{payment.receipt_no} {body.method} ${body.amount_cents / 100:.2f} "
                    f"on {inv.number}")
    return billing.invoice_out(db, inv)


@router.get("/api/clients/{client_id}/invoices")
def client_invoices(client_id: int, user: User = Depends(auth.current_user),
                    db: Session = Depends(get_db)):
    require_billing(user)
    client = auth.scope_filter(user, db.query(Client), Client).filter(
        Client.id == client_id).first()
    if not client:
        raise HTTPException(404, "Client not found")
    rows = db.query(Invoice).filter(Invoice.tenant_id == user.tenant_id,
                                    Invoice.client_id == client_id).order_by(
        Invoice.id.desc()).all()
    return [billing.invoice_out(db, r) for r in rows]


@router.post("/api/jobs/run-billing")
def run_billing(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    require_billing(user)
    result = billing.run_billing_job(db, user.tenant_id, firm_name(db, user.tenant_id))
    messaging.audit(db, user.tenant_id, user.id, "billing_job_run", "job", None, str(result))
    return result


# ---------- subscription (W12) ----------
def subscription_out(s):
    return {"plan": s.plan, "status": s.status, "seats": s.seats,
            "started_on": str(s.started_on) if s.started_on else None,
            "renews_on": str(s.renews_on) if s.renews_on else None, "notes": s.notes}


def _get_subscription(db, tenant_id):
    row = db.query(PlatformSubscription).filter(
        PlatformSubscription.tenant_id == tenant_id).first()
    if not row:
        row = PlatformSubscription(tenant_id=tenant_id, started_on=date.today())
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("/api/settings/subscription")
def get_subscription(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    require_admin(user)
    return subscription_out(_get_subscription(db, user.tenant_id))


class SubscriptionPatch(BaseModel):
    plan: str | None = None
    status: str | None = None
    seats: int | None = None
    renews_on: str | None = None
    notes: str | None = None


@router.patch("/api/settings/subscription")
def patch_subscription(body: SubscriptionPatch, user: User = Depends(auth.current_user),
                       db: Session = Depends(get_db)):
    require_admin(user)
    if body.plan is not None and body.plan not in SUBSCRIPTION_PLANS:
        raise HTTPException(400, f"Plan must be one of: {', '.join(SUBSCRIPTION_PLANS)}")
    if body.status is not None and body.status not in SUBSCRIPTION_STATUSES:
        raise HTTPException(400, f"Status must be one of: {', '.join(SUBSCRIPTION_STATUSES)}")
    row = _get_subscription(db, user.tenant_id)
    data = body.model_dump(exclude_unset=True)
    if "renews_on" in data and data["renews_on"]:
        data["renews_on"] = date.fromisoformat(data["renews_on"])
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    messaging.audit(db, user.tenant_id, user.id, "subscription_changed",
                    "platform_subscription", row.id, f"{row.plan}/{row.status}")
    return subscription_out(row)


# ---------- deadline engine ----------
class RuleIn(BaseModel):
    name: str
    trigger: str
    stage: str = ""
    offset_days: int
    deadline_type: str = "general"
    title: str


@router.post("/api/deadline-rules")
def create_rule(body: RuleIn, user: User = Depends(auth.current_user),
                db: Session = Depends(get_db)):
    require_admin(user)
    if body.trigger not in ("case_created", "stage_entered", "submission"):
        raise HTTPException(400, "Trigger must be case_created, stage_entered, or submission")
    if body.trigger == "stage_entered" and not body.stage:
        raise HTTPException(400, "stage_entered rules need a stage")
    row = DeadlineRule(tenant_id=user.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "trigger": row.trigger, "stage": row.stage,
            "offset_days": row.offset_days, "deadline_type": row.deadline_type,
            "title": row.title}


@router.get("/api/deadline-rules")
def list_rules(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    rows = db.query(DeadlineRule).filter(DeadlineRule.tenant_id == user.tenant_id).all()
    return [{"id": r.id, "name": r.name, "trigger": r.trigger, "stage": r.stage,
             "offset_days": r.offset_days, "deadline_type": r.deadline_type,
             "title": r.title} for r in rows]


@router.post("/api/cases/{case_id}/derive-deadlines")
def derive_deadlines(case_id: int, user: User = Depends(auth.current_user),
                     db: Session = Depends(get_db)):
    case = staff_case(user, db, case_id)
    created = deadline_engine.derive_for_case(db, user.tenant_id, case)
    messaging.audit(db, user.tenant_id, user.id, "deadlines_derived",
                    "case", case.id, f"{len(created)} derived")
    return {"created": len(created),
            "deadlines": [{"id": d.id, "title": d.title, "type": d.deadline_type,
                           "due_date": str(d.due_date)} for d in created]}


@router.post("/api/jobs/run-deadline-alerts")
def run_deadline_alerts(user: User = Depends(auth.current_user),
                        db: Session = Depends(get_db)):
    result = deadline_engine.run_deadline_alerts(
        db, user.tenant_id, firm_name(db, user.tenant_id))
    messaging.audit(db, user.tenant_id, user.id, "deadline_alerts_run", "job", None,
                    str(result))
    return result


# ---------- reports (W2 complete) ----------
@router.get("/api/reports/summary")
def reports_summary(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    require_billing(user)
    return reports.summary(db, user.tenant_id)


@router.get("/api/reports/export.xlsx")
def reports_export(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    require_billing(user)
    data = reports.export_xlsx(db, user.tenant_id)
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=reports.xlsx"})


@router.get("/api/cases/{case_id}/assistant-turns")
def case_assistant_turns(case_id: int, user: User = Depends(auth.current_user),
                         db: Session = Depends(get_db)):
    case = staff_case(user, db, case_id)
    rows = db.query(AIAssistantTurn).filter(
        AIAssistantTurn.tenant_id == user.tenant_id,
        AIAssistantTurn.case_id == case.id).order_by(AIAssistantTurn.id).all()
    return [{"id": r.id, "question": r.question, "answer": r.answer,
             "cited_fields": json.loads(r.cited_fields), "routed": r.routed,
             "at": str(r.created_at)} for r in rows]


# ---------- portal: own invoices + AI assistant ----------
@router.get("/api/portal/invoices")
def portal_invoices(client: Client = Depends(current_portal_client),
                    db: Session = Depends(get_db)):
    rows = db.query(Invoice).filter(Invoice.tenant_id == client.tenant_id,
                                    Invoice.client_id == client.id).order_by(
        Invoice.id.desc()).all()
    return [billing.invoice_out(db, r) for r in rows]


@router.get("/api/portal/invoices/{invoice_id}")
def portal_invoice(invoice_id: int, client: Client = Depends(current_portal_client),
                   db: Session = Depends(get_db)):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id,
                                   Invoice.tenant_id == client.tenant_id,
                                   Invoice.client_id == client.id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return billing.invoice_out(db, inv)


class AssistantAsk(BaseModel):
    question: str
    case_id: int | None = None


@router.post("/api/portal/assistant/ask")
def portal_assistant_ask(body: AssistantAsk, client: Client = Depends(current_portal_client),
                         db: Session = Depends(get_db)):
    case = None
    if body.case_id is not None:
        case = db.query(Case).filter(Case.id == body.case_id,
                                     Case.client_id == client.id,
                                     Case.tenant_id == client.tenant_id).first()
        if not case:
            raise HTTPException(404, "Case not found")
    text, cited, routed = assistant.answer(db, client.tenant_id, client, case, body.question)
    use_case = case
    if use_case is None:
        use_case = db.query(Case).filter(
            Case.client_id == client.id, Case.tenant_id == client.tenant_id).order_by(
            Case.id).first()
    if use_case is not None:
        db.add(AIAssistantTurn(tenant_id=client.tenant_id, case_id=use_case.id,
                               client_id=client.id, question=body.question,
                               answer=text, cited_fields=json.dumps(cited),
                               routed=routed))
        db.commit()
    return {"answer": text, "cited_fields": cited, "routed": routed}
