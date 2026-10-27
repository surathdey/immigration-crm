"""Phase 3 API routes — documents and client portal (W7, W10, W11,
Section 6.1). Mounted by main.py.

Scoping: staff access always goes through the case (tenant + branch
via auth.scope_filter), so a checklist item, version, or suggestion is
reachable only through a case the staff member's firm (and branch)
owns. Portal access goes through the owning client only — a portal
token opens nothing but that client's own cases and documents.
"""
import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db
from .models import Tenant, User, Client, Case
from .models_phase2 import CaseMessage, Deadline
from .models_phase3 import ChecklistItem, DocumentVersion, AiSuggestion, CHECKLIST_STATUSES
from . import auth, messaging, documents, portal_auth

router = APIRouter()


# ---------- helpers ----------
def staff_case(user, db, case_id):
    case = auth.scope_filter(user, db.query(Case), Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    return case


def item_via_case(user, db, item_id):
    item = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "Checklist item not found")
    staff_case(user, db, item.case_id)  # tenant + branch scoping
    return item


def portal_case(client, db, case_id):
    case = db.query(Case).filter(Case.id == case_id,
                                 Case.client_id == client.id,
                                 Case.tenant_id == client.tenant_id).first()
    if not case:
        raise HTTPException(404, "Case not found")
    return case


def firm_name(db, tenant_id):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    return tenant.name if tenant else ""


def client_of(db, case):
    return db.query(Client).filter(Client.id == case.client_id).first()


def suggestion_out(s):
    return {"id": s.id, "document_version_id": s.document_version_id, "case_id": s.case_id,
            "kind": s.kind, "proposed_field": s.proposed_field,
            "proposed_value": s.proposed_value, "source_excerpt": s.source_excerpt,
            "status": s.status, "decided_by_id": s.decided_by_id,
            "decided_at": str(s.decided_at) if s.decided_at else None}


def version_out(db, v):
    sugs = db.query(AiSuggestion).filter(
        AiSuggestion.document_version_id == v.id).order_by(AiSuggestion.id).all()
    return {"id": v.id, "checklist_item_id": v.checklist_item_id, "version_no": v.version_no,
            "original_filename": v.original_filename, "content_type": v.content_type,
            "size_bytes": v.size_bytes, "uploaded_by_kind": v.uploaded_by_kind,
            "review_decision": v.review_decision, "review_reason": v.review_reason,
            "at": str(v.created_at), "suggestions": [suggestion_out(s) for s in sugs]}


def item_out(db, item):
    latest = documents.latest_version(db, item.id)
    pending = db.query(AiSuggestion).filter(
        AiSuggestion.case_id == item.case_id, AiSuggestion.status == "Pending").count() \
        if latest else 0
    return {"id": item.id, "case_id": item.case_id, "document_name": item.document_name,
            "person": item.person, "status": item.status,
            "rejection_reason": item.rejection_reason,
            "expiry_date": str(item.expiry_date) if item.expiry_date else None,
            "latest_version": version_out(db, latest) if latest else None,
            "pending_suggestions": pending}


def notify_review(db, user, case, kind, detail):
    """Review-decision notification via the Phase 2 log-mode adapters
    (both channels the client has). Never blocks the review action."""
    client = client_of(db, case)
    if not client:
        return
    if kind == "approved":
        sms = (f"Hi {client.full_name}, your document was approved for your "
               f"{case.stream} case. Thank you.")
        subj, body = "A document on your case was approved", sms
    elif kind == "rejected":
        sms = (f"Hi {client.full_name}, a document for your {case.stream} case "
               f"needs attention: {detail}. Please re-upload it.")
        subj, body = (f"A document on your case needs attention",
                      f"Hi {client.full_name},\n\nA document for your {case.stream} case "
                      f"needs attention: {detail}\n\nPlease re-upload it.")
    else:  # requested
        sms = (f"Hi {client.full_name}, for your {case.stream} case we need "
               f"the following document: {detail}. Please upload it in the portal.")
        subj, body = (f"Document needed for your {case.stream} case",
                      f"Hi {client.full_name},\n\nFor your {case.stream} case we need "
                      f"the following document: {detail}.\n\nPlease upload it in the portal.")
    documents.notify_client(db, user.tenant_id, firm_name(db, user.tenant_id),
                            case, client, sms, subj, body)


