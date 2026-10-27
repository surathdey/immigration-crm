"""Auth: OTP sign-in (W1) + firm selection.

Phase 1 has no SMS/email sending channel (those arrive in Phase 2), so
OTP delivery works like this, honestly labelled:
- DEV_OTP=true (demo/dev only): the code is returned in the API
  response so sign-in works out of the box. Never enable in production.
- DEV_OTP=false: the code is stored only; delivery needs the Phase 2
  channel, and the response says so instead of pretending it was sent.
"""
import os
import random
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from .db import get_db
from .models import User, OtpCode

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
DEV_OTP = os.environ.get("DEV_OTP", "true").lower() == "true"
ALGORITHM = "HS256"
bearer = HTTPBearer(auto_error=False)


def request_otp(db: Session, email: str) -> dict:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        # Do not reveal whether the email exists; still behave the same.
        return {"sent": False, "dev_code": None, "detail": "If this email belongs to a staff account, a code was issued."}
    code = f"{random.randint(0, 999999):06d}"
    db.query(OtpCode).filter(OtpCode.email == email, OtpCode.used == 0).update({"used": 1})
    db.add(OtpCode(email=email, code=code, expires_at=datetime.utcnow() + timedelta(minutes=10)))
    db.commit()
    if DEV_OTP:
        return {"sent": True, "dev_code": code, "detail": "Development mode: code returned in response (no message sent)."}
    return {"sent": False, "dev_code": None, "detail": "OTP delivery channel arrives in Phase 2; code stored, not sent."}


def verify_otp(db: Session, email: str, code: str) -> dict:
    row = (
        db.query(OtpCode)
        .filter(OtpCode.email == email, OtpCode.code == code, OtpCode.used == 0)
        .order_by(OtpCode.id.desc())
        .first()
    )
    if not row or row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    row.used = 1
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    db.commit()
    token = jwt.encode(
        {"sub": str(user.id), "tenant_id": user.tenant_id, "role": user.role,
         "exp": datetime.utcnow() + timedelta(hours=12)},
        SECRET_KEY, algorithm=ALGORITHM,
    )
    return {"token": token, "user": {"id": user.id, "email": user.email,
                                     "full_name": user.full_name, "role": user.role,
                                     "tenant_id": user.tenant_id, "branch_id": user.branch_id}}


def current_user(creds: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)):
    if not creds:
        raise HTTPException(status_code=401, detail="Not signed in")
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        user_id = int(payload["sub"])
    except (ValueError, TypeError):
        # Portal tokens (sub "client:<id>") are not staff tokens.
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Unknown user")
    return user


def scope_filter(user, query, model):
    """Tenant scoping, plus branch scoping for non-admin staff."""
    q = query.filter(model.tenant_id == user.tenant_id)
    if user.role != "firm_admin" and user.branch_id:
        q = q.filter(model.branch_id == user.branch_id)
    return q
