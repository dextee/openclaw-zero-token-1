#!/usr/bin/env python3
"""IMAP account credential management for SG Outreach reply tracking.

Central store: /root/.openclaw/workspace/outreach/imap_accounts.json

Each entry:
  {
    "email": "louis@miraeadvisory.com",
    "imap_server": "imap.gmail.com",
    "imap_port": 993,
    "app_password": "xxxx xxxx xxxx xxxx",
    "configured_at": "2026-05-03T10:00:00",
    "configured_by": "portal|telegram|cli",
    "last_check": null,
    "last_reply_count": 0,
    "status": "ok|error|untested"
  }
"""

import fcntl
import imaplib
import json
import logging
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STORE_PATH = Path("/root/.openclaw/workspace/outreach/imap_accounts.json")
DEFAULT_IMAP_SERVER = "imap.gmail.com"
DEFAULT_IMAP_PORT = 993
CONNECT_TIMEOUT = 10


def _load_store() -> dict:
    if not STORE_PATH.exists():
        return {}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logging.warning("imap_accounts.json is corrupt: %s", e)
        return {}
    except Exception:
        return {}


def _save_store(store: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: write to temp then rename, with exclusive lock
    fd, tmp_path = tempfile.mkstemp(dir=STORE_PATH.parent, prefix=".imap_accounts_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(store, f, indent=2)
        os.replace(tmp_path, STORE_PATH)
        os.chmod(STORE_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def list_accounts() -> list[dict]:
    """Return all configured accounts as a list."""
    return list(_load_store().values())


def get_account(email: str) -> dict | None:
    return _load_store().get(email.strip().lower())


def save_account(
    email: str,
    app_password: str,
    imap_server: str = DEFAULT_IMAP_SERVER,
    imap_port: int = DEFAULT_IMAP_PORT,
    configured_by: str = "cli",
) -> dict:
    """Save or update IMAP credentials for an account."""
    key = email.strip().lower()
    store = _load_store()
    existing = store.get(key, {})
    entry = {
        "email": key,
        "imap_server": imap_server or DEFAULT_IMAP_SERVER,
        "imap_port": int(imap_port or DEFAULT_IMAP_PORT),
        "app_password": app_password.strip(),
        "configured_at": existing.get("configured_at") or datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "configured_by": configured_by,
        "last_check": existing.get("last_check"),
        "last_reply_count": existing.get("last_reply_count", 0),
        "status": "untested",
    }
    store[key] = entry
    _save_store(store)
    return entry


def delete_account(email: str) -> bool:
    key = email.strip().lower()
    store = _load_store()
    if key in store:
        del store[key]
        _save_store(store)
        return True
    return False


def test_connection(email: str, app_password: str = None,
                   imap_server: str = None, imap_port: int = None) -> tuple[bool, str]:
    """Test IMAP connection. Returns (success, message).

    If app_password is None, reads from the credential store.
    """
    key = email.strip().lower()
    if app_password is None:
        account = get_account(key)
        if not account:
            return False, f"No credentials found for {email}"
        app_password = account["app_password"]
        imap_server = account.get("imap_server", DEFAULT_IMAP_SERVER)
        imap_port = account.get("imap_port", DEFAULT_IMAP_PORT)

    server = imap_server or DEFAULT_IMAP_SERVER
    port = int(imap_port or DEFAULT_IMAP_PORT)

    mail = None
    try:
        mail = imaplib.IMAP4_SSL(server, port, timeout=CONNECT_TIMEOUT)
        mail.login(key, app_password)
        mail.select("inbox")
        status, data = mail.search(None, "ALL")
        count = len(data[0].split()) if status == "OK" and data[0] else 0
        msg = f"Connected to {server}. Inbox has {count} messages."
        store = _load_store()
        if key in store:
            store[key]["status"] = "ok"
            store[key]["last_check"] = datetime.now(timezone.utc).isoformat()
            _save_store(store)
        return True, msg
    except imaplib.IMAP4.error as e:
        err = str(e)
        if "AUTHENTICATIONFAILED" in err or "Invalid credentials" in err:
            return False, "Authentication failed. Check your App Password."
        return False, f"IMAP error: {err}"
    except Exception as e:
        return False, f"Connection error: {e}"
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass


def mark_last_check(email: str, reply_count: int = 0) -> None:
    key = email.strip().lower()
    store = _load_store()
    if key in store:
        store[key]["last_check"] = datetime.now(timezone.utc).isoformat()
        store[key]["last_reply_count"] = reply_count
        store[key]["status"] = "ok"
        _save_store(store)


if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="IMAP account manager")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="List configured accounts")
    p_test = sub.add_parser("test", help="Test IMAP connection")
    p_test.add_argument("email")
    p_save = sub.add_parser("save", help="Save credentials")
    p_save.add_argument("email")
    p_save.add_argument("app_password")
    p_save.add_argument("--server", default=DEFAULT_IMAP_SERVER)
    p_save.add_argument("--port", type=int, default=DEFAULT_IMAP_PORT)
    p_del = sub.add_parser("delete", help="Remove account")
    p_del.add_argument("email")

    args = parser.parse_args()

    if args.cmd == "list":
        accounts = list_accounts()
        if not accounts:
            print("No IMAP accounts configured.")
        for a in accounts:
            status = a.get("status", "untested")
            last = a.get("last_check", "never")[:19] if a.get("last_check") else "never"
            print(f"  {a['email']:35s}  status={status:8s}  last_check={last}")

    elif args.cmd == "test":
        ok, msg = test_connection(args.email)
        print(f"{'OK' if ok else 'FAIL'}: {msg}")
        sys.exit(0 if ok else 1)

    elif args.cmd == "save":
        entry = save_account(args.email, args.app_password, args.server, args.port)
        print(f"Saved {entry['email']}. Testing connection...")
        ok, msg = test_connection(args.email)
        print(f"{'OK' if ok else 'FAIL'}: {msg}")
        sys.exit(0 if ok else 1)

    elif args.cmd == "delete":
        if delete_account(args.email):
            print(f"Removed {args.email}")
        else:
            print(f"Not found: {args.email}")

    else:
        parser.print_help()
