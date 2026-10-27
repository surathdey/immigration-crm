"""Phase 5 automation — retainers, IRCC form autofill, document chasing,
eligibility pre-check (design doc Phase 5 row + Section 6.4).

Honesty notes, enforced here and stated in the README:
- E-signatures are captured in-app (typed name + timestamp + audit
  row). There is no third-party e-signature provider in this build.
- IRCC "forms" are structured data + a printable rendering, NOT
  official IRCC PDFs. Official templates are not available here.
- The system NEVER submits anything to IRCC on its own. There is no
  submission path in this module, or anywhere else in the codebase:
  submission is a human act by the licensed consultant, recorded
  afterwards (design doc Section 8).
"""
import json
from datetime import datetime, timedelta

from .models import StreamTemplate
from .models_phase3 import ChecklistItem
from .models_phase5 import (RetainerTemplate, RetainerAgreement, IrccForm,
                            ChaseLog, PreCheckResult, MISSING_STATUSES,
                            CHASE_INTERVAL_DAYS, DISCLAIMER, IRCC_FORM_CODES)
from . import messaging

STANDARD_RETAINER_TEMPLATE = """RETAINER AGREEMENT (standard template — for the firm's lawyer to review)

Firm: {firm_name}
Client: {client_name}
Stream: {stream}
Date: {date}

The client retains the firm to advise and act on the above immigration
stream. {fee_notes}

The client confirms the information supplied to the firm is true and
complete, and that the consultant — not this agreement — decides
strategy, eligibility, and any submission. No outcome is promised.

Signed in-app by the client (typed name) or by staff on the client's
instruction, with the signature timestamp and audit record kept on file.
"""

# field key -> label. Values come from the case/client context; anything
# the case does not hold stays blank for the consultant to correct —
# the generator never invents a case fact.
FORM_DEFS = {
    "IMM 0008": ("Generic Application Form for Canada", [
        ("applicant_name", "Applicant full name"),
        ("country_of_origin", "Country of origin"),
        ("stream", "Program / stream"),
        ("uci", "UCI (if known)"),
        ("ircc_file_number", "IRCC file number (if known)"),
        ("email", "Contact email"),
        ("phone", "Contact phone"),
    ]),
    "IMM 5669": ("Schedule A — Background / Declaration", [
        ("applicant_name", "Applicant full name"),
        ("country_of_origin", "Country of origin"),
        ("stream", "Program / stream"),
        ("uci", "UCI (if known)"),
    ]),
    "IMM 5257": ("Application for Visitor Visa (Temporary Resident Visa)", [
        ("applicant_name", "Applicant full name"),
        ("country_of_origin", "Country of origin"),
        ("purpose", "Purpose of visit (stream)"),
        ("email", "Contact email"),
        ("phone", "Contact phone"),
    ]),
    "IMM 1294": ("Application for Work Permit Made Outside of Canada", [
        ("applicant_name", "Applicant full name"),
        ("country_of_origin", "Country of origin"),
        ("stream", "Program / stream"),
        ("uci", "UCI (if known)"),
        ("ircc_file_number", "IRCC file number (if known)"),
    ]),
    "IMM 5476": ("Use of a Representative", [
        ("applicant_name", "Applicant full name"),
        ("representative", "Representative (firm)"),
        ("stream", "Program / stream"),
        ("ircc_file_number", "IRCC file number (if known)"),
    ]),
}


def case_context(client, firm_name, case):
    return {
        "applicant_name": client.full_name if client else "",
        "client_name": client.full_name if client else "",
        "country_of_origin": client.country_of_origin if client else "",
        "email": client.email if client else "",
        "phone": client.phone if client else "",
        "stream": case.stream,
        "uci": case.uci or "",
        "ircc_file_number": case.ircc_file_number or "",
        "representative": firm_name,
        "firm_name": firm_name,
        "fee_notes": "",
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "purpose": case.stream,
    }


# ---------- retainers ----------
def render_retainer(body, ctx):
    out = body
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", v or "")
    return out


def generate_retainer(db, tenant_id, case, client, firm_name, user_id):
    """Render from the firm's latest custom template when one exists,
    else the standard template. Returns the draft agreement."""
    template = db.query(RetainerTemplate).filter(
        RetainerTemplate.tenant_id == tenant_id,
        RetainerTemplate.is_custom == True).order_by(
        RetainerTemplate.id.desc()).first()
    ctx = case_context(client, firm_name, case)
    template_obj = db.query(StreamTemplate).filter(
        StreamTemplate.tenant_id == tenant_id,
        StreamTemplate.stream == case.stream).first()
    if template_obj:
        ctx["fee_notes"] = template_obj.fee_notes or ""
    if template:
        body = render_retainer(template.body, ctx)
        template_id = template.id
    else:
        body = render_retainer(STANDARD_RETAINER_TEMPLATE, ctx)
        template_id = None
    agreement = RetainerAgreement(
        tenant_id=tenant_id, case_id=case.id, template_id=template_id,
        body=body, status="draft", created_by_id=user_id)
    db.add(agreement)
    db.commit()
    db.refresh(agreement)
    return agreement


