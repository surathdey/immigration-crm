"""Phase 4 data model — billing, deadline engine, reports, portal AI
assistant. Extends Phases 1–3; no earlier table is altered.

Tenant rule (same as Phases 1–3): every firm-owned row carries tenant_id
and every query filters on it at the data layer.

Money is integer cents everywhere; currency defaults to CAD. Payments
are RECORDED, not charged: a card payment records the same way as
e-transfer or cash. Live Stripe charging is NOT implemented in this
build (it would need the firm's Stripe credentials in env, which this
codebase never ships); the Payment.provider field exists so a future
live-charge integration has a place to record its charge id, and it
stays empty until then.
"""
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey, Boolean, func
from .db import Base

INVOICE_STATUSES = ["Draft", "Sent", "Partially Paid", "Paid", "Overdue"]
PAYMENT_METHODS = ["card", "e-transfer", "cash"]
SUBSCRIPTION_PLANS = ["starter", "growth", "scale"]
SUBSCRIPTION_STATUSES = ["trialing", "active", "past_due", "cancelled"]


class InvoiceTemplate(Base):
    """A firm fee template (W9). line_items JSON: [{"description": str,
    "amount_cents": int}]. instalments JSON: [{"offset_days": int,
    "share": float}] — shares must sum to ~1; empty means one instalment
    due immediately. If a share list is given, the last instalment takes
    any rounding remainder so the parts always sum to the total."""
    __tablename__ = "invoice_templates"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String, nullable=False)
    line_items = Column(Text, nullable=False, default="[]")
    instalments = Column(Text, nullable=False, default="[]")
    currency = Column(String, default="CAD")
    created_at = Column(DateTime, server_default=func.now())


class Invoice(Base):
    """An invoice (W9). number is unique per tenant (INV-0001, ...).
    Status is stored; the billing job recomputes Sent/Partially Paid
    past due_date into Overdue. total_cents is the sum of line items;
    paid_cents is maintained by payment recording (never edited by hand).
    branch_id follows the case (or the client) for branch scoping."""
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=True)
    template_id = Column(Integer, ForeignKey("invoice_templates.id"), nullable=True)
    number = Column(String, nullable=False)
    line_items = Column(Text, nullable=False, default="[]")
    total_cents = Column(Integer, nullable=False, default=0)
    paid_cents = Column(Integer, nullable=False, default=0)
    currency = Column(String, default="CAD")
    status = Column(String, default="Draft")
    due_date = Column(Date, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Instalment(Base):
    """One slice of an invoice's schedule. paid_cents is maintained by
    payment allocation (oldest pending instalment first). Status:
    pending | paid | overdue (overdue is set by the billing job)."""
    __tablename__ = "instalments"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    due_date = Column(Date, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    paid_cents = Column(Integer, nullable=False, default=0)
    status = Column(String, default="pending")
    created_at = Column(DateTime, server_default=func.now())


class Payment(Base):
    """A recorded payment against an invoice (W9). receipt_no is unique
    per tenant (RCP-0001, ...). proof is a free-text reference (e.g. an
    e-transfer confirmation number) — never a card number. provider and
    provider_ref stay empty until a live-charge integration exists."""
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    method = Column(String, nullable=False)  # card | e-transfer | cash
    amount_cents = Column(Integer, nullable=False)
    proof = Column(String, default="")
    receipt_no = Column(String, nullable=False)
    provider = Column(String, default="")
    provider_ref = Column(String, default="")
    recorded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class PlatformSubscription(Base):
    """The firm's own platform subscription (W12). One row per tenant,
    created on first read. Plan-change mechanics are deliberately simple
    (plan + status + dates + seats, firm-admin only, audited): the
    design doc names subscription management but does not specify a
    proration, trial, or dunning flow, and none is invented here."""
    __tablename__ = "platform_subscriptions"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, unique=True)
    plan = Column(String, default="starter")
    status = Column(String, default="trialing")
    seats = Column(Integer, default=1)
    started_on = Column(Date, nullable=True)
    renews_on = Column(Date, nullable=True)
    notes = Column(String, default="")


class DeadlineRule(Base):
    """A derived-deadline rule (deadline engine). Trigger: case_created
    (offset from the case's creation), stage_entered (offset from the
    latest timeline entry into `stage`), submission (offset from the
    case's submission_date). Deriving is idempotent: a second run never
    creates a second open deadline with the same case, title, and type."""
    __tablename__ = "deadline_rules"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String, nullable=False)
    trigger = Column(String, nullable=False)  # case_created | stage_entered | submission
    stage = Column(String, default="")  # only for stage_entered
    offset_days = Column(Integer, nullable=False, default=0)
    deadline_type = Column(String, default="general")
    title = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class AIAssistantTurn(Base):
    """One portal-assistant exchange (design doc entity table, Section
    6.2). cited_fields JSON names the case fields the answer was drawn
    from (e.g. ["stage", "next_deadline"]); routed=True means the
    assistant declined to answer and routed the client to the
    consultant. Staff review turns from the case's staff endpoint."""
    __tablename__ = "ai_assistant_turns"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    cited_fields = Column(Text, nullable=False, default="[]")
    routed = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
