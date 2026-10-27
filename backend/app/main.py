"""Immigration Consultant CRM — Phase 1 API + Phase 2/3 routes.

Endpoints (all tenant-scoped; branch-scoped for non-admin staff):
  GET  /api/health
  POST /api/auth/request-otp, POST /api/auth/verify-otp
  GET  /api/me
  GET/POST /api/leads, GET/PATCH /api/leads/{id}, POST /api/leads/{id}/convert
  GET/POST /api/clients, GET /api/clients/{id} (360 view: client + cases + messages + consultations)
  GET/POST /api/cases, GET/PATCH /api/cases/{id} (stage move appends timeline)
  GET  /api/dashboard (core cards + action items + upcoming deadlines/consultations)
  GET  /api/templates (stream templates), GET /api/settings (firm + team)
  Phase 2 routes live in routers_phase2.py (comms settings, messages,
  event types, consultations, calendar week view + webhooks, deadlines,
  jobs, action items, AI drafts, audit log).
  Phase 3 routes live in routers_phase3.py (document checklists, review
  queue, AI suggestions, submission packet, expiry alerts, client portal).
"""
from datetime import date
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db, engine, Base
from .models import Tenant, Branch, User, Lead, Client, Case, CaseStageEvent, StreamTemplate, LEAD_STAGES
from . import auth, messaging, booking, documents
from . import models_phase2  # noqa: F401 — registers Phase 2 tables for create_all
from . import models_phase3  # noqa: F401 — registers Phase 3 tables for create_all
from .routers_phase2 import router as phase2_router
from .routers_phase3 import router as phase3_router
from .seed import seed as run_seed

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Immigration Consultant CRM — Phase 3")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(phase2_router)
app.include_router(phase3_router)
if messaging.ALLOW_TEST_HOOKS:
    from .test_hooks import router as test_hooks_router
    app.include_router(test_hooks_router)


@app.on_event("startup")
def startup():
    run_seed()


@app.get("/api/health")
def health():
    return {"status": "ok", "phase": 3}


# ---------- auth ----------
class OtpRequest(BaseModel):
    email: str


class OtpVerify(BaseModel):
    email: str
    code: str


@app.post("/api/auth/request-otp")
def request_otp(body: OtpRequest, db: Session = Depends(get_db)):
    return auth.request_otp(db, body.email)


@app.post("/api/auth/verify-otp")
def verify_otp(body: OtpVerify, db: Session = Depends(get_db)):
    return auth.verify_otp(db, body.email, body.code)


@app.get("/api/me")
def me(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role,
            "tenant": tenant.name if tenant else None, "branch_id": user.branch_id}


# ---------- helpers ----------
def lead_out(l: Lead):
    return {"id": l.id, "full_name": l.full_name, "email": l.email, "phone": l.phone,
            "source": l.source, "stream_of_interest": l.stream_of_interest, "stage": l.stage,
            "assignee_id": l.assignee_id, "next_follow_up": str(l.next_follow_up) if l.next_follow_up else None,
            "lost_reason": l.lost_reason, "notes": l.notes, "branch_id": l.branch_id}


def case_out(c: Case):
    return {"id": c.id, "client_id": c.client_id, "stream": c.stream, "stage": c.stage,
            "assigned_consultant_id": c.assigned_consultant_id, "priority": c.priority,
            "ircc_file_number": c.ircc_file_number, "uci": c.uci,
            "submission_date": str(c.submission_date) if c.submission_date else None,
            "closure_reason": c.closure_reason, "branch_id": c.branch_id,
            "events": [{"from": e.from_stage, "to": e.to_stage, "note": e.note,
                        "at": str(e.created_at)} for e in c.events]}


class LeadIn(BaseModel):
    full_name: str
    email: str = ""
    phone: str = ""
    source: str = ""
    stream_of_interest: str = ""
    stage: str = "New"
    assignee_id: int | None = None
    next_follow_up: str | None = None
    notes: str = ""


class LeadPatch(BaseModel):
    stage: str | None = None
    assignee_id: int | None = None
    next_follow_up: str | None = None
    lost_reason: str | None = None
    notes: str | None = None


class ClientIn(BaseModel):
    full_name: str
    email: str = ""
    phone: str = ""
    country_of_origin: str = ""


class CaseIn(BaseModel):
    client_id: int
    stream: str
    stage: str
    assigned_consultant_id: int | None = None
    priority: str = "Normal"


class CasePatch(BaseModel):
    stage: str | None = None
    assigned_consultant_id: int | None = None
    priority: str | None = None
    ircc_file_number: str | None = None
    uci: str | None = None
    closure_reason: str | None = None