def sign_retainer(db, tenant_id, agreement, signer_name, user_id):
    """In-app signature: typed name + timestamp + audit row. Only a
    draft can be signed; a signed agreement is never re-signed."""
    if agreement.status != "draft":
        raise ValueError(f"Retainer is {agreement.status}, not a draft")
    if not signer_name or not signer_name.strip():
        raise ValueError("Signer name is required")
    agreement.status = "signed"
    agreement.signer_name = signer_name.strip()
    agreement.method = "in-app-typed"
    agreement.signed_at = datetime.utcnow()
    messaging.audit(db, tenant_id, user_id, "retainer_signed",
                    "retainer_agreement", agreement.id,
                    f"Retainer for case #{agreement.case_id} signed in-app by {signer_name.strip()}")
    db.commit()
    db.refresh(agreement)
    return agreement


def retainer_signed(db, tenant_id, case_id):
    return db.query(RetainerAgreement).filter(
        RetainerAgreement.tenant_id == tenant_id,
        RetainerAgreement.case_id == case_id,
        RetainerAgreement.status == "signed").first() is not None


def opening_stage(db, tenant_id, case):
    """First stage of the case's stream template; 'Consultation' when
    the stream has no template. The retainer gate guards leaving it."""
    template = db.query(StreamTemplate).filter(
        StreamTemplate.tenant_id == tenant_id,
        StreamTemplate.stream == case.stream).first()
    if template:
        try:
            stages = json.loads(template.stages)
            if stages:
                return stages[0]
        except (ValueError, TypeError):
            pass
    return "Consultation"


# ---------- IRCC forms ----------
def generate_form(db, tenant_id, case, client, firm_name, form_code, user_id):
    if form_code not in FORM_DEFS:
        raise ValueError(f"Unknown IRCC form code. Use one of: {', '.join(IRCC_FORM_CODES)}")
    title, fields = FORM_DEFS[form_code]
    ctx = case_context(client, firm_name, case)
    data = {key: ctx.get(key, "") for key, _label in fields}
    latest = db.query(IrccForm).filter(
        IrccForm.tenant_id == tenant_id, IrccForm.case_id == case.id,
        IrccForm.form_code == form_code).order_by(IrccForm.version_no.desc()).first()
    form = IrccForm(tenant_id=tenant_id, case_id=case.id, form_code=form_code,
                    version_no=(latest.version_no + 1) if latest else 1,
                    data=json.dumps(data), status="draft",
                    corrected_by_id=user_id, note="Generated from case data")
    db.add(form)
    db.commit()
    db.refresh(form)
    return form


def correct_form(db, form, corrections, user_id, note=""):
    """Consultant review gate: a correction is a NEW version; the old
    version is never overwritten. Only known fields may be corrected."""
    _title, fields = FORM_DEFS[form.form_code]
    known = {key for key, _label in fields}
    unknown = [k for k in corrections if k not in known]
    if unknown:
        raise ValueError(f"Unknown fields for {form.form_code}: {', '.join(unknown)}")
    data = json.loads(form.data)
    data.update({k: v for k, v in corrections.items()})
    new = IrccForm(tenant_id=form.tenant_id, case_id=form.case_id,
                   form_code=form.form_code, version_no=form.version_no + 1,
                   data=json.dumps(data), status="corrected",
                   corrected_by_id=user_id, note=note or "Consultant correction")
    db.add(new)
    db.commit()
    db.refresh(new)
    return new


def render_form_text(form):
    """Printable rendering of one form version. Plainly NOT an official
    IRCC PDF — structured data rendered for review and print."""
    title, fields = FORM_DEFS[form.form_code]
    data = json.loads(form.data)
    lines = [
        f"{form.form_code} — {title}",
        f"Version {form.version_no} · Status: {form.status}",
        "NOT AN OFFICIAL IRCC PDF — structured data rendered for consultant",
        "review and print. This system never submits anything to IRCC.",
        "",
    ]
    for key, label in fields:
        lines.append(f"{label}: {data.get(key, '')}")
    return "\n".join(lines)


