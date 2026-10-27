"""Phase 3 document helpers: file storage, checklist init, AI document
reading (template adapter), expiry alerts, submission packet.

Storage: files live under backend/data/uploads/<tenant>/<case>/ (the
backend/data/ dir is gitignored). The database stores only the relative
path — never a blob (design doc, Section 4).

AI reading (Section 6.1) uses the same template-adapter pattern as the
Phase 2 AI drafts: AI_PROVIDER=template (default) reads ONLY the
uploaded file's text content and the case it belongs to, so it cannot
invent a fact and no data leaves the firm. Anything else raises instead
of pretending. Suggestions are rows, never writes: a value suggestion
is applied only by a staff approve action, a mismatch suggestion is
only acknowledged.
"""
import io
import json
import os
import re
import zipfile
from datetime import date, datetime, timedelta

from .models import StreamTemplate, Client, Case
from .models_phase3 import ChecklistItem, DocumentVersion, AiSuggestion
from . import messaging

AI_PROVIDER = os.environ.get("AI_PROVIDER", "template")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "uploads")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _require_template_provider():
    if AI_PROVIDER != "template":
        raise ValueError(
            f"AI provider '{AI_PROVIDER}' is not configured. Set AI_PROVIDER=template "
            "(built-in, reads only the uploaded file's text) or configure a managed provider.")


def safe_filename(name: str) -> str:
    name = os.path.basename(name or "upload")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:100] or "upload"
    return name


def init_checklist(db, tenant_id, case):
    """Create checklist items from the case's stream template, if the
    case has none yet. Returns the items (new or existing)."""
    existing = db.query(ChecklistItem).filter(
        ChecklistItem.tenant_id == tenant_id,
        ChecklistItem.case_id == case.id).order_by(ChecklistItem.id).all()
    if existing:
        return existing
    template = db.query(StreamTemplate).filter(
        StreamTemplate.tenant_id == tenant_id,
        StreamTemplate.stream == case.stream).first()
    if not template:
        return []
    items = [ChecklistItem(tenant_id=tenant_id, case_id=case.id,
                           document_name=name, person="principal",
                           status="Not Started")
             for name in json.loads(template.checklist)]
    db.add_all(items)
    db.commit()
    for it in items:
        db.refresh(it)
    return items


