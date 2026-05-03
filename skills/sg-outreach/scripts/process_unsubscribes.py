#!/usr/bin/env python3
"""Weekly IMAP unsubscribe sweep.

Reads UNSEEN messages to unsubscribe@<domain>, extracts sender addresses,
adds them to the suppression list, and marks messages as seen.

Usage:
    python3 process_unsubscribes.py --user-id <chat_id>
"""

import argparse
import email
import json
import os
import re
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
import outreach_history as oh
import imap_auth


def resolve_config(chat_id: str, account_email: str | None = None) -> dict:
    """Read IMAP config. Priority: central imap_accounts.json > per-user config > global config."""
    if account_email:
        account = imap_auth.get_account(account_email)
        if account:
            return {
                "email": account["email"],
                "app_password": account["app_password"],
                "imap_host": account.get("imap_server", imap_auth.DEFAULT_IMAP_SERVER),
                "imap_port": account.get("imap_port", imap_auth.DEFAULT_IMAP_PORT),
            }
    paths = [
        f"/root/.openclaw/workspace/outreach/user_{chat_id}/.workspace_smtp_config.json",
        os.path.join(SKILL_DIR, ".workspace_smtp_config.json"),
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    return {}


def extract_addresses_from_msg(msg_bytes: bytes) -> list[str]:
    """Extract unsubscribe requester addresses from an email message."""
    msg = email.message_from_bytes(msg_bytes)
    addresses = []

    # From header
    from_hdr = msg.get("From", "")
    m = re.search(r'<([^>]+)>', from_hdr)
    if m:
        addresses.append(m.group(1).lower().strip())
    elif "@" in from_hdr:
        addresses.append(from_hdr.lower().strip())

    # Reply-To header
    reply_to = msg.get("Reply-To", "")
    if reply_to:
        m = re.search(r'<([^>]+)>', reply_to)
        if m:
            addresses.append(m.group(1).lower().strip())
        elif "@" in reply_to:
            addresses.append(reply_to.lower().strip())

    # Body text
    for part in msg.walk():
        if part.get_content_type() in ("text/plain", "text/html"):
            try:
                payload = part.get_payload(decode=True)
                if payload:
                    text = payload.decode("utf-8", errors="ignore")
                    # Look for email addresses in the body
                    found = re.findall(r'[\w.-]+@[\w.-]+\.\w+', text)
                    addresses.extend([f.lower().strip() for f in found])
            except Exception:
                continue

    return list(dict.fromkeys(addresses))  # dedupe preserve order


def main():
    parser = argparse.ArgumentParser(description="Unsubscribe IMAP sweep")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--account-email", default=None,
                        help="Email from central imap_accounts.json store")
    args = parser.parse_args()

    config = resolve_config(args.user_id, args.account_email)
    imap_host = config.get("imap_host", "")
    imap_port = int(config.get("imap_port", 993))
    email_addr = config.get("email", "")
    password = config.get("app_password", "")

    if not imap_host or not password:
        print(json.dumps({"skipped": "imap_not_configured"}))
        sys.exit(0)

    try:
        import imaplib
        mail = imaplib.IMAP4_SSL(imap_host, imap_port)
        mail.login(email_addr, password)
        mail.select("inbox")

        # Search for UNSEEN messages to unsubscribe@domain
        unsub_addr = f"unsubscribe@{email_addr.split('@')[-1]}"
        _, data = mail.search(None, f'(UNSEEN TO "{unsub_addr}")')
        msg_ids = data[0].split()

        suppressed = []
        for msg_id in msg_ids:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    addresses = extract_addresses_from_msg(response_part[1])
                    for addr in addresses:
                        oh.record_contact(email=addr, status="unsubscribed")
                        suppressed.append(addr)
            # Mark as seen
            mail.store(msg_id, "+FLAGS", "\\Seen")

        mail.close()
        mail.logout()

        result = {"processed": len(msg_ids), "suppressed": len(suppressed), "addresses": suppressed}
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