# ---------- document chasing ----------
def run_chasing(db, tenant_id, firm_name):
    """Chase every missing checklist item once per channel per interval.
    Log mode (Phase 2 default) records 'would send' — nothing is
    delivered. An item that arrives stops being chased by definition:
    it is no longer in MISSING_STATUSES. Returns counts."""
    from .models import Client
    cutoff = datetime.utcnow() - timedelta(days=CHASE_INTERVAL_DAYS)
    chased, skipped = 0, 0
    items = db.query(ChecklistItem).filter(
        ChecklistItem.tenant_id == tenant_id,
        ChecklistItem.status.in_(MISSING_STATUSES)).order_by(ChecklistItem.id).all()
    for item in items:
        # Resolve the client through the case (items carry case_id).
        from .models import Case
        case = db.query(Case).filter(Case.id == item.case_id).first()
        client = db.query(Client).filter(Client.id == case.client_id).first() if case else None
        if not client:
            continue
        body = (f"Reminder: your document '{item.document_name}' for case "
                f"#{item.case_id} is still missing. Please upload it when ready.")
        for channel, address in (("sms", client.phone), ("email", client.email)):
            if not address:
                continue
            recent = db.query(ChaseLog).filter(
                ChaseLog.checklist_item_id == item.id, ChaseLog.channel == channel,
                ChaseLog.chased_at >= cutoff).first()
            if recent:
                skipped += 1
                continue
            if channel == "sms":
                msg = messaging.send_sms(db, tenant_id, firm_name, address, body,
                                         case_id=item.case_id, client_id=client.id,
                                         template_key="document_chase", source="chasing")
            else:
                msg = messaging.send_email(db, tenant_id, firm_name, address,
                                           "Document still missing", body,
                                           case_id=item.case_id, client_id=client.id,
                                           template_key="document_chase", source="chasing")
            db.add(ChaseLog(tenant_id=tenant_id, case_id=item.case_id,
                            checklist_item_id=item.id, channel=channel,
                            message_status=msg.status))
            chased += 1
    db.commit()
    return {"chased": chased, "skipped_recent": skipped}


# ---------- eligibility pre-check (6.4) ----------
def score_precheck(answers):
    """Rules-based triage only. Returns ranked streams with plain-language
    reasons. Scores are never an eligibility decision and the wording
    never promises an outcome — streams are 'to explore'."""
    edu = (answers.get("education") or "").lower()
    lang = answers.get("language_clb") or 0
    try:
        lang = int(lang)
    except (ValueError, TypeError):
        lang = 0
    work = answers.get("work_years") or 0
    try:
        work = int(work)
    except (ValueError, TypeError):
        work = 0
    age = (answers.get("age_band") or "").lower()
    job = bool(answers.get("job_offer"))
    family = bool(answers.get("family_in_canada"))
    adm = bool(answers.get("admission_letter"))
    funds = bool(answers.get("proof_of_funds"))
    prov = bool((answers.get("province_interest") or "").strip())

    scored = {}

    def add(stream, points, reason):
        score, reasons = scored.get(stream, (0, []))
        scored[stream] = (score + points, reasons + [reason])

    if lang >= 7:
        add("Express Entry", 3, "Language CLB 7 or higher")
    if edu in ("bachelor", "master_plus"):
        add("Express Entry", 2, "Degree-level education")
    if work >= 3:
        add("Express Entry", 2, "3+ years of work history")
    elif work >= 1:
        add("Express Entry", 1, "Work history on file")
    if age in ("under-30", "30-40"):
        add("Express Entry", 1, "Age band commonly assessed")
    if prov:
        add("PNP", 3, "Province of interest named")
    if work >= 1:
        add("PNP", 1, "Work history on file")
    if lang >= 4:
        add("PNP", 1, "Language CLB 4 or higher")
    if job:
        add("Work", 4, "Job offer in hand")
        add("LMIA", 2, "Job offer in hand (employer route to explore)")
    if work >= 1:
        add("Work", 1, "Work history on file")
    if adm:
        add("Study", 4, "Admission letter in hand")
    if funds:
        add("Study", 1, "Proof of funds available")
    if edu in ("bachelor", "master_plus"):
        add("Study", 1, "Degree-level education")
    if family:
        add("Family Sponsorship", 4, "Family in Canada")

    order = ["Express Entry", "PNP", "Work", "LMIA", "Study", "Family Sponsorship"]
    ranked = [{"stream": s, "score": sc, "reasons": rs}
              for s, (sc, rs) in sorted(scored.items(), key=lambda kv: (-kv[1][0], order.index(kv[0])))
              if sc > 0]
    return ranked


def run_precheck(db, tenant_id, answers, lead_id=None):
    ranked = score_precheck(answers)
    result = PreCheckResult(tenant_id=tenant_id, lead_id=lead_id,
                            answers=json.dumps(answers), ranked=json.dumps(ranked),
                            disclaimer=DISCLAIMER)
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def precheck_out(result):
    return {"id": result.id, "lead_id": result.lead_id,
            "answers": json.loads(result.answers),
            "ranked": json.loads(result.ranked),
            "disclaimer": result.disclaimer,
            "at": str(result.created_at)}
