"""Inbound Meta webhook tests (WhatsApp + Facebook/Instagram -> leads).

Boots the backend itself from backend/ on a FRESH SQLite DB, then drives
it with fake Meta payloads signed with a test secret. No network, no
Meta account, no Page token needed (the leadgen stub path is tested).

Usage: backend/.venv/bin/python scripts/test_webhooks.py [PORT]
Exits non-zero if any check fails. Kills the server it started.
"""
import hashlib
import hmac
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
BASE = f"http://127.0.0.1:{PORT}"
DB = "/tmp/webhooks_test.db"
VERIFY_TOKEN = "test-verify-token"
APP_SECRET = "test-app-secret"
WA_PHONE = "+14165550199"
WA_TEXT = "Hi, I want to study in Canada"

passed, failed = [], []


def check(name, cond, extra=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" — {extra}" if extra and not cond else ""))


def sign(body_bytes):
    return "sha256=" + hmac.new(APP_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()


def call(method, path, body=None, signature="valid", headers=None):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"}
    if data is not None:
        if signature == "valid":
            hdrs["X-Hub-Signature-256"] = sign(data)
        elif signature == "bad":
            hdrs["X-Hub-Signature-256"] = "sha256=" + "0" * 64
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(BASE + path, method=method, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def db_count(sql, params=()):
    conn = sqlite3.connect(DB, timeout=10)
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def db_one(sql, params=()):
    conn = sqlite3.connect(DB, timeout=10)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def port_free(port):
    s = socket.socket()
    try:
        s.connect(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def main():
    if not port_free(PORT):
        print(f"FAIL port {PORT} is already in use — kill the stale server first, do not test against it")
        return 1
    if os.path.exists(DB):
        os.remove(DB)
    env = dict(os.environ)
    env.update({"DATABASE_URL": f"sqlite:///{DB}", "SECRET_KEY": "smoke-test", "DEV_OTP": "true",
                "META_VERIFY_TOKEN": VERIFY_TOKEN, "META_APP_SECRET": APP_SECRET})
    env.pop("META_PAGE_TOKEN", None)  # stub path for leadgen
    proc = subprocess.Popen(
        [os.path.join(BACKEND, ".venv", "bin", "python"), "-m", "uvicorn", "app.main:app",
         "--port", str(PORT)],
        cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 60
        while True:
            try:
                status, _ = call("GET", "/api/health")
                if status == 200:
                    break
            except Exception:
                pass
            if time.time() > deadline:
                print("FAIL backend did not come up on /api/health")
                return 1
            time.sleep(1)

        # (0) GET handshake
        status, body = call("GET", f"/api/webhooks/meta?hub.mode=subscribe"
                                   f"&hub.verify_token={VERIFY_TOKEN}&hub.challenge=CHALLENGE123")
        check("GET handshake echoes challenge", status == 200 and body == "CHALLENGE123",
              f"{status} {body!r}")
        status, _ = call("GET", "/api/webhooks/meta?hub.mode=subscribe"
                                "&hub.verify_token=wrong&hub.challenge=CHALLENGE123")
        check("GET handshake rejects wrong token", status == 403, f"{status}")

        # (1) WhatsApp text message -> lead
        wa = {"object": "whatsapp_business_account", "entry": [{"id": "WABA1", "changes": [
            {"field": "messages", "value": {
                "messaging_product": "whatsapp",
                "messages": [{"from": WA_PHONE, "id": "wamid.HBgTest1", "timestamp": "1700000000",
                              "type": "text", "text": {"body": WA_TEXT}}],
                "contacts": [{"profile": {"name": "Test User"}, "wa_id": WA_PHONE}]}}]}]}
        status, body = call("POST", "/api/webhooks/meta", wa)
        row = db_one("SELECT full_name, phone, source, notes FROM leads WHERE phone = ?", (WA_PHONE,))
        check("WhatsApp message creates lead with phone", status == 200 and row is not None
              and row[0] == "Test User" and row[1] == WA_PHONE and row[2] == "WhatsApp"
              and row[3] == WA_TEXT, f"{status} {body} row={row}")
        check("WhatsApp event recorded", db_count(
            "SELECT COUNT(*) FROM webhook_events WHERE provider = 'whatsapp'") == 1)

        # (2) Duplicate delivery of the same message id -> ignored
        status, _ = call("POST", "/api/webhooks/meta", wa)
        check("Duplicate WhatsApp delivery ignored", status == 200
              and db_count("SELECT COUNT(*) FROM leads WHERE phone = ?", (WA_PHONE,)) == 1
              and db_count("SELECT COUNT(*) FROM webhook_events WHERE provider = 'whatsapp'") == 1)

        # (3) Bad signature -> 401 and no lead
        before = db_count("SELECT COUNT(*) FROM leads")
        status, _ = call("POST", "/api/webhooks/meta", wa, signature="bad")
        check("Bad signature rejected with 401", status == 401
              and db_count("SELECT COUNT(*) FROM leads") == before, f"{status}")
        status, _ = call("POST", "/api/webhooks/meta", wa, signature="none")
        check("Missing signature rejected with 401", status == 401, f"{status}")

        # (4) Leadgen without Page token -> stub lead
        lg = {"object": "page", "entry": [{"id": "PAGE1", "changes": [
            {"field": "leadgen", "value": {"leadgen_id": "LG12345", "page_id": "PAGE1",
                                            "form_id": "FORM1", "created_time": 1700000000}}]}]}
        status, _ = call("POST", "/api/webhooks/meta", lg)
        row = db_one("SELECT full_name, source, notes FROM leads WHERE full_name LIKE 'Facebook Lead Ads%'")
        check("Leadgen without Page token creates stub lead", status == 200 and row is not None
              and row[0] == "Facebook Lead Ads LG12345" and row[1] == "Facebook"
              and "LG12345" in (row[2] or "") and "pending Page token" in (row[2] or ""),
              f"{status} row={row}")

        # (5) Unknown event type -> 200, no lead, no crash
        before = db_count("SELECT COUNT(*) FROM leads")
        unknown = {"object": "page", "entry": [{"id": "PAGE1", "changes": [
            {"field": "feed", "value": {"item": "status"}}]}]}
        status, _ = call("POST", "/api/webhooks/meta", unknown)
        check("Unknown event type ignored with 200", status == 200
              and db_count("SELECT COUNT(*) FROM leads") == before, f"{status}")
        status, _ = call("POST", "/api/webhooks/meta", {"object": "weird_thing", "entry": []})
        check("Unknown object ignored with 200", status == 200, f"{status}")

        # (6) Instagram DM -> lead, deduped on redelivery
        ig = {"object": "instagram", "entry": [{"id": "IG1", "messaging": [
            {"sender": {"id": "IGUSER99"}, "recipient": {"id": "IG1"}, "timestamp": 1700000000,
             "message": {"mid": "mid.ig.1", "text": "Hello, I need help with Express Entry"}}]}]}
        status, _ = call("POST", "/api/webhooks/meta", ig)
        row = db_one("SELECT full_name, source, notes FROM leads WHERE source = 'Instagram'")
        check("Instagram DM creates lead", status == 200 and row is not None
              and row[0] == "Instagram message IGUSER99" and row[2].startswith("Hello"),
              f"{status} row={row}")
        call("POST", "/api/webhooks/meta", ig)
        check("Duplicate Instagram DM ignored",
              db_count("SELECT COUNT(*) FROM leads WHERE source = 'Instagram'") == 1)

        # (7) WhatsApp non-text message -> ignored, no lead
        img = {"object": "whatsapp_business_account", "entry": [{"id": "WABA1", "changes": [
            {"field": "messages", "value": {
                "messages": [{"from": "+14165550200", "id": "wamid.HBgImg1", "type": "image",
                              "image": {"id": "IMG1"}}],
                "contacts": [{"profile": {"name": "Pic Sender"}, "wa_id": "+14165550200"}]}}]}]}
        status, _ = call("POST", "/api/webhooks/meta", img)
        check("WhatsApp non-text ignored", status == 200
              and db_count("SELECT COUNT(*) FROM leads WHERE phone = '+14165550200'") == 0,
              f"{status}")
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    print(f"\n{len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