# ---------- staff: checklist ----------
@router.get("/api/cases/{case_id}/checklist")
def get_checklist(case_id: int, user: User = Depends(auth.current_user),
                  db: Session = Depends(get_db)):
    case = staff_case(user, db, case_id)
    items = db.query(ChecklistItem).filter(
        ChecklistItem.tenant_id == user.tenant_id,
        ChecklistItem.case_id == case.id).order_by(ChecklistItem.id).all()
    return [item_out(db, it) for it in items]


@router.post("/api/cases/{case_id}/checklist/init")
def init_checklist(case_id: int, user: User = Depends(auth.current_user),
                   db: Session = Depends(get_db)):
    case = staff_case(user, db, case_id)
    items = documents.init_checklist(db, user.tenant_id, case)
    return [item_out(db, it) for it in items]


class ItemPatch(BaseModel):
    expiry_date: str | None = None
    person: str | None = None
    document_name: str | None = None


@router.patch("/api/checklist-items/{item_id}")
def patch_item(item_id: int, body: ItemPatch, user: User = Depends(auth.current_user),
               db: Session = Depends(get_db)):
    item = item_via_case(user, db, item_id)
    data = body.model_dump(exclude_unset=True)
    if "expiry_date" in data:
        if data["expiry_date"]:
            try:
                item.expiry_date = date.fromisoformat(data["expiry_date"])
            except ValueError:
                raise HTTPException(400, "expiry_date must be YYYY-MM-DD")
        else:
            item.expiry_date = None
    if "person" in data and data["person"]:
        item.person = data["person"]
    if "document_name" in data and data["document_name"]:
        item.document_name = data["document_name"]
    db.commit()
    db.refresh(item)
    return item_out(db, item)


@router.post("/api/checklist-items/{item_id}/request")
def request_item(item_id: int, user: User = Depends(auth.current_user),
                 db: Session = Depends(get_db)):
    item = item_via_case(user, db, item_id)
    if item.status not in ("Not Started", "Rejected", "Expired"):
        raise HTTPException(400, f"Cannot request a document in status {item.status}")
    item.status = "Requested"
    db.commit()
    case = staff_case(user, db, item.case_id)
    notify_review(db, user, case, "requested", item.document_name)
    messaging.audit(db, user.tenant_id, user.id, "document_requested",
                    "checklist_item", item.id, item.document_name)
    db.commit()
    return item_out(db, item)


