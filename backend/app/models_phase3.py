"""Phase 3 data model — documents and client portal. Extends Phases 1/2;
no Phase 1/2 table is altered.

Tenant rule (same as Phases 1/2): every firm-owned row carries tenant_id
and every query filters on it at the data layer. Document FILES live on
local disk under backend/data/ (gitignored), referenced from the
database — never stored as database blobs (design doc, Section 4).

Status ladder (fixed, design doc entity table): Not Started / Requested
/ Uploaded / Under Review / Approved / Rejected / Expired.
"""
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey, Boolean, func
from .db import Base

CHECKLIST_STATUSES = ["Not Started", "Requested", "Uploaded", "Under Review",
                      "Approved", "Rejected", "Expired"]

SUGGESTION_STATUSES = ["Pending", "Approved", "Rejected"]


class ChecklistItem(Base):
    """One per-stream document on a case (design doc entity table).
    person is "principal" or a dependant label; expiry_date is set by
    staff or by an approved AI suggestion, never by the AI itself."""
    __tablename__ = "checklist_items"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    document_name = Column(String, nullable=False)  # e.g. "Passport"
    person = Column(String, default="principal")
    status = Column(String, default="Not Started")
    rejection_reason = Column(String, default="")  # latest rejection, cleared on re-upload
    expiry_date = Column(Date, nullable=True)
    alerted_for_expiry = Column(Date, nullable=True)  # expiry date already alerted for
    created_at = Column(DateTime, server_default=func.now())


class DocumentVersion(Base):
    """One uploaded file for a checklist item. file_path is relative to
    backend/data/ (e.g. uploads/<tenant>/<case>/<version>_<name>).
    review_decision: pending | approved | rejected; review_reason holds
    the rejection reason (empty unless rejected)."""
    __tablename__ = "document_versions"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    checklist_item_id = Column(Integer, ForeignKey("checklist_items.id"), nullable=False)
    version_no = Column(Integer, nullable=False, default=1)
    file_path = Column(String, nullable=False)
    original_filename = Column(String, default="")
    content_type = Column(String, default="")
    size_bytes = Column(Integer, default=0)
    uploaded_by_kind = Column(String, default="staff")  # staff | client
    uploaded_by_id = Column(Integer, nullable=True)  # staff user id or client id
    review_decision = Column(String, default="pending")
    review_reason = Column(String, default="")
    reviewed_by_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class AiSuggestion(Base):
    """A proposed case-field value (or mismatch flag) from AI document
    reading (design doc Section 6.1, entity table). A proposal is NEVER
    a case value until a consultant approves it; approving a value
    suggestion writes it, approving a mismatch suggestion only
    acknowledges it. kind: value | mismatch."""
    __tablename__ = "ai_suggestions"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    document_version_id = Column(Integer, ForeignKey("document_versions.id"), nullable=False)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    kind = Column(String, default="value")  # value | mismatch
    proposed_field = Column(String, nullable=False)  # e.g. expiry_date, uci, name_mismatch
    proposed_value = Column(String, default="")
    source_excerpt = Column(String, default="")
    status = Column(String, default="Pending")
    decided_by_id = Column(Integer, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class PortalOtpCode(Base):
    """Client-portal one-time codes. Separate from the staff OtpCode
    table: the portal identifier is an email OR a phone number, and a
    portal code must never sign into the staff app (or vice versa)."""
    __tablename__ = "portal_otp_codes"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    identifier = Column(String, nullable=False)  # email or phone as typed
    code = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Integer, default=0)
