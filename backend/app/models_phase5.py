"""Phase 5 data model — automation. Extends Phases 1–4; no earlier table
is altered.

- Retainer agreements: generated from a firm template (or the standard
  template when the firm has none), signed in-app — no third-party
  e-signature provider exists here — and every signature is audited.
- IRCC forms: structured form data mapped from case data, versioned;
  each consultant correction is a new version. These are NOT official
  IRCC PDFs: official templates are not available here, so the system
  produces structured data plus a printable rendering, and says so.
- Document chasing: one ChaseLog row per (item, channel) per chase run;
  chasing is idempotent within CHASE_INTERVAL_DAYS and stops when the
  item arrives (Uploaded / Under Review / Approved).
- Pre-check results: stored on the lead as a pre-check ONLY, with the
  disclaimer on every result. A pre-check is never an eligibility
  decision and never promises an outcome.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, func
from .db import Base

MISSING_STATUSES = ["Not Started", "Requested", "Rejected", "Expired"]
ARRIVED_STATUSES = ["Uploaded", "Under Review", "Approved"]
CHASE_INTERVAL_DAYS = 7

DISCLAIMER = ("Not legal advice — this is a triage aid only; the consultant decides. "
              "It is not an eligibility decision and promises no outcome.")

IRCC_FORM_CODES = ["IMM 0008", "IMM 5669", "IMM 5257", "IMM 1294", "IMM 5476"]


class RetainerTemplate(Base):
    """A firm-supplied retainer template (design doc Table 4: the standard
    template is drafted for the firm's lawyer to review and is replaced
    by the firm's own template when supplied). Generation uses the firm's
    latest custom template when one exists, else the standard text."""
    __tablename__ = "retainer_templates"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String, nullable=False, default="Firm retainer")
    body = Column(Text, nullable=False)  # {client_name} {firm_name} {stream} {fee_notes} {date}
    is_custom = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class RetainerAgreement(Base):
    """One generated retainer for a case. status: draft | signed | voided.
    Signing is in-app: the signer types their name (method
    "in-app-typed"), the timestamp is recorded, and messaging.audit
    writes the audit row. There is no third-party e-signature provider
    in this build, and the README says so plainly."""
    __tablename__ = "retainer_agreements"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("retainer_templates.id"), nullable=True)
    body = Column(Text, nullable=False)  # rendered text at generation time
    status = Column(String, default="draft")
    signer_name = Column(String, default="")
    method = Column(String, default="")  # in-app-typed
    signed_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class IrccForm(Base):
    """One version of one IRCC form for a case. data is JSON text mapped
    from case/client data at generation, then corrected by the
    consultant — each correction is a NEW row (version_no + 1), so the
    history is never overwritten. status: draft | corrected.
    These renderings are NOT official IRCC PDFs."""
    __tablename__ = "ircc_forms"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    form_code = Column(String, nullable=False)  # e.g. IMM 0008
    version_no = Column(Integer, nullable=False, default=1)
    data = Column(Text, nullable=False, default="{}")  # JSON {field_key: value}
    status = Column(String, default="draft")
    corrected_by_id = Column(Integer, nullable=True)
    note = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())


class ChaseLog(Base):
    """One chase reminder for one checklist item on one channel.
    Idempotency key is (checklist_item_id, channel, recent window):
    run_chasing skips an item already chased on that channel within
    CHASE_INTERVAL_DAYS, and never chases an arrived item."""
    __tablename__ = "chase_logs"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    checklist_item_id = Column(Integer, ForeignKey("checklist_items.id"), nullable=False)
    channel = Column(String, nullable=False)  # sms | email
    message_status = Column(String, default="")  # adapter status, e.g. would_send
    chased_at = Column(DateTime, server_default=func.now())


class PreCheckResult(Base):
    """One eligibility pre-check result (design doc Section 6.4). answers
    and ranked are JSON text. The disclaimer is stored WITH the result
    so every view of it carries the disclaimer. lead_id is null when
    the prospect gave no contact details; when they did, the result is
    linked to their lead as a pre-check only — never as a decision."""
    __tablename__ = "precheck_results"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    answers = Column(Text, nullable=False, default="{}")
    ranked = Column(Text, nullable=False, default="[]")  # [{stream, score, reasons[]}]
    disclaimer = Column(Text, nullable=False, default=DISCLAIMER)
    created_at = Column(DateTime, server_default=func.now())
