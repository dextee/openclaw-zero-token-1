#!/usr/bin/env python3
"""Google Workspace SMTP sender for SG Outreach sequences.

Uses SMTP_SSL (port 465) with an App Password — tokens NEVER expire.
Ideal for Google Workspace accounts where OAuth2 refresh tokens die
after 7 days in Google Cloud Testing mode.

Auth files:
  - .workspace_smtp_config.json  (email + app_password — create this manually)

Config format:
  {
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 465,
    "email": "admin@miraeadvisory.com",
    "app_password": "xxxx xxxx xxxx xxxx"
  }

Usage:
    # Check auth / config:
    python3 workspace_smtp_sender.py --check-auth

    # Send a single one-off email:
    python3 workspace_smtp_sender.py --to "recipient@example.com" \
        --subject "Hello" --body "Body text." --sender-name "Wei Xian"

    # Dry run sequences:
    python3 workspace_smtp_sender.py --sequences leads/sg_sequences_20260407.csv --dry-run

    # Live send:
    python3 workspace_smtp_sender.py --sequences leads/sg_sequences_20260407.csv --daily-limit 450
"""

import argparse
import csv
import json
import os
import random
import re
import smtplib
import sys
import tempfile
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Import global outreach history and domain throttle
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
import outreach_history as oh
from domain_throttle import DomainThrottle, extract_domain

# Module-level defaults — can be overridden via CLI args for per-user campaigns
CONFIG_FILE = os.path.join(SKILL_DIR, ".workspace_smtp_config.json")
STATE_FILE = os.path.join(SKILL_DIR, ".outreach_state.json")
AUTH_STATUS_FILE = os.path.join(SKILL_DIR, ".workspace_auth_status.json")
COMPLIANCE_FILE = "/root/.openclaw/workspace/compliance/COMPLIANCE.json"

DEFAULT_DAILY_LIMIT = 450
PLACEHOLDER_PATTERN = re.compile(r"\{\{[^}]+\}\}")

