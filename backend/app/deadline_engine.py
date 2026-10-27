"""Deadline engine (Phase 4): derived deadlines from firm rules, the
30/14/7-day alert schedule, and overdue escalation.

Alert honesty follows the Phase 2/3 job pattern: alerts are recorded
in ReminderLog under one window key per deadline per window, so a
re-run never double-alerts. Escalation is a dashboard ActionItem for
the branch manager / firm admin (deduped per deadline while unresolved)
— the manager sees it on the dashboard, exactly where Phase 2 surfaces
failed sends and syncs. Client alerts go through the Phase 2 log-mode
adapters; nothing here sends outside log mode unless the firm has
enabled live sending with verified senders.
"""
from datetime import datetime, timedelta

from .models import Client, Case, CaseStageEvent
from .models_phase2 import Deadline, ReminderLog, ActionItem
from .models_phase4 import DeadlineRule

ALERT_WINDOWS = [30, 14, 7]


def derive_for_case(db, tenant_id, case):
    """Create open deadlines for every rule that fires for this case.
    Idempotent: an open deadline with the same case, title, and type
    is never created twice. Returns the list of newly created rows."""
    created = []
    for rule in db.query(DeadlineRule).filter(
            DeadlineRule.tenant_id == tenant_id).all():
        base = None
        if rule.trigger == "case_created":
            base = case.created_at
        elif rule.trigger == "submission":
            base = datetime.combine(case.submission_date,
                                    datetime.min.time()) if case.submission_date else None
        elif rule.trigger == "stage_entered" and rule.stage:
            ev = db.query(CaseStageEvent).filter(
                CaseStageEvent.case_id == case.id,
                CaseStageEvent.to_stage == rule.stage).order_by(
                CaseStageEvent.created_at.desc(), CaseStageEvent.id.desc()).first()
            base = ev.created_at if ev else None
        if base is None:
            continue
        due = base + timedelta(days=rule.offset_days)
        existing = db.query(Deadline).filter(
            Deadline.tenant_id == tenant_id, Deadline.case_id == case.id,
            Deadline.title == rule.title, Deadline.deadline_type == rule.deadline_type,
            Deadline.done == False).first()
        if existing:
            continue
        row = Deadline(tenant_id=tenant_id, case_id=case.id, title=rule.title,
                       deadline_type=rule.deadline_type, due_date=due, remind_for="both")
        db.add(row)
        created.append(row)
    db.commit()
    return created


def run_deadline_alerts(db, tenant_id, firm_name, now=None):
    """30/14/7-day alerts + overdue escalation. Returns
    {"alerted": n, "escalated": m}."""
    from . import messaging  # deferred: avoids an import cycle at module load
    now = now or datetime.utcnow()
    alerted = escalated = 0
    for dl in db.query(Deadline).filter(
            Deadline.tenant_id == tenant_id, Deadline.done == False).all():
        days_left = (dl.due_date.date() - now.date()).days if dl.due_date else None
        case = db.query(Case).filter(Case.id == dl.case_id).first()
        client = db.query(Client).filter(
            Client.id == case.client_id).first() if case else None
        if days_left is not None and days_left in ALERT_WINDOWS:
            window = f"deadline-engine:{dl.id}:{days_left}d"
            if not db.query(ReminderLog).filter(
                    ReminderLog.tenant_id == tenant_id,
                    ReminderLog.window_key == window).first():
                body = (f"Hi {client.full_name if client else 'there'}, "
                        f"a deadline on your case is in {days_left} days: "
                        f"{dl.title}, due {dl.due_date.date()}.")
                sent = False
                if dl.remind_for in ("client", "both") and client:
                    if client.phone:
                        try:
                            messaging.send_sms(db, tenant_id, firm_name, client.phone,
                                               body, case_id=dl.case_id,
                                               template_key="status_update",
                                               source="system", client_id=client.id)
                            sent = True
                        except ValueError:
                            pass
                    if client.email:
                        try:
                            messaging.send_email(db, tenant_id, firm_name, client.email,
                                                 f"Deadline in {days_left} days: {dl.title}",
                                                 body, case_id=dl.case_id,
                                                 template_key="status_update",
                                                 source="system", client_id=client.id)
                            sent = True
                        except ValueError:
                            pass
                db.add(ReminderLog(tenant_id=tenant_id, deadline_id=dl.id,
                                   channel="sms", window_key=window,
                                   recipient=client.phone if client else "",
                                   status="would_send" if sent else "failed"))
                if sent:
                    alerted += 1
        if days_left is not None and days_left < 0:
            marker = f"deadline #{dl.id}"
            existing = db.query(ActionItem).filter(
                ActionItem.tenant_id == tenant_id, ActionItem.resolved == False,
                ActionItem.kind == "deadline_escalation",
                ActionItem.detail.like(f"%{marker}%")).first()
            if not existing:
                branch = f"branch {case.branch_id}" if case and case.branch_id else "the firm"
                db.add(ActionItem(
                    tenant_id=tenant_id, kind="deadline_escalation",
                    title=f"Overdue deadline: {dl.title} (case #{dl.case_id})",
                    detail=f"{marker} is overdue since {dl.due_date.date()} — "
                           f"escalated to the branch manager / firm admin of {branch}."))
                escalated += 1
    db.commit()
    return {"alerted": alerted, "escalated": escalated}
