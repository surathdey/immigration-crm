"""Client-portal auth (W10/W11). Separate from staff auth on purpose:
a portal code signs into the portal only, a staff code into the staff
app only, and a portal token opens only the owning client's own cases.

Sign-in identifier is the client's email OR phone. The portal belongs
to one firm, so callers pass firm_slug; without it, an identifier that
matches clients in several firms is refused with a clear message asking
for the firm, rather than guessing. DEV_OTP=true returns the code on
screen, exactly like staff sign-in (demo/dev only, never production).
"""
import os
import random
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from .db import get_db
from .models import Tenant, Client
from .models_phase3 import PortalOtpCode
from .auth import SECRET_KEY, DEV_OTP, ALGORITHM

bearer = HTTPBearer(auto_error=False)


def _find_clients(db, identifier, firm_slug):
    q = db.query(Client).filter(
        (Client.email == identifier) | (Client.phone == identifier))
    if firm_slug:
        tenant = db.query(Tenant).filter(Tenant.slug == firm_slug).first()
        if not tenant:
            return [], None
        q = q.filter(Client.tenant_id == tenant.id)
        return q.all(), tenant
    return q.all(), None


def request_portal_otp(db, identifier, firm_slug):
    clients, _ = _find_clients(db, identifier, firm_slug)
    if not clients:
        # Same non-revealing shape as staff sign-in.
        return {"sent": False, "dev_code": None,
                "detail": "If this email or phone belongs to a client account, a code was issued."}
    if len(clients) > 1:
        raise HTTPException(
            400, "This email or phone matches clients at several firms — "
                 "please sign in through your firm's portal link.")
    client = clients[0]
    code = f"{random.randint(0, 999999):06d}"
    db.query(PortalOtpCode).filter(
        PortalOtpCode.client_id == client.id, PortalOtpCode.used == 0).update({"used": 1})
    db.add(PortalOtpCode(tenant_id=client.tenant_id, client_id=client.id,
                         identifier=identifier, code=code,
                         expires_at=datetime.utcnow() + timedelta(minutes=10)))
    db.commit()
    if DEV_OTP:
        return {"sent": True, "dev_code": code,
                "detail": "Development mode: code returned in response (no message sent)."}
    return {"sent": False, "dev_code": None,
            "detail": "Portal code delivery needs the firm's messaging channel; code stored, not sent."}


def verify_portal_otp(db, identifier, firm_slug, code):
    clients, _ = _find_clients(db, identifier, firm_slug)
    if len(clients) != 1:
        raise HTTPException(401, "Invalid or expired code")
    client = clients[0]
    row = (db.query(PortalOtpCode)
           .filter(PortalOtpCode.client_id == client.id, PortalOtpCode.code == code,
                   PortalOtpCode.used == 0)
           .order_by(PortalOtpCode.id.desc()).first())
    if not row or row.expires_at < datetime.utcnow():
        raise HTTPException(401, "Invalid or expired code")
    row.used = 1
    db.commit()
    token = jwt.encode(
        {"sub": f"client:{client.id}", "tenant_id": client.tenant_id,
         "client_id": client.id, "kind": "portal",
         "exp": datetime.utcnow() + timedelta(hours=12)},
        SECRET_KEY, algorithm=ALGORITHM)
    return {"token": token,
            "client": {"id": client.id, "full_name": client.full_name,
                       "email": client.email, "tenant_id": client.tenant_id}}


def current_portal_client(creds: HTTPAuthorizationCredentials = Depends(bearer),
                         db: Session = Depends(get_db)):
    if not creds:
        raise HTTPException(401, "Not signed in to the portal")
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(401, "Invalid token")
    if payload.get("kind") != "portal" or not payload.get("client_id"):
        raise HTTPException(401, "Not a portal token")
    client = db.query(Client).filter(Client.id == int(payload["client_id"])).first()
    if not client or client.tenant_id != payload.get("tenant_id"):
        raise HTTPException(401, "Unknown portal client")
    return client
