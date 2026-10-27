"""Seed data. Idempotent: re-running it never duplicates the demo firm.
Demo firm is fictional; demo people are fictional. Test login (with
DEV_OTP=true): request an OTP for admin@demo.example and sign in with
the returned code.
"""
import json
from datetime import date, timedelta

from .db import SessionLocal, engine, Base
from .models import Tenant, Branch, User, Lead, Client, Case, CaseStageEvent, StreamTemplate

STREAM_STAGES = {
    "Express Entry": ["Consultation", "Documents", "Profile Created", "ITA Received", "Submitted", "Decision"],
    "PNP": ["Consultation", "Documents", "Nomination Applied", "Nominated", "Submitted", "Decision"],
    "LMIA": ["Consultation", "Employer Documents", "LMIA Applied", "LMIA Approved", "Work Permit", "Decision"],
    "Study": ["Consultation", "Documents", "Admission", "Study Permit Applied", "Approved", "Decision"],
    "Work": ["Consultation", "Documents", "Permit Applied", "Approved", "Decision"],
    "Family Sponsorship": ["Consultation", "Documents", "Sponsorship Applied", "In Process", "Decision"],
}
STREAM_CHECKLISTS = {
    "Express Entry": ["Passport", "IELTS result", "ECA report", "Police clearance", "Proof of funds"],
    "PNP": ["Passport", "IELTS result", "ECA report", "Employment letter", "Police clearance"],
    "LMIA": ["Passport", "Job offer", "Employer documents", "Resume"],
    "Study": ["Passport", "Admission letter", "IELTS result", "Proof of funds", "Statement of purpose"],
    "Work": ["Passport", "Job offer", "Resume", "Police clearance"],
    "Family Sponsorship": ["Passport", "Marriage certificate", "Sponsor documents", "Police clearance"],
}


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Tenant).filter(Tenant.slug == "demo-firm").first():
            return "already seeded"
        tenant = Tenant(name="Maple Leaf Immigration (Demo)", slug="demo-firm")
        db.add(tenant)
        db.flush()
        toronto = Branch(tenant_id=tenant.id, name="Toronto", city="Toronto")
        mississauga = Branch(tenant_id=tenant.id, name="Mississauga", city="Mississauga")
        db.add_all([toronto, mississauga])
        db.flush()
        admin = User(tenant_id=tenant.id, branch_id=toronto.id, email="admin@demo.example",
                     full_name="Demo Admin", role="firm_admin")
        consultant = User(tenant_id=tenant.id, branch_id=toronto.id, email="consultant@demo.example",
                          full_name="Priya Sharma", role="consultant")
        filing = User(tenant_id=tenant.id, branch_id=mississauga.id, email="filing@demo.example",
                      full_name="Rohan Mehta", role="filing_staff")
        db.add_all([admin, consultant, filing])
        db.flush()
        for stream, stages in STREAM_STAGES.items():
            db.add(StreamTemplate(tenant_id=tenant.id, stream=stream,
                                  stages=json.dumps(stages),
                                  checklist=json.dumps(STREAM_CHECKLISTS[stream]),
                                  fee_notes="Fee schedule set by the firm per stream."))
        db.flush()
        today = date.today()
        leads = [
            Lead(tenant_id=tenant.id, branch_id=toronto.id, full_name="Aisha Khan",
                 email="aisha@example.com", phone="+1 416 555 0101", source="Website",
                 stream_of_interest="Express Entry", stage="New", assignee_id=consultant.id,
                 next_follow_up=today + timedelta(days=2)),
            Lead(tenant_id=tenant.id, branch_id=toronto.id, full_name="David Okafor",
                 email="david@example.com", phone="+1 416 555 0102", source="WhatsApp",
                 stream_of_interest="Study", stage="Qualified", assignee_id=consultant.id,
                 next_follow_up=today + timedelta(days=5)),
            Lead(tenant_id=tenant.id, branch_id=mississauga.id, full_name="Maria Lopez",
                 email="maria@example.com", phone="+1 905 555 0103", source="Walk-in",
                 stream_of_interest="Family Sponsorship", stage="Consultation", assignee_id=filing.id,
                 next_follow_up=today + timedelta(days=1)),
            Lead(tenant_id=tenant.id, branch_id=toronto.id, full_name="Chen Wei",
                 email="chen@example.com", phone="+1 416 555 0104", source="Referral",
                 stream_of_interest="Work", stage="Lost", lost_reason="Chose another firm"),
        ]
        db.add_all(leads)
        db.flush()
        client = Client(tenant_id=tenant.id, branch_id=toronto.id, full_name="Aisha Khan",
                        email="aisha@example.com", phone="+1 416 555 0101",
                        country_of_origin="Pakistan", lead_id=leads[0].id)
        db.add(client)
        db.flush()
        leads[0].stage = "Converted"
        case = Case(tenant_id=tenant.id, branch_id=toronto.id, client_id=client.id,
                    stream="Express Entry", stage="Documents", assigned_consultant_id=consultant.id,
                    priority="Normal", ircc_file_number="E123456789", uci="1234-5678")
        db.add(case)
        db.flush()
        db.add(CaseStageEvent(case_id=case.id, from_stage="", to_stage="Consultation",
                              note="Case opened from converted lead"))
        db.add(CaseStageEvent(case_id=case.id, from_stage="Consultation", to_stage="Documents",
                              note="Consultation done; documents requested"))
        case2 = Case(tenant_id=tenant.id, branch_id=mississauga.id, client_id=client.id,
                     stream="Study", stage="Admission", assigned_consultant_id=filing.id,
                     priority="High")
        db.add(case2)
        db.commit()
        return "seeded"
    finally:
        db.close()


if __name__ == "__main__":
    print(seed())