@router.post("/api/checklist-items/{item_id}/upload")
async def upload_item(item_id: int, file: UploadFile = File(...),
                      user: User = Depends(auth.current_user),
                      db: Session = Depends(get_db)):
    item = item_via_case(user, db, item_id)
    content = await file.read()
    try:
        version = documents.save_upload(db, user.tenant_id, item, content,
                                        file.filename or "upload",
                                        file.content_type or "", "staff", user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    case = staff_case(user, db, item.case_id)
    client = client_of(db, case)
    documents.generate_suggestions(db, user.tenant_id, case, client, version, content)
    messaging.audit(db, user.tenant_id, user.id, "document_uploaded",
                    "document_version", version.id,
                    f"{item.document_name} v{version.version_no} (staff)")
    db.commit()
    return version_out(db, version)


@router.post("/api/checklist-items/{item_id}/start-review")
def start_review(item_id: int, user: User = Depends(auth.current_user),
                 db: Session = Depends(get_db)):
    item = item_via_case(user, db, item_id)
    if item.status != "Uploaded":
        raise HTTPException(400, f"Cannot start review in status {item.status}")
    item.status = "Under Review"
    db.commit()
    return item_out(db, item)


@router.post("/api/checklist-items/{item_id}/approve")
def approve_item(item_id: int, user: User = Depends(auth.current_user),
                 db: Session = Depends(get_db)):
    item = item_via_case(user, db, item_id)
    if item.status not in ("Uploaded", "Under Review"):
        raise HTTPException(400, f"Cannot approve a document in status {item.status}")
    latest = documents.latest_version(db, item.id)
    if latest:
        latest.review_decision = "approved"
        latest.review_reason = ""
        latest.reviewed_by_id = user.id
    item.status = "Approved"
    item.rejection_reason = ""
    db.commit()
    case = staff_case(user, db, item.case_id)
    notify_review(db, user, case, "approved", item.document_name)
    messaging.audit(db, user.tenant_id, user.id, "document_approved",
                    "checklist_item", item.id, item.document_name)
    db.commit()
    return item_out(db, item)


class RejectIn(BaseModel):
    reason: str


@router.post("/api/checklist-items/{item_id}/reject")
def reject_item(item_id: int, body: RejectIn, user: User = Depends(auth.current_user),
                db: Session = Depends(get_db)):
    item = item_via_case(user, db, item_id)
    if item.status not in ("Uploaded", "Under Review"):
        raise HTTPException(400, f"Cannot reject a document in status {item.status}")
    if not (body.reason or "").strip():
        raise HTTPException(400, "A rejection reason is required")
    latest = documents.latest_version(db, item.id)
    if latest:
        latest.review_decision = "rejected"
        latest.review_reason = body.reason.strip()
        latest.reviewed_by_id = user.id
    item.status = "Rejected"
    item.rejection_reason = body.reason.strip()
    db.commit()
    case = staff_case(user, db, item.case_id)
    notify_review(db, user, case, "rejected", body.reason.strip())
    messaging.audit(db, user.tenant_id, user.id, "document_rejected",
                    "checklist_item", item.id,
                    f"{item.document_name}: {body.reason.strip()}")
    db.commit()
    return item_out(db, item)


# ---------- staff: review queue, versions, packet, expiry ----------
@router.get("/api/review-queue")
def review_queue(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    rows = (db.query(ChecklistItem, Case, Client)
            .join(Case, Case.id == ChecklistItem.case_id)
            .join(Client, Client.id == Case.client_id)
            .filter(ChecklistItem.tenant_id == user.tenant_id,
                    ChecklistItem.status.in_(["Uploaded", "Under Review"])))
    if user.role != "firm_admin" and user.branch_id:
        rows = rows.filter(Case.branch_id == user.branch_id)
    rows = rows.order_by(ChecklistItem.id).all()
    out = []
    for item, case, client in rows:
        d = item_out(db, item)
        d["case_stream"] = case.stream
        d["client_name"] = client.full_name
        out.append(d)
    return out


@router.get("/api/checklist-items/{item_id}/versions")
def item_versions(item_id: int, user: User = Depends(auth.current_user),
                  db: Session = Depends(get_db)):
    item = item_via_case(user, db, item_id)
    versions = db.query(DocumentVersion).filter(
        DocumentVersion.checklist_item_id == item.id).order_by(DocumentVersion.id).all()
    return [version_out(db, v) for v in versions]


@router.get("/api/documents/versions/{version_id}/download")
def download_version(version_id: int, user: User = Depends(auth.current_user),
                     db: Session = Depends(get_db)):
    version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
    if not version:
        raise HTTPException(404, "Document not found")
    item_via_case(user, db, version.checklist_item_id)
    full = documents.file_full_path(version)
    import os
    if not os.path.exists(full):
        raise HTTPException(404, "File not on disk")
    return FileResponse(full, filename=version.original_filename or "document")


@router.get("/api/cases/{case_id}/packet")
def submission_packet(case_id: int, user: User = Depends(auth.current_user),
                      db: Session = Depends(get_db)):
    case = staff_case(user, db, case_id)
    buf, filename = documents.build_packet(db, user.tenant_id, case)
    return Response(content=buf.read(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/api/documents/expiring")
def expiring_docs(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    horizon = date.today() + timedelta(days=30)
    rows = (db.query(ChecklistItem, Case, Client)
            .join(Case, Case.id == ChecklistItem.case_id)
            .join(Client, Client.id == Case.client_id)
            .filter(ChecklistItem.tenant_id == user.tenant_id,
                    ChecklistItem.expiry_date.isnot(None),
                    ChecklistItem.expiry_date <= horizon,
                    ChecklistItem.status != "Expired"))
    if user.role != "firm_admin" and user.branch_id:
        rows = rows.filter(Case.branch_id == user.branch_id)
    rows = rows.order_by(ChecklistItem.expiry_date).all()
    out = []
    for item, case, client in rows:
        d = item_out(db, item)
        d["case_stream"] = case.stream
        d["client_name"] = client.full_name
        out.append(d)
    return out


@router.post("/api/jobs/run-expiry-alerts")
def run_expiry_alerts(user: User = Depends(auth.current_user),
                      db: Session = Depends(get_db)):
    return documents.run_expiry_alerts(db, user.tenant_id, firm_name(db, user.tenant_id))


# ---------- staff: AI suggestions ----------
@router.post("/api/suggestions/{sug_id}/approve")
def approve_suggestion(sug_id: int, user: User = Depends(auth.current_user),
                       db: Session = Depends(get_db)):
    sug = db.query(AiSuggestion).filter(AiSuggestion.id == sug_id).first()
    if not sug:
        raise HTTPException(404, "Suggestion not found")
    staff_case(user, db, sug.case_id)  # tenant + branch scoping
    try:
        documents.apply_suggestion(db, user.tenant_id, sug, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return suggestion_out(sug)


@router.post("/api/suggestions/{sug_id}/reject")
def reject_suggestion(sug_id: int, user: User = Depends(auth.current_user),
                      db: Session = Depends(get_db)):
    sug = db.query(AiSuggestion).filter(AiSuggestion.id == sug_id).first()
    if not sug:
        raise HTTPException(404, "Suggestion not found")
    staff_case(user, db, sug.case_id)
    if sug.status != "Pending":
        raise HTTPException(400, f"Suggestion is {sug.status}, not open for decision.")
    sug.status = "Rejected"
    sug.decided_by_id = user.id
    sug.decided_at = datetime.utcnow()
    messaging.audit(db, user.tenant_id, user.id, "suggestion_decided", "ai_suggestion",
                    sug.id, f"{sug.kind}:{sug.proposed_field} rejected (dismissed)")
    db.commit()
    return suggestion_out(sug)


# ---------- portal (W10/W11) ----------
class PortalOtpRequest(BaseModel):
    identifier: str
    firm_slug: str | None = None


class PortalOtpVerify(BaseModel):
    identifier: str
    firm_slug: str | None = None
    code: str


@router.post("/api/portal/request-otp")
def portal_request_otp(body: PortalOtpRequest, db: Session = Depends(get_db)):
    return portal_auth.request_portal_otp(db, body.identifier, body.firm_slug)


@router.post("/api/portal/verify-otp")
def portal_verify_otp(body: PortalOtpVerify, db: Session = Depends(get_db)):
    return portal_auth.verify_portal_otp(db, body.identifier, body.firm_slug, body.code)


@router.get("/api/portal/me")
def portal_me(client: Client = Depends(portal_auth.current_portal_client),
              db: Session = Depends(get_db)):
    cases = db.query(Case).filter(Case.client_id == client.id,
                                  Case.tenant_id == client.tenant_id).all()
    return {"id": client.id, "full_name": client.full_name, "email": client.email,
            "cases": [{"id": c.id, "stream": c.stream, "stage": c.stage} for c in cases]}


def portal_case_out(db, client, case):
    items = db.query(ChecklistItem).filter(
        ChecklistItem.case_id == case.id,
        ChecklistItem.tenant_id == client.tenant_id).order_by(ChecklistItem.id).all()
    counts = {s: 0 for s in CHECKLIST_STATUSES}
    for it in items:
        counts[it.status] = counts.get(it.status, 0) + 1
    upcoming = db.query(Deadline).filter(
        Deadline.tenant_id == client.tenant_id, Deadline.case_id == case.id,
        Deadline.done == False).order_by(Deadline.due_date).first()
    return {"id": case.id, "stream": case.stream, "stage": case.stage,
            "priority": case.priority,
            "checklist_counts": counts,
            "next_deadline": ({"title": upcoming.title,
                               "due_date": str(upcoming.due_date)} if upcoming else None)}


@router.get("/api/portal/cases")
def portal_cases(client: Client = Depends(portal_auth.current_portal_client),
                 db: Session = Depends(get_db)):
    cases = db.query(Case).filter(Case.client_id == client.id,
                                  Case.tenant_id == client.tenant_id).all()
    return [portal_case_out(db, client, c) for c in cases]


@router.get("/api/portal/cases/{case_id}")
def portal_case_detail(case_id: int, client: Client = Depends(portal_auth.current_portal_client),
                       db: Session = Depends(get_db)):
    case = portal_case(client, db, case_id)
    items = db.query(ChecklistItem).filter(
        ChecklistItem.case_id == case.id,
        ChecklistItem.tenant_id == client.tenant_id).order_by(ChecklistItem.id).all()
    messages = db.query(CaseMessage).filter(
        CaseMessage.tenant_id == client.tenant_id,
        CaseMessage.case_id == case.id).order_by(
        CaseMessage.created_at, CaseMessage.id).all()
    return {"case": portal_case_out(db, client, case),
            "checklist": [item_out(db, it) for it in items],
            "messages": [{"channel": m.channel, "body": m.body, "status": m.status,
                          "at": str(m.created_at)} for m in messages]}


@router.post("/api/portal/cases/{case_id}/checklist/{item_id}/upload")
async def portal_upload(case_id: int, item_id: int, file: UploadFile = File(...),
                        client: Client = Depends(portal_auth.current_portal_client),
                        db: Session = Depends(get_db)):
    case = portal_case(client, db, case_id)
    item = db.query(ChecklistItem).filter(
        ChecklistItem.id == item_id, ChecklistItem.case_id == case.id,
        ChecklistItem.tenant_id == client.tenant_id).first()
    if not item:
        raise HTTPException(404, "Checklist item not found")
    content = await file.read()
    try:
        version = documents.save_upload(db, client.tenant_id, item, content,
                                        file.filename or "upload",
                                        file.content_type or "", "client", client.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    documents.generate_suggestions(db, client.tenant_id, case, client, version, content)
    messaging.audit(db, client.tenant_id, None, "document_uploaded",
                    "document_version", version.id,
                    f"{item.document_name} v{version.version_no} (client portal)")
    db.commit()
    return version_out(db, version)


@router.get("/api/portal/cases/{case_id}/documents/{version_id}/download")
def portal_download(case_id: int, version_id: int,
                    client: Client = Depends(portal_auth.current_portal_client),
                    db: Session = Depends(get_db)):
    portal_case(client, db, case_id)
    version = db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
    if not version:
        raise HTTPException(404, "Document not found")
    item = db.query(ChecklistItem).filter(
        ChecklistItem.id == version.checklist_item_id,
        ChecklistItem.case_id == case_id,
        ChecklistItem.tenant_id == client.tenant_id).first()
    if not item:
        raise HTTPException(404, "Document not found")
    import os
    full = documents.file_full_path(version)
    if not os.path.exists(full):
        raise HTTPException(404, "File not on disk")
    return FileResponse(full, filename=version.original_filename or "document")