# ---------- leads ----------
@app.get("/api/leads")
def list_leads(stage: str | None = None, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    q = auth.scope_filter(user, db.query(Lead), Lead)
    if stage:
        q = q.filter(Lead.stage == stage)
    return [lead_out(l) for l in q.order_by(Lead.id.desc()).all()]


@app.post("/api/leads")
def create_lead(body: LeadIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    if body.stage not in LEAD_STAGES:
        raise HTTPException(400, f"Unknown stage. Use one of: {', '.join(LEAD_STAGES)}")
    data = body.model_dump(exclude={"next_follow_up"})
    data["next_follow_up"] = date.fromisoformat(body.next_follow_up) if body.next_follow_up else None
    lead = Lead(tenant_id=user.tenant_id, branch_id=user.branch_id, **data)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead_out(lead)


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    lead = auth.scope_filter(user, db.query(Lead), Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead_out(lead)


@app.patch("/api/leads/{lead_id}")
def patch_lead(lead_id: int, body: LeadPatch, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    lead = auth.scope_filter(user, db.query(Lead), Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(404, "Lead not found")
    data = body.model_dump(exclude_unset=True)
    if "stage" in data and data["stage"] not in LEAD_STAGES:
        raise HTTPException(400, f"Unknown stage. Use one of: {', '.join(LEAD_STAGES)}")
    if "next_follow_up" in data and data["next_follow_up"]:
        data["next_follow_up"] = date.fromisoformat(data["next_follow_up"])
    for k, v in data.items():
        setattr(lead, k, v)
    db.commit()
    db.refresh(lead)
    return lead_out(lead)


@app.post("/api/leads/{lead_id}/convert")
def convert_lead(lead_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    """Lead -> client + case shell, copying contact/stream (no retyping)."""
    lead = auth.scope_filter(user, db.query(Lead), Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(404, "Lead not found")
    if lead.stage == "Converted":
        raise HTTPException(400, "Lead already converted")
    client = Client(tenant_id=user.tenant_id, branch_id=lead.branch_id, full_name=lead.full_name,
                    email=lead.email, phone=lead.phone, lead_id=lead.id)
    db.add(client)
    db.flush()
    template = db.query(StreamTemplate).filter(
        StreamTemplate.tenant_id == user.tenant_id,
        StreamTemplate.stream == lead.stream_of_interest).first()
    first_stage = "Consultation"
    if template:
        import json as _json
        stages = _json.loads(template.stages)
        first_stage = stages[0] if stages else first_stage
    case = Case(tenant_id=user.tenant_id, branch_id=lead.branch_id, client_id=client.id,
                stream=lead.stream_of_interest or "Express Entry", stage=first_stage,
                assigned_consultant_id=lead.assignee_id)
    db.add(case)
    db.flush()
    db.add(CaseStageEvent(case_id=case.id, from_stage="", to_stage=first_stage,
                          note="Case opened from converted lead"))
    lead.stage = "Converted"
    db.commit()
    # Phase 3 (additive): a new case starts with its stream's checklist.
    documents.init_checklist(db, user.tenant_id, case)
    return {"client_id": client.id, "case": case_out(case)}


# ---------- clients ----------
@app.get("/api/clients")
def list_clients(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    q = auth.scope_filter(user, db.query(Client), Client)
    return [{"id": c.id, "full_name": c.full_name, "email": c.email, "phone": c.phone,
             "country_of_origin": c.country_of_origin, "branch_id": c.branch_id}
            for c in q.order_by(Client.id.desc()).all()]


@app.post("/api/clients")
def create_client(body: ClientIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    client = Client(tenant_id=user.tenant_id, branch_id=user.branch_id, **body.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return {"id": client.id, "full_name": client.full_name}


@app.get("/api/clients/{client_id}")
def client_360(client_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    client = auth.scope_filter(user, db.query(Client), Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(404, "Client not found")
    cases = db.query(Case).filter(Case.client_id == client.id, Case.tenant_id == user.tenant_id).all()
    case_ids = [c.id for c in cases]
    messages = []
    if case_ids:
        from .models_phase2 import CaseMessage, Consultation
        from sqlalchemy import or_
        messages = db.query(CaseMessage).filter(
            CaseMessage.tenant_id == user.tenant_id,
            or_(CaseMessage.case_id.in_(case_ids),
                CaseMessage.client_id == client.id)).order_by(
            CaseMessage.created_at, CaseMessage.id).all()
        consultations = db.query(Consultation).filter(
            Consultation.tenant_id == user.tenant_id,
            Consultation.client_id == client.id).order_by(Consultation.starts_at).all()
    else:
        consultations = []
    return {"id": client.id, "full_name": client.full_name, "email": client.email,
            "phone": client.phone, "country_of_origin": client.country_of_origin,
            "cases": [case_out(c) for c in cases],
            "messages": [{"id": m.id, "channel": m.channel, "body": m.body,
                          "status": m.status, "at": str(m.created_at)} for m in messages],
            "consultations": [{"id": c.id, "kind": c.kind, "starts_at": str(c.starts_at),
                               "status": c.status, "source": c.source} for c in consultations]}


# ---------- cases ----------
@app.get("/api/cases")
def list_cases(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    q = auth.scope_filter(user, db.query(Case), Case)
    return [case_out(c) for c in q.order_by(Case.id.desc()).all()]


@app.post("/api/cases")
def create_case(body: CaseIn, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    case = Case(tenant_id=user.tenant_id, branch_id=user.branch_id, **body.model_dump())
    db.add(case)
    db.flush()
    db.add(CaseStageEvent(case_id=case.id, from_stage="", to_stage=body.stage, note="Case opened"))
    db.commit()
    db.refresh(case)
    # Phase 3 (additive): a new case starts with its stream's checklist.
    documents.init_checklist(db, user.tenant_id, case)
    return case_out(case)


@app.get("/api/cases/{case_id}")
def get_case(case_id: int, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    case = auth.scope_filter(user, db.query(Case), Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    return case_out(case)


@app.patch("/api/cases/{case_id}")
def patch_case(case_id: int, body: CasePatch, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    case = auth.scope_filter(user, db.query(Case), Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    data = body.model_dump(exclude_unset=True)
    if "stage" in data and data["stage"] != case.stage:
        db.add(CaseStageEvent(case_id=case.id, from_stage=case.stage, to_stage=data["stage"],
                              note="Stage moved"))
    for k, v in data.items():
        setattr(case, k, v)
    db.commit()
    db.refresh(case)
    return case_out(case)


# ---------- dashboard / templates / settings ----------
@app.get("/api/dashboard")
def dashboard(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    leads = auth.scope_filter(user, db.query(Lead), Lead).all()
    cases = auth.scope_filter(user, db.query(Case), Case).all()
    by_stage = {s: 0 for s in LEAD_STAGES}
    for l in leads:
        by_stage[l.stage] = by_stage.get(l.stage, 0) + 1
    by_stream = {}
    for c in cases:
        by_stream[c.stream] = by_stream.get(c.stream, 0) + 1
    upcoming = sorted(
        [{"type": "lead follow-up", "name": l.full_name, "date": str(l.next_follow_up)}
         for l in leads if l.next_follow_up],
        key=lambda x: x["date"])[:10]
    # Phase 2 additions (existing keys untouched).
    from .models_phase2 import ActionItem, Deadline, Consultation
    from datetime import datetime
    now = datetime.utcnow()
    action_items = db.query(ActionItem).filter(
        ActionItem.tenant_id == user.tenant_id, ActionItem.resolved == False
    ).order_by(ActionItem.id.desc()).all()
    upcoming_deadlines = db.query(Deadline).filter(
        Deadline.tenant_id == user.tenant_id, Deadline.done == False,
        Deadline.due_date >= now).order_by(Deadline.due_date).limit(10).all()
    upcoming_cons = auth.scope_filter(user, db.query(Consultation), Consultation).filter(
        Consultation.status.in_(["booked", "rescheduled"]),
        Consultation.starts_at >= now).order_by(Consultation.starts_at).limit(10).all()
    return {"active_cases": len(cases), "total_leads": len(leads),
            "leads_by_stage": by_stage, "cases_by_stream": by_stream,
            "upcoming_follow_ups": upcoming,
            "action_items": [{"id": a.id, "kind": a.kind, "title": a.title,
                              "detail": a.detail} for a in action_items],
            "upcoming_deadlines": [{"id": d.id, "case_id": d.case_id, "title": d.title,
                                    "due_date": str(d.due_date)} for d in upcoming_deadlines],
            "upcoming_consultations": [{"id": c.id, "kind": c.kind,
                                        "starts_at": str(c.starts_at),
                                        "status": c.status} for c in upcoming_cons]}


@app.get("/api/templates")
def templates(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    import json as _json
    rows = db.query(StreamTemplate).filter(StreamTemplate.tenant_id == user.tenant_id).all()
    return [{"stream": r.stream, "stages": _json.loads(r.stages),
             "checklist": _json.loads(r.checklist), "fee_notes": r.fee_notes} for r in rows]


@app.get("/api/settings")
def settings(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()
    branches = db.query(Branch).filter(Branch.tenant_id == user.tenant_id).all()
    team = db.query(User).filter(User.tenant_id == user.tenant_id).all()
    return {"firm": tenant.name if tenant else None,
            "branches": [{"id": b.id, "name": b.name, "city": b.city} for b in branches],
            "team": [{"id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role,
                      "branch_id": u.branch_id} for u in team]}
