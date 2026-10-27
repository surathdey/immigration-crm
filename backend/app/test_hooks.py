"""Test-only endpoints. Registered ONLY when ALLOW_TEST_HOOKS=true
(default off, never on in production). They inject failure states that
a real provider outage would produce, so the retry-then-action-item
rules are verifiable without a real outage. They create no real sends.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db
from .models_phase2 import CaseMessage, ReminderLog, TestFailure, TestReminderFailure
from . import auth
from .models import User

router = APIRouter()


class FailMessageBody(BaseModel):
    message_id: int


@router.post("/api/test-hooks/fail-message")
def fail_message(body: FailMessageBody, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    msg = db.query(CaseMessage).filter(
        CaseMessage.id == body.message_id, CaseMessage.tenant_id == user.tenant_id).first()
    if not msg:
        raise HTTPException(404, "Message not found")
    msg.status, msg.provider_status = "failed", "test-injected failure"
    if not db.query(TestFailure).filter(TestFailure.message_id == msg.id).first():
        db.add(TestFailure(message_id=msg.id))
    db.commit()
    return {"message_id": msg.id, "status": "failed"}


class FailReminderBody(BaseModel):
    consultation_id: int | None = None
    deadline_id: int | None = None
    channel: str = "sms"


@router.post("/api/test-hooks/fail-reminder")
def fail_reminder(body: FailReminderBody, user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    log = ReminderLog(tenant_id=user.tenant_id, consultation_id=body.consultation_id,
                      deadline_id=body.deadline_id, channel=body.channel,
                      window_key="test", recipient="test", status="failed")
    db.add(log)
    db.flush()
    db.add(TestReminderFailure(reminder_log_id=log.id))
    db.commit()
    return {"reminder_log_id": log.id, "status": "failed"}
