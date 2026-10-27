"""Phase 1 data model. Every firm-owned row carries tenant_id; every
query in the API filters on it (shared database, tenant-scoped rows —
the design doc default; database-per-tenant was flagged undecided and
is NOT built here). Nothing in Phase 1 sends any message anywhere.
"""
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from .db import Base


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    branches = relationship("Branch", back_populates="tenant")
    users = relationship("User", back_populates="tenant")


class Branch(Base):
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    name = Column(String, nullable=False)
    city = Column(String, default="")
    tenant = relationship("Tenant", back_populates="branches")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    email = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # firm_admin | branch_manager | consultant | filing_staff | receptionist
    tenant = relationship("Tenant", back_populates="users")


class OtpCode(Base):
    __tablename__ = "otp_codes"
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    code = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Integer, default=0)


LEAD_STAGES = ["New", "Contacted", "Qualified", "Consultation", "Converted", "Lost"]
STREAMS = ["Express Entry", "PNP", "LMIA", "Study", "Work", "Family Sponsorship"]


class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    full_name = Column(String, nullable=False)
    email = Column(String, default="")
    phone = Column(String, default="")
    source = Column(String, default="")  # Website | WhatsApp | Walk-in | Referral
    stream_of_interest = Column(String, default="")
    stage = Column(String, default="New")
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    next_follow_up = Column(Date, nullable=True)
    lost_reason = Column(String, default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    full_name = Column(String, nullable=False)
    email = Column(String, default="")
    phone = Column(String, default="")
    country_of_origin = Column(String, default="")
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)  # converted-from, no retyping
    created_at = Column(DateTime, server_default=func.now())


class Case(Base):
    __tablename__ = "cases"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    stream = Column(String, nullable=False)
    stage = Column(String, nullable=False)
    assigned_consultant_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    priority = Column(String, default="Normal")
    ircc_file_number = Column(String, default="")
    uci = Column(String, default="")
    submission_date = Column(Date, nullable=True)
    closure_reason = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())
    events = relationship("CaseStageEvent", back_populates="case", order_by="CaseStageEvent.created_at")


class CaseStageEvent(Base):
    __tablename__ = "case_stage_events"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    from_stage = Column(String, default="")
    to_stage = Column(String, nullable=False)
    note = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())
    case = relationship("Case", back_populates="events")


class StreamTemplate(Base):
    __tablename__ = "stream_templates"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    stream = Column(String, nullable=False)
    stages = Column(Text, nullable=False)  # JSON list of stage names
    checklist = Column(Text, nullable=False)  # JSON list of document names
    fee_notes = Column(Text, default="")
