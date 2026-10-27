"""Portal AI client assistant (design doc Section 6.2) — template
adapter, the same pattern as the Phase 2/3 AI adapters: no external
model call, no firm data leaves the firm, and the answer is built
ONLY from the signed-in client's own case data.

Scope (design doc Table 4): only questions answerable from the
client's own case data — stage, next step, deadline, outstanding
items, appointments, invoices. Everything else routes to the
consultant: the assistant says so plainly and never invents a fact,
never gives a legal answer, never promises a timeline or an outcome,
and never discusses another client's file. When the asked-for data
does not exist (no deadline, no invoice), it says so plainly instead
of inventing one.
"""
import json

from .models import Case
from .models_phase2 import Deadline, Consultation
from .models_phase3 import ChecklistItem
from .models_phase4 import Invoice

# Any of these words means the question is outside the assistant's
# scope, however it is phrased: law, eligibility, strategy, outcome.
ROUTE_WORDS = ["eligible", "eligibility", "chance", "guarantee", "legal",
               "lawyer", "law ", "should i", "strategy", "will i get",
               "will my", "approve me", "refusal risk", "appeal chance"]

CATEGORIES = [
    ("deadline", ["deadline", "due", "expir", "when is", "by when"]),
    ("documents", ["document", "missing", "outstanding", "needed", "upload",
                   "checklist", "still need"]),
    ("appointment", ["appointment", "consultation", "meeting", "booked",
                     "schedule"]),
    ("invoice", ["invoice", "payment", "pay", "owe", "balance", "bill",
                 "receipt"]),
    ("stage", ["status", "stage", "happening", "progress", "where is",
               "next step", "what happens next", "update"]),
]


def _next_stage(db, tenant_id, case):
    from .models import StreamTemplate
    tmpl = db.query(StreamTemplate).filter(
        StreamTemplate.tenant_id == tenant_id,
        StreamTemplate.stream == case.stream).first()
    if not tmpl:
        return None
    stages = json.loads(tmpl.stages)
    try:
        i = stages.index(case.stage)
        return stages[i + 1] if i + 1 < len(stages) else None
    except ValueError:
        return None


def answer(db, tenant_id, client, case, question):
    """Returns (answer_text, cited_fields_list, routed_bool). The caller
    owns the tenant/client scoping: `case` must already be verified as
    the client's own, or None (then the client's first case is used)."""
    from datetime import datetime
    q = question.lower()
    if any(w in q for w in ROUTE_WORDS):
        return ("I can't answer questions about eligibility, legal advice, "
                "or likely outcomes — those are for your consultant to decide. "
                "I've flagged this for them; please message the firm through "
                "the portal and they will reply.", [], True)
    if case is None:
        cases = db.query(Case).filter(
            Case.client_id == client.id, Case.tenant_id == tenant_id).order_by(
            Case.id).all()
        if not cases:
            return ("You don't have a case on file yet. Please message the "
                    "firm through the portal and they will help.", [], False)
        case = cases[0]
    category = None
    for name, words in CATEGORIES:
        if any(w in q for w in words):
            category = name
            break
    if category is None:
        return ("I can only answer from your own case file — its stage, next "
                "step, deadlines, outstanding documents, appointments, and "
                "invoices. For anything else, please message your consultant "
                "through the portal.", [], True)
    if category == "stage":
        nxt = _next_stage(db, tenant_id, case)
        text = (f"Your {case.stream} case is at the “{case.stage}” stage."
                + (f" The next step is “{nxt}”." if nxt else
                   " This is the final stage of the process."))
        return text, ["stage", "next_stage"], False
    if category == "deadline":
        dl = db.query(Deadline).filter(
            Deadline.tenant_id == tenant_id, Deadline.case_id == case.id,
            Deadline.done == False).order_by(Deadline.due_date).first()
        if not dl:
            return ("You have no upcoming deadline on this case right now.",
                    ["next_deadline"], False)
        return (f"Your next deadline is “{dl.title}”, due "
                f"{dl.due_date.date()}.", ["next_deadline"], False)
    if category == "documents":
        items = db.query(ChecklistItem).filter(
            ChecklistItem.tenant_id == tenant_id, ChecklistItem.case_id == case.id,
            ChecklistItem.status.in_(["Not Started", "Requested", "Rejected"])).all()
        if not items:
            return ("All documents on this case are uploaded or approved — "
                    "nothing is outstanding right now.",
                    ["outstanding_items"], False)
        names = ", ".join(sorted({i.document_name for i in items}))
        return (f"Still outstanding on this case: {names}. Upload them in "
                f"the portal documents section.",
                ["outstanding_items"], False)
    if category == "appointment":
        now = datetime.utcnow()
        con = db.query(Consultation).filter(
            Consultation.tenant_id == tenant_id, Consultation.client_id == client.id,
            Consultation.status.in_(["booked", "rescheduled"]),
            Consultation.starts_at >= now).order_by(Consultation.starts_at).first()
        if not con:
            return ("You have no upcoming appointment booked right now.",
                    ["next_appointment"], False)
        return (f"Your next appointment is a {con.kind} on "
                f"{con.starts_at.strftime('%Y-%m-%d %H:%M')} (status: {con.status}).",
                ["next_appointment"], False)
    if category == "invoice":
        invs = db.query(Invoice).filter(
            Invoice.tenant_id == tenant_id, Invoice.client_id == client.id).all()
        open_invs = [i for i in invs if i.total_cents > i.paid_cents]
        if not open_invs:
            return ("You have no outstanding invoice balance right now.",
                    ["open_invoices"], False)
        total = sum(i.total_cents - i.paid_cents for i in open_invs) / 100
        names = ", ".join(i.number for i in open_invs)
        return (f"You have an outstanding balance of ${total:.2f} across "
                f"invoice(s): {names}.", ["open_invoices"], False)
    return ("I couldn't match that to your case file — please message your "
            "consultant through the portal.", [], True)