def save_upload(db, tenant_id, item, content: bytes, filename: str,
                content_type: str, by_kind: str, by_id):
    """Persist one uploaded file + its DocumentVersion row. Returns the
    version. The item moves to Uploaded and its rejection reason clears
    (the version history keeps the old reason)."""
    if not content:
        raise ValueError("Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Uploaded file exceeds the 25 MB limit.")
    version = DocumentVersion(
        tenant_id=tenant_id, checklist_item_id=item.id, version_no=1,
        file_path="", original_filename=filename, content_type=content_type,
        size_bytes=len(content), uploaded_by_kind=by_kind, uploaded_by_id=by_id)
    db.add(version)
    db.flush()
    siblings = db.query(DocumentVersion).filter(
        DocumentVersion.checklist_item_id == item.id).count()
    version.version_no = siblings
    rel = os.path.join(str(tenant_id), str(item.case_id),
                       f"{version.id}_{safe_filename(filename)}")
    full = os.path.join(DATA_DIR, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(content)
    version.file_path = rel
    item.status = "Uploaded"
    item.rejection_reason = ""
    db.commit()
    db.refresh(version)
    return version


def file_full_path(version: DocumentVersion) -> str:
    return os.path.join(DATA_DIR, version.file_path)


def latest_version(db, item_id):
    return db.query(DocumentVersion).filter(
        DocumentVersion.checklist_item_id == item_id).order_by(
        DocumentVersion.id.desc()).first()


# ---------- AI document reading (6.1) ----------
_FIELD_PATTERNS = [
    # (regex, proposed_field) — value suggestions, applied only on approval.
    (r"(?im)^\s*uci\s*[:#]\s*([A-Za-z0-9-]{4,})\s*$", "uci"),
    (r"(?im)^\s*(?:ircc\s*file(?:\s*number)?|file\s*number)\s*[:#]\s*([A-Za-z0-9-]{4,})\s*$",
     "ircc_file_number"),
    (r"(?im)^\s*expir(?:y|ation)(?:\s*date)?\s*[:#]\s*(\d{4}-\d{2}-\d{2})\s*$", "expiry_date"),
]
_NAME_PATTERN = r"(?im)^\s*name\s*[:#]\s*(.+?)\s*$"


def _readable_text(content: bytes):
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "\x00" in text:  # binary payload, not readable text
        return None
    return text


def generate_suggestions(db, tenant_id, case, client, version, content: bytes):
    """Propose case-field values + mismatch flags from one upload.
    Returns the created suggestions (possibly empty). Never writes to
    the case, the client, or the item — approval does that, separately."""
    _require_template_provider()
    text = _readable_text(content)
    if text is None:
        return []
    created = []

    def add(kind, field, value, excerpt):
        sug = AiSuggestion(tenant_id=tenant_id, document_version_id=version.id,
                           case_id=case.id, kind=kind, proposed_field=field,
                           proposed_value=value, source_excerpt=excerpt[:200])
        db.add(sug)
        created.append(sug)

    for pattern, field in _FIELD_PATTERNS:
        m = re.search(pattern, text)
        if not m:
            continue
        value = m.group(1).strip()
        current = {"uci": case.uci or "", "ircc_file_number": case.ircc_file_number or "",
                   "expiry_date": ""}.get(field, "")
        if field == "expiry_date":
            item = db.query(ChecklistItem).filter(ChecklistItem.id == version.checklist_item_id).first()
            current = str(item.expiry_date) if item and item.expiry_date else ""
            if value == current:
                continue
            add("value", field, value, m.group(0).strip())
            try:
                if datetime.strptime(value, "%Y-%m-%d").date() < date.today():
                    add("mismatch", "expiry_in_past",
                        f"Document expiry {value} is already past", m.group(0).strip())
            except ValueError:
                pass
        elif value != current:
            add("value", field, value, m.group(0).strip())
    m = re.search(_NAME_PATTERN, text)
    if m and client:
        found = m.group(1).strip()
        if found.lower() != (client.full_name or "").lower():
            add("mismatch", "name_mismatch",
                f"Document says '{found}' but the file says '{client.full_name}'",
                m.group(0).strip())
    if created:
        db.commit()
        for sug in created:
            db.refresh(sug)
    return created


def apply_suggestion(db, tenant_id, suggestion, user_id):
    """Staff approve: value suggestions write their field; mismatch
    suggestions are only acknowledged. Either way the suggestion leaves
    Pending and the decision is audited."""
    if suggestion.status != "Pending":
        raise ValueError(f"Suggestion is {suggestion.status}, not open for decision.")
    version = db.query(DocumentVersion).filter(
        DocumentVersion.id == suggestion.document_version_id).first()
    item = db.query(ChecklistItem).filter(
        ChecklistItem.id == version.checklist_item_id).first() if version else None
    if suggestion.kind == "value":
        case = db.query(Case).filter(Case.id == suggestion.case_id).first()
        if suggestion.proposed_field == "uci" and case:
            case.uci = suggestion.proposed_value
        elif suggestion.proposed_field == "ircc_file_number" and case:
            case.ircc_file_number = suggestion.proposed_value
        elif suggestion.proposed_field == "expiry_date" and item:
            item.expiry_date = datetime.strptime(suggestion.proposed_value, "%Y-%m-%d").date()
        elif suggestion.proposed_field == "client_full_name" and case:
            client = db.query(Client).filter(Client.id == case.client_id).first()
            if client:
                client.full_name = suggestion.proposed_value
    suggestion.status = "Approved"
    suggestion.decided_by_id = user_id
    suggestion.decided_at = datetime.utcnow()
    messaging.audit(db, tenant_id, user_id, "suggestion_decided", "ai_suggestion",
                    suggestion.id,
                    f"{suggestion.kind}:{suggestion.proposed_field} approved"
                    + (" (applied)" if suggestion.kind == "value" else " (acknowledged)"))
    db.commit()
    db.refresh(suggestion)
    return suggestion


# ---------- notifications (reuse Phase 2 log-mode adapters) ----------
def notify_client(db, tenant_id, firm_name, case, client, sms_body, email_subject, email_body):
    """Notify via every channel the client has contact info for. In log
    mode (the default) this records would-sends in the case log and
    delivers nothing; live-mode gates are enforced by the adapters. A
    failed channel never blocks the staff action that triggered it."""
    if client is None:
        return
    if client.phone:
        try:
            messaging.send_sms(db, tenant_id, firm_name, client.phone, sms_body,
                               case_id=case.id, template_key="status_update",
                               source="system", client_id=client.id)
        except ValueError:
            pass
    if client.email:
        try:
            messaging.send_email(db, tenant_id, firm_name, client.email,
                                 email_subject, email_body,
                                 case_id=case.id, template_key="status_update",
                                 source="system", client_id=client.id)
        except ValueError:
            pass


def run_expiry_alerts(db, tenant_id, firm_name):
    """Expiry alerts job: items with an expiry date that are not already
    Expired. Past expiry flips the item to Expired; expiry within 30
    days alerts. Each expiry date is alerted once (alerted_for_expiry),
    so re-running the job never spams the client."""
    today = date.today()
    horizon = today + timedelta(days=30)
    items = db.query(ChecklistItem).filter(
        ChecklistItem.tenant_id == tenant_id,
        ChecklistItem.expiry_date.isnot(None),
        ChecklistItem.status != "Expired").all()
    expired_n, alerted_n = 0, 0
    for item in items:
        if item.alerted_for_expiry == item.expiry_date:
            continue
        case = db.query(Case).filter(Case.id == item.case_id).first()
        client = db.query(Client).filter(Client.id == case.client_id).first() if case else None
        if item.expiry_date < today:
            item.status = "Expired"
            item.alerted_for_expiry = item.expiry_date
            if case and client:
                notify_client(db, tenant_id, firm_name, case, client,
                              f"Hi {client.full_name}, your document '{item.document_name}' "
                              f"for your {case.stream} case has expired. Please provide a current copy.",
                              "A document on your case has expired",
                              f"Hi {client.full_name},\n\nYour document '{item.document_name}' "
                              f"for your {case.stream} case expired on {item.expiry_date}. "
                              "Please provide a current copy.")
            expired_n += 1
        elif item.expiry_date <= horizon:
            item.alerted_for_expiry = item.expiry_date
            if case and client:
                notify_client(db, tenant_id, firm_name, case, client,
                              f"Hi {client.full_name}, your document '{item.document_name}' "
                              f"for your {case.stream} case expires on {item.expiry_date}. "
                              "Please renew it before then.",
                              "A document on your case expires soon",
                              f"Hi {client.full_name},\n\nYour document '{item.document_name}' "
                              f"for your {case.stream} case expires on {item.expiry_date}. "
                              "Please renew it before then.")
            alerted_n += 1
    db.commit()
    return {"expired": expired_n, "alerted": alerted_n}


def build_packet(db, tenant_id, case):
    """Submission packet: the latest APPROVED version of each checklist
    item, plus a manifest. Returns (BytesIO, filename). Items without an
    approved version are listed in the manifest as missing."""
    items = db.query(ChecklistItem).filter(
        ChecklistItem.tenant_id == tenant_id,
        ChecklistItem.case_id == case.id).order_by(ChecklistItem.id).all()
    manifest = [f"Submission packet — case {case.id} ({case.stream})",
                f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", ""]
    to_include = []
    for item in items:
        approved = db.query(DocumentVersion).filter(
            DocumentVersion.checklist_item_id == item.id,
            DocumentVersion.review_decision == "approved").order_by(
            DocumentVersion.id.desc()).first()
        if not approved:
            manifest.append(f"MISSING (no approved version): {item.document_name}")
            continue
        full = file_full_path(approved)
        if not os.path.exists(full):
            manifest.append(f"MISSING (file not on disk): {item.document_name}")
            continue
        to_include.append((item, approved, full))
        manifest.append(f"INCLUDED: {item.document_name} (version {approved.version_no})")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.txt", "\n".join(manifest) + "\n")
        for item, approved, full in to_include:
            zf.write(full, f"{item.document_name}/{approved.original_filename or 'document'}")
    buf.seek(0)
    return buf, f"case-{case.id}-submission-packet.zip"