def load_compliance() -> dict:
    if not os.path.exists(COMPLIANCE_FILE):
        return {}
    with open(COMPLIANCE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_footer(cfg: dict, sender_email: str = "") -> str:
    company = cfg.get("company_name", "").strip()
    address = cfg.get("physical_address", "").strip()
    contact = cfg.get("contact_email", "").strip() or sender_email
    if not company and not address and not contact:
        return ""
    lines = [""]
    if company:
        lines.append(company)
    if address:
        lines.append(address)
    if contact:
        lines.append(f"Unsubscribe: mailto:{contact}?subject=Unsubscribe")
    return "\n".join(lines)


# ── Config & Auth Status ─────────────────────────────────────────────────────

def _load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_auth_status(ok: bool, message: str):
    with open(AUTH_STATUS_FILE, "w") as f:
        json.dump({
            "ok": ok,
            "message": message,
            "checked_at": datetime.now().isoformat(),
        }, f, indent=2)


def _check_smtp_auth(config: dict) -> tuple[bool, str]:
    """Test-connect to SMTP and authenticate. Returns (ok, message)."""
    host = config.get("smtp_host", "smtp.gmail.com")
    port = int(config.get("smtp_port", 465))
    email = config.get("email", "").strip()
    password = config.get("app_password", "").strip()
    relay_mode = config.get("relay_mode", False)

    if not email:
        return False, "AUTH_FAILED: email missing in .workspace_smtp_config.json"
    if not relay_mode and not password:
        return False, "AUTH_FAILED: app_password missing (set relay_mode:true for IP-based auth)"

    try:
        source = ('194.233.74.163', 0) if relay_mode else None
        if port == 465 and not relay_mode:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                server.ehlo()
                server.login(email, password)
        else:
            # STARTTLS mode — relay (port 587). Force IPv4 so whitelisted IP is used.
            server = smtplib.SMTP(host, port, timeout=15, source_address=source)
            server.ehlo()
            server.starttls()
            server.ehlo()
            if not relay_mode and password:
                server.login(email, password)
            server.quit()
        return True, f"Auth OK — {email} ({'relay/IP' if relay_mode else 'SMTP'})"
    except smtplib.SMTPAuthenticationError as e:
        return False, f"AUTH_FAILED: SMTP auth error — {e}"
    except Exception as e:
        return False, f"AUTH_FAILED: SMTP connection error — {e}"


def get_auth_service():
    """Return (config, email, message).  Mirrors gmail_sender.py interface."""
    config = _load_config()
    if not config:
        msg = (
            "AUTH_FAILED: Workspace SMTP config not found.\n"
            f"Create: {CONFIG_FILE}\n"
            "See SKILL.md → 'Workspace SMTP (Never Expire)' section."
        )
        _write_auth_status(False, msg)
        return None, None, msg

    ok, msg = _check_smtp_auth(config)
    _write_auth_status(ok, msg)
    if not ok:
        return None, None, msg
    return config, config.get("email", ""), "ok"


# ── Send Email ───────────────────────────────────────────────────────────────

def create_message(to: str, subject: str, body: str, from_name: str, from_email: str,
                     parent_message_id: str = "") -> tuple:
    body = re.sub(r"<[^>]+>", "", body)
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to
    msg["From"] = f"{from_name} <{from_email}>"
    msg["Subject"] = subject
    msg["Reply-To"] = from_email
    # Add a custom header so IMAP tracker can correlate replies later
    msg_id = f"{int(time.time())}-{random.randint(1000,9999)}"
    msg["X-SG-Outreach-Id"] = msg_id
    if parent_message_id:
        msg["In-Reply-To"] = parent_message_id
        msg["References"] = parent_message_id
    return msg, msg_id


def send_email_smtp(config: dict, to: str, subject: str, body: str,
                    from_name: str, from_email: str, parent_message_id: str = "",
                    compliance_cfg: dict = None) -> dict:
    host = config.get("smtp_host", "smtp.gmail.com")
    port = int(config.get("smtp_port", 465))
    password = config.get("app_password", "")
    relay_mode = config.get("relay_mode", False)

    footer = build_footer(compliance_cfg, sender_email=from_email) if compliance_cfg else ""
    if footer:
        body = body + footer

    msg, msg_id = create_message(to, subject, body, from_name, from_email, parent_message_id)
    source = ('194.233.74.163', 0) if relay_mode else None
    try:
        if port == 465 and not relay_mode:
            with smtplib.SMTP_SSL(host, port, timeout=30) as server:
                server.ehlo()
                server.login(from_email, password)
                server.sendmail(from_email, [to], msg.as_bytes())
        else:
            server = smtplib.SMTP(host, port, timeout=30, source_address=source)
            server.ehlo()
            server.starttls()
            server.ehlo()
            if not relay_mode and password:
                server.login(from_email, password)
            server.sendmail(from_email, [to], msg.as_bytes())
            server.quit()
        return {
            "message_id": msg_id,
            "thread_id": "",
            "status": "sent",
        }
    except smtplib.SMTPRecipientsRefused:
        return {"message_id": "", "thread_id": "", "status": "failed: recipient refused"}
    except smtplib.SMTPSenderRefused:
        return {"message_id": "", "thread_id": "", "status": "failed: sender refused (check relay config)"}
    except Exception as e:
        return {"message_id": "", "thread_id": "", "status": f"failed: {str(e)[:120]}"}


# ── Sequence Scheduling ──────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"campaign_start_date": None, "last_send_date": None, "sent_today": 0}


def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_due_emails(sequences: list, state: dict) -> list:
    now = datetime.now()
    campaign_start = state.get("campaign_start_date")
    if campaign_start:
        campaign_start = datetime.fromisoformat(campaign_start)
    else:
        campaign_start = now
        state["campaign_start_date"] = now.isoformat()
        save_state(state)

    email1_sent: dict[str, datetime] = {}
    for seq in sequences:
        if (seq.get("email_number") in (1, "1") and
                seq.get("status") == "sent" and seq.get("sent_at")):
            try:
                email1_sent[seq["lead_id"]] = datetime.fromisoformat(seq["sent_at"])
            except (ValueError, TypeError):
                pass

    due = []
    for seq in sequences:
        if seq.get("status") != "pending":
            continue
        email_num = int(seq.get("email_number", 1))
        delay_days = int(seq.get("send_delay_days", 0))
        lead_id = seq.get("lead_id", "")

        if email_num == 1:
            due.append(seq)
        else:
            if lead_id not in email1_sent:
                continue
            due_date = email1_sent[lead_id] + timedelta(days=delay_days * (email_num - 1))
            if now >= due_date:
                due.append(seq)
    return due


# ── Send One-Off ──────────────────────────────────────────────────────────────

def send_one(config, to: str, subject: str, body: str, sender_name: str = ""):
    email = config.get("email", "").strip()
    if not sender_name:
        sender_name = email.split("@")[0].replace(".", " ").title()

    compliance_cfg = load_compliance()
    result = send_email_smtp(config, to, subject, body, sender_name, email, compliance_cfg=compliance_cfg)

    if result["status"] == "sent":
        print(f"{Fore.GREEN}SUCCESS: Email sent!{Style.RESET_ALL}")
        print(f"To: {to}")
        print(f"Subject: {subject}")
        print(f"From: {sender_name} <{email}>")
    else:
        print(f"{Fore.RED}FAILED: {result['status']}{Style.RESET_ALL}")
        sys.exit(1)


# ── Send Sequences from CSV ───────────────────────────────────────────────────

def send_sequences_from_csv(sequences_csv: str, daily_limit: int = DEFAULT_DAILY_LIMIT,
                            dry_run: bool = False):
    if not os.path.exists(sequences_csv):
        print(f"{Fore.RED}Error: Sequences file not found: {sequences_csv}{Style.RESET_ALL}")
        sys.exit(1)

    config, email, msg = get_auth_service()
    if not config:
        print(msg)
        sys.exit(1)

    compliance_cfg = load_compliance()

    state = load_state()
    today_str = datetime.now().strftime("%Y-%m-%d")
    if state.get("last_send_date") != today_str:
        state["sent_today"] = 0
        state["last_send_date"] = today_str

    with open(sequences_csv, encoding="utf-8-sig") as f:
        sequences = list(csv.DictReader(f))

    if not sequences:
        print(f"{Fore.YELLOW}No sequences found in {sequences_csv}{Style.RESET_ALL}")
        return

    # ── Pre-send validation ────────────────────────────────────────────────
    val_errors = []
    for i, seq in enumerate(sequences, 1):
        if not seq.get("sender_name", "").strip():
            val_errors.append(f"Row {i}: sender_name is EMPTY")
        unfilled = PLACEHOLDER_PATTERN.findall(f"{seq.get('subject','')} {seq.get('body','')}")
        if unfilled:
            val_errors.append(f"Row {i} ({seq.get('company_name','?')}): Unfilled placeholders: {', '.join(set(unfilled))}")
    if val_errors:
        print(f"{Fore.RED}PRE-SEND VALIDATION FAILED ({len(val_errors)} errors):{Style.RESET_ALL}")
        for e in val_errors[:10]:
            print(f"  ✗ {e}")
        if len(val_errors) > 10:
            print(f"  ... and {len(val_errors) - 10} more")
        print(f"\n{Fore.RED}Fix: regenerate sequences with --sender-name, --sender-title, --sender-company.{Style.RESET_ALL}")
        sys.exit(1)

    due = get_due_emails(sequences, state)
    remaining = daily_limit - state.get("sent_today", 0)
    due = due[:remaining]

    if not due:
        print(f"{Fore.YELLOW}No emails due today.{Style.RESET_ALL}")
        print(f"Sent today: {state.get('sent_today', 0)}/{daily_limit}")
        return

    first_seq = sequences[0]
    sender_name = first_seq.get("sender_name", email.split("@")[0].replace(".", " ").title())
    sender_email = first_seq.get("sender_email", "").strip() or email
    campaign_name = os.path.basename(sequences_csv)

    # ── Pre-send history check ───────────────────────────────────────────────
    history_skipped = []
    history_suppressed = []
    allowed = []
    for seq in due:
        to_email = seq.get("to_email", "").strip()
        is_supp, supp_reason = oh.is_suppressed(to_email)
        if is_supp:
            history_suppressed.append((to_email, seq.get("company_name", ""), supp_reason))
            seq["status"] = "skipped_suppressed"
            continue
        was_sent, sent_reason = oh.was_already_sent(to_email, campaign_name)
        if was_sent:
            history_skipped.append((to_email, seq.get("company_name", ""), sent_reason))
            seq["status"] = "skipped_duplicate"
            continue
        allowed.append(seq)
    due = allowed

    # ── Auto-backup before first live send ──────────────────────────────────
    if not dry_run:
        backup_path = sequences_csv.replace(".csv", "_backup.csv")
        if not os.path.exists(backup_path):
            import shutil
            shutil.copy2(sequences_csv, backup_path)
            print(f"{Fore.CYAN}📦 Auto-backup created: {backup_path}{Style.RESET_ALL}")

    # Build lookup for email #1 message_ids (for threading follow-ups)
    message_id_by_lead = {}
    for s in sequences:
        if s.get("email_number") in ("1", 1) and s.get("status") == "sent":
            message_id_by_lead[s.get("lead_id", "")] = s.get("message_id", "")

    # Domain throttle
    throttle = DomainThrottle(min_delay_seconds=45)

    print(f"{Fore.CYAN}{'DRY RUN — ' if dry_run else ''}{len(due)} emails to send today{Style.RESET_ALL}")
    print(f"Daily limit: {daily_limit} | Sent so far: {state.get('sent_today', 0)}")
    print(f"Sending as: {sender_name} <{sender_email}>")
    if history_skipped:
        print(f"{Fore.YELLOW}⚠️  {len(history_skipped)} skipped (already sent in history){Style.RESET_ALL}")
    if history_suppressed:
        print(f"{Fore.RED}🚫 {len(history_suppressed)} suppressed (opted-out/bounced){Style.RESET_ALL}")
    print()

    sent_count = 0
    failed_count = 0
    throttled_count = 0

    for seq in due:
        to_email = seq.get("to_email", "")
        subject = seq.get("subject", "")
        body = seq.get("body", "")
        email_num = seq.get("email_number", "1")
        company = seq.get("company_name", "")
        spam = seq.get("spam_warnings", "")
        lead_id = seq.get("lead_id", "")

        if dry_run:
            print(f"{Fore.BLUE}[DRY RUN]{Style.RESET_ALL} "
                  f"Email #{email_num} → {to_email} ({company})")
            print(f"  Subject: {subject[:70]}")
            print(f"  Body: {body[:100]}...")
            if spam:
                print(f"  {Fore.YELLOW}Spam words: {spam}{Style.RESET_ALL}")
            print()
            sent_count += 1
            continue

        # Domain throttling
        domain = extract_domain(to_email)
        if domain and not throttle.can_send(domain):
            wait_sec = throttle.time_until_next(domain)
            if wait_sec > 0:
                print(f"  {Fore.YELLOW}Domain throttle: waiting {wait_sec:.0f}s for {domain}{Style.RESET_ALL}")
                time.sleep(wait_sec)
        if domain:
            throttle.record_send(domain)

        # Threading: for follow-ups, reference email #1's message_id
        parent_message_id = ""
        if int(email_num) > 1:
            parent_message_id = message_id_by_lead.get(lead_id, "")

        result = send_email_smtp(config, to_email, subject, body, sender_name, sender_email, parent_message_id, compliance_cfg=compliance_cfg)

        if result["status"] == "sent":
            seq["status"] = "sent"
            seq["sent_at"] = datetime.now().isoformat()
            if result.get("message_id"):
                seq["message_id"] = result["message_id"]
                # Store for potential follow-up threading
                if int(email_num) == 1:
                    message_id_by_lead[lead_id] = result["message_id"]
            sent_count += 1
            state["sent_today"] = state.get("sent_today", 0) + 1
            print(f"{Fore.GREEN}✓{Style.RESET_ALL} Sent #{email_num} to {to_email} ({company})")
            # Update global history
            oh.record_contact(
                email=to_email,
                company_name=company,
                campaign=campaign_name,
                status="sent",
                subject=subject,
            )
        else:
            failed_count += 1
            seq["status"] = "failed"
            print(f"{Fore.RED}✗{Style.RESET_ALL} Failed #{email_num} to {to_email}: {result['status']}")
            oh.record_contact(
                email=to_email,
                company_name=company,
                campaign=campaign_name,
                status="failed",
            )

        time.sleep(random.uniform(2, 3))

    save_state(state)
    _flush_csv(sequences_csv, sequences)

    print()
    print(f"{Fore.CYAN}Summary:{Style.RESET_ALL}")
    print(f"  Sent: {sent_count}")
    if not dry_run:
        print(f"  Failed: {failed_count}")
        print(f"  Skipped (dup): {len(history_skipped)}")
        print(f"  Suppressed: {len(history_suppressed)}")
        print(f"  Domain-throttled waits: {throttled_count}")
        print(f"  Daily total: {state.get('sent_today', 0)}/{daily_limit}")


def _flush_csv(path: str, sequences: list):
    """Atomic CSV write using tempfile + os.replace to prevent corruption on crash."""
    dir_name = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile(
        mode="w", newline="", encoding="utf-8-sig",
        dir=dir_name, delete=False, suffix=".tmp"
    ) as f:
        if sequences:
            writer = csv.DictWriter(f, fieldnames=list(sequences[0].keys()))
            writer.writeheader()
            writer.writerows(sequences)
        tmp_path = f.name
    os.replace(tmp_path, path)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Google Workspace SMTP Outreach Sender")
    parser.add_argument("--check-auth", action="store_true",
                        help="Validate SMTP config and exit")
    parser.add_argument("--sequences", default=None,
                        help="Path to sequences CSV")
    parser.add_argument("--daily-limit", type=int, default=DEFAULT_DAILY_LIMIT,
                        help="Max emails per day (default: 450)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without sending")
    parser.add_argument("--to", default=None,
                        help="Recipient email for one-off send")
    parser.add_argument("--subject", default=None,
                        help="Subject for one-off send")
    parser.add_argument("--body", default=None,
                        help="Body for one-off send")
    parser.add_argument("--sender-name", default="",
                        help="Sender display name")
    parser.add_argument("--state-file", default=None,
                        help="Override path for .outreach_state.json (per-user campaigns)")
    parser.add_argument("--config-file", default=None,
                        help="Override path for .workspace_smtp_config.json (per-user SMTP)")
    args = parser.parse_args()

    # Override module-level paths if CLI args provided
    global CONFIG_FILE, STATE_FILE
    if args.config_file:
        CONFIG_FILE = args.config_file
    if args.state_file:
        STATE_FILE = args.state_file

    if args.check_auth:
        config, email, msg = get_auth_service()
        print(msg)
        sys.exit(0 if config else 1)

    config = _load_config()
    if not config:
        print(f"{Fore.RED}Error: {CONFIG_FILE} not found.{Style.RESET_ALL}")
        print("Create it first. See SKILL.md → 'Workspace SMTP (Never Expire)'")
        sys.exit(1)

    if args.to:
        if not args.subject or not args.body:
            print(f"{Fore.RED}Error: --to requires --subject and --body{Style.RESET_ALL}")
            sys.exit(1)
        send_one(config, args.to, args.subject, args.body, args.sender_name)
        return

    if not args.sequences:
        leads_dir = os.path.join(SKILL_DIR, "leads")
        if os.path.exists(leads_dir):
            files = sorted(
                [f for f in os.listdir(leads_dir) if f.startswith("sg_sequences_")],
                reverse=True,
            )
            if files:
                args.sequences = os.path.join(leads_dir, files[0])

    if not args.sequences or not os.path.exists(args.sequences):
        print(f"{Fore.RED}Error: No sequences file found. Run generate_sequences.py first.{Style.RESET_ALL}")
        sys.exit(1)

    send_sequences_from_csv(
        sequences_csv=args.sequences,
        daily_limit=args.daily_limit,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
