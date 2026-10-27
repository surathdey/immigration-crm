"""Phase 5 API routes — automation (retainers, IRCC forms, document
chasing, eligibility pre-check; design doc Phase 5 row + Section 6.4).
Mounted by main.py.

Scoping: staff access always goes through the case (tenant + branch
via auth.scope_filter), so a retainer, form, or chase log is reachable
only through a case the staff member's firm (and branch) owns. The
public pre-check resolves its firm by firm_slug (same precedent as the
Calendly webhook) and never sees another firm's data. Receptionists
cannot write Phase 5 objects; retainer templates are firm-admin only.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db
from .models import Tenant, User, Client, Case, Lead
from .models_phase5 import (RetainerTemplate, RetainerAgreement, IrccForm,
                            ChaseLog, PreCheckResult, DISCLAIMER, IRCC_FORM_CODES)
from . import auth, automation

router = APIRouter()


# ---------- helpers ----------
def require_staff_write(user: User):
    if user.role == "receptionist":
        raise HTTPException(403, "This role cannot change automation records")


def require_admin(user: User):
    if user.role != "firm_admin":
        raise HTTPException(403, "Firm admin only")


def staff_case(user, db, case_id):
    case = auth.scope_filter(user, db.query(Case), Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    return case


def firm_name(db, tenant_id):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    return tenant.name if tenant else ""


def client_of(db, case):
    return db.query(Client).filter(Client.id == case.client_id).first()


def retainer_out(r):
    return {"id": r.id, "case_id": r.case_id, "template_id": r.template_id,
            "body": r.body, "status": r.status, "signer_name": r.signer_name,
            "method": r.method, "signed_at": str(r.signed_at) if r.signed_at else None,
            "at": str(r.created_at)}


def form_out(f):
    return {"id": f.id, "case_id": f.case_id, "form_code": f.form_code,
            "version_no": f.version_no, "data": json.loads(f.data),
            "status": f.status, "note": f.note, "at": str(f.created_at)}


# ---------- retainer templates ----------
class TemplateIn(BaseModel):
    name: str = "Firm retainer"
    body: str


@router.post("/api/retainer-templates")
def create_retainer_template(body: TemplateIn, user: User = Depends(auth.current_user),
                             db: Session = Depends(get_db)):
    require_admin(user)
    if not body.body.strip():
        raise HTTPException(400, "Template body is required")
    row = RetainerTemplate(tenant_id=user.tenant_id, name=body.name, body=body.body, is_custom=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "is_custom": True}


@router.get("/api/retainer-templates")
def list_retainer_templates(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    rows = db.query(RetainerTemplate).filter(
        RetainerTemplate.tenant_id == user.tenant_id).order_by(RetainerTemplate.id.desc()).all()
    return [{"id": r.id, "name": r.name, "body": r.body, "is_custom": r.is_custom} for r in rows]


# ---------- retainers ----------
class RetainerIn(BaseModel):
    template_id: int | None = None


@router.post("/api/cases/{case_id}/retainers")
def generate_retainer(case_id: int, body: RetainerIn, user: User = Depends(auth.current_user),
                      db: Session = Depends(get_db)):
    require_staff_write(user)
    case = staff_case(user, db, case_id)
    client = client_of(db, case)
    if body.template_id:
        template = db.query(RetainerTemplate).filter(
            RetainerTemplate.id == body.template_id,
            RetainerTemplate.tenant_id == user.tenant_id).first()
        if not template:
            raise HTTPException(404, "Retainer template not found")
        ctx = automation.case_context(client, firm_name(db, user.tenant_id), case)
        rendered = automation.render_retainer(template.body, ctx)
        agreement = RetainerAgreement(tenant_id=user.tenant_id, case_id=case.id,
                                      template_id=template.id, body=rendered,
                                      status="draft", created_by_id=user.id)
        db.add(agreement)
        db.commit()
        db.refresh(agreement)
        return retainer_out(agreement)
    agreement = automation.generate_retainer(db, user.tenant_id, case, client,
                                             firm_name(db, user.tenant_id), user.id)
    return retainer_out(agreement)


@router.get("/api/cases/{case_id}/retainers")
def list_retainers(case_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    case = staff_case(user, db, case_id)
    rows = db.query(RetainerAgreement).filter(
        RetainerAgreement.tenant_id == user.tenant_id,
        RetainerAgreement.case_id == case.id).order_by(RetainerAgreement.id).all()
    return [retainer_out(r) for r in rows]


def _retainer_via_case(user, db, retainer_id):
    row = db.query(RetainerAgreement).filter(RetainerAgreement.id == retainer_id).first()
    if not row:
        raise HTTPException(404, "Retainer not found")
    staff_case(user, db, row.case_id)  # tenant + branch scoping
    return row


@router.get("/api/retainers/{retainer_id}")
def get_retainer(retainer_id: int, user: User = Depends(auth.current_user),
                 db: Session = Depends(get_db)):
    return retainer_out(_retainer_via_case(user, db, retainer_id))


class SignIn(BaseModel):
    signer_name: str


@router.post("/api/retainers/{retainer_id}/sign")
def sign_retainer(retainer_id: int, body: SignIn, user: User = Depends(auth.current_user),
                  db: Session = Depends(get_db)):
    require_staff_write(user)
    row = _retainer_via_case(user, db, retainer_id)
    try:
        signed = automation.sign_retainer(db, user.tenant_id, row, body.signer_name, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return retainer_out(signed)


# ---------- IRCC forms ----------
class FormIn(BaseModel):
    form_code: str


@router.post("/api/cases/{case_id}/ircc-forms")
def generate_ircc_form(case_id: int, body: FormIn, user: User = Depends(auth.current_user),
                       db: Session = Depends(get_db)):
    require_staff_write(user)
    case = staff_case(user, db, case_id)
    client = client_of(db, case)
    try:
        form = automation.generate_form(db, user.tenant_id, case, client,
                                        firm_name(db, user.tenant_id), body.form_code, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return form_out(form)


@router.get("/api/cases/{case_id}/ircc-forms")
def list_ircc_forms(case_id: int, user: User = Depends(auth.current_user),
                    db: Session = Depends(get_db)):
    case = staff_case(user, db, case_id)
    rows = db.query(IrccForm).filter(
        IrccForm.tenant_id == user.tenant_id, IrccForm.case_id == case.id
    ).order_by(IrccForm.form_code, IrccForm.version_no).all()
    return [form_out(f) for f in rows]


def _form_via_case(user, db, form_id):
    row = db.query(IrccForm).filter(IrccForm.id == form_id).first()
    if not row:
        raise HTTPException(404, "Form not found")
    staff_case(user, db, row.case_id)  # tenant + branch scoping
    return row


@router.get("/api/ircc-forms/{form_id}")
def get_ircc_form(form_id: int, user: User = Depends(auth.current_user),
                  db: Session = Depends(get_db)):
    row = _form_via_case(user, db, form_id)
    out = form_out(row)
    out["rendering"] = automation.render_form_text(row)
    out["available_codes"] = IRCC_FORM_CODES
    return out


class CorrectIn(BaseModel):
    corrections: dict
    note: str = ""


@router.patch("/api/ircc-forms/{form_id}")
def correct_ircc_form(form_id: int, body: CorrectIn, user: User = Depends(auth.current_user),
                      db: Session = Depends(get_db)):
    require_staff_write(user)
    row = _form_via_case(user, db, form_id)
    try:
        new = automation.correct_form(db, row, body.corrections, user.id, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return form_out(new)


# ---------- document chasing ----------
@router.post("/api/jobs/run-chasing")
def run_chasing_job(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    require_staff_write(user)
    return automation.run_chasing(db, user.tenant_id, firm_name(db, user.tenant_id))


@router.get("/api/cases/{case_id}/chases")
def list_chases(case_id: int, user: User = Depends(auth.current_user),
                db: Session = Depends(get_db)):
    case = staff_case(user, db, case_id)
    rows = db.query(ChaseLog).filter(
        ChaseLog.tenant_id == user.tenant_id, ChaseLog.case_id == case.id
    ).order_by(ChaseLog.id.desc()).all()
    return [{"id": c.id, "checklist_item_id": c.checklist_item_id, "channel": c.channel,
             "message_status": c.message_status, "at": str(c.chased_at)} for c in rows]


# ---------- eligibility pre-check (6.4) ----------
class PreCheckIn(BaseModel):
    firm_slug: str = ""
    answers: dict = {}
    full_name: str = ""
    email: str = ""
    phone: str = ""


def _attach_lead(db, tenant_id, full_name, email, phone):
    """Find-or-create the prospect's lead so the result arrives on the
    lead as a pre-check only. Returns the lead id or None."""
    if not email:
        return None
    lead = db.query(Lead).filter(Lead.tenant_id == tenant_id, Lead.email == email).first()
    if not lead:
        lead = Lead(tenant_id=tenant_id, full_name=full_name or email, email=email,
                    phone=phone, source="Pre-check")
        db.add(lead)
        db.commit()
        db.refresh(lead)
    return lead.id


@router.post("/api/precheck")
def public_precheck(body: PreCheckIn, db: Session = Depends(get_db)):
    """Public prospect endpoint: the firm is resolved by firm_slug (the
    Calendly precedent). No other firm's data is reachable through it."""
    tenant = db.query(Tenant).filter(Tenant.slug == body.firm_slug).first()
    if not tenant:
        raise HTTPException(404, "Firm not found")
    lead_id = _attach_lead(db, tenant.id, body.full_name, body.email, body.phone)
    result = automation.run_precheck(db, tenant.id, body.answers, lead_id)
    out = automation.precheck_out(result)
    out["disclaimer_notice"] = DISCLAIMER
    return out


@router.post("/api/staff/precheck")
def staff_precheck(body: PreCheckIn, user: User = Depends(auth.current_user),
                   db: Session = Depends(get_db)):
    """Staff-run pre-check inside the firm's tenant scope (used by the
    staff app's Pre-check page and by tests)."""
    lead_id = None
    if body.email:
        lead_id = _attach_lead(db, user.tenant_id, body.full_name, body.email, body.phone)
    result = automation.run_precheck(db, user.tenant_id, body.answers, lead_id)
    return automation.precheck_out(result)


@router.get("/api/leads/{lead_id}/prechecks")
def lead_prechecks(lead_id: int, user: User = Depends(auth.current_user),
                   db: Session = Depends(get_db)):
    lead = auth.scope_filter(user, db.query(Lead), Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(404, "Lead not found")
    rows = db.query(PreCheckResult).filter(
        PreCheckResult.tenant_id == user.tenant_id,
        PreCheckResult.lead_id == lead.id).order_by(PreCheckResult.id).all()
    return [automation.precheck_out(r) for r in rows]
