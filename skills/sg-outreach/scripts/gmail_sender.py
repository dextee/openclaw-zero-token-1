#!/usr/bin/env python3
"""Gmail API sender for SG Outreach sequences.

Uses Gmail API v1 via OAuth2. For production apps, refresh tokens are long-lived.
Auth files:
  - credentials/client_secret.json  (Google OAuth2 Desktop client)
  - .gmail_token.json               (cached access + refresh token)

Sending account: arvion.sg@gmail.com (personal Gmail, ~500/day API limit)

Usage:
    # Check auth status:
    python3 gmail_sender.py --check-auth

    # Send a single one-off email:
    python3 gmail_sender.py --to "recipient@example.com" \\
        --subject "Hello" --body "Body text." --sender-name "Arvion"

    # Dry run sequences:
    python3 gmail_sender.py --sequences leads/sg_sequences_20260407.csv --dry-run

    # Live send:
    python3 gmail_sender.py --sequences leads/sg_sequences_20260407.csv --daily-limit 450
"""

import argparse
import base64
import csv
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

# Import global outreach history and domain throttle
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
import outreach_history as oh
from domain_throttle import DomainThrottle, extract_domain

# Gmail API imports
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print(f"{Fore.RED}Error: Google API libraries not installed.{Style.RESET_ALL}")
    print("Run: pip install google-auth google-auth-oauthlib google-api-python-client")
    sys.exit(1)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(SKILL_DIR, ".gmail_token.json")
CREDENTIALS_FILE = os.path.join(SKILL_DIR, "credentials", "client_secret.json")
STATE_FILE = os.path.join(SKILL_DIR, ".outreach_state.json")
AUTH_STATUS_FILE = os.path.join(SKILL_DIR, ".auth_status.json")

DEFAULT_EMAIL = "arvion.sg@gmail.com"
MAX_RETRIES = 3
BACKOFF_DELAYS = [5, 15, 60]
PLACEHOLDER_PATTERN = re.compile(r"\{\{[^}]+\}\}")

COMPLIANCE_FILE = "/root/.openclaw/workspace/compliance/COMPLIANCE.json"


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


# ── Credentials & Auth Status ─────────────────────────────────────────────────

def _write_auth_status(ok: bool, message: str):
    """Persist auth status so the bot can read it without re-running a send."""
    with open(AUTH_STATUS_FILE, "w") as f:
        json.dump({
            "ok": ok,
            "message": message,
            "checked_at": datetime.now().isoformat(),
        }, f, indent=2)


def get_auth_service():
    """Load token, refresh if needed, return Gmail service + email."""
    if not os.path.exists(TOKEN_FILE):
        msg = (
            "AUTH_FAILED: Gmail not authenticated.\n"
            "Run: python3 scripts/gmail_sender.py --setup"
        )
        _write_auth_status(False, msg)
        return None, None, msg

    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                with open(TOKEN_FILE, "w") as f:
                    f.write(creds.to_json())
            except Exception as e:
                err = str(e)
                if "invalid_grant" in err:
                    msg = (
                        "AUTH_FAILED: Gmail token expired or revoked.\n"
                        "Fix: Run --generate-auth-url to get a new sign-in link."
                    )
                else:
                    msg = f"AUTH_FAILED: Could not refresh token — {err[:120]}"
                _write_auth_status(False, msg)
                return None, None, msg
        else:
            msg = (
                "AUTH_FAILED: Gmail token invalid and cannot refresh.\n"
                "Fix: Run --generate-auth-url to get a new sign-in link."
            )
            _write_auth_status(False, msg)
            return None, None, msg

    service = build("gmail", "v1", credentials=creds)
    try:
        profile = service.users().getProfile(userId="me").execute()
        email = profile.get("emailAddress", DEFAULT_EMAIL)
    except Exception:
        email = DEFAULT_EMAIL

    _write_auth_status(True, f"Auth OK — {email}")
    return service, email, "ok"


# ── OAuth2 Setup Helpers ──────────────────────────────────────────────────────

def generate_auth_url() -> str:
    """Generate OAuth2 auth URL for headless/manual code entry."""
    if not os.path.exists(CREDENTIALS_FILE):
        return ""

    flow = InstalledAppFlow.from_client_secrets_file(
        CREDENTIALS_FILE,
        SCOPES,
        redirect_uri="urn:ietf:wg:oauth:2.0:oob",
    )
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return auth_url


def exchange_code(code: str) -> str:
    """Exchange OAuth2 code for token and save it. Returns email address."""
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(f"Credentials file not found: {CREDENTIALS_FILE}")

    flow = InstalledAppFlow.from_client_secrets_file(
        CREDENTIALS_FILE,
        SCOPES,
        redirect_uri="urn:ietf:wg:oauth:2.0:oob",
    )
    flow.fetch_token(code=code)
    creds = flow.credentials

    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


# ── Send Email ────────────────────────────────────────────────────────────────

def create_message(to: str, subject: str, body: str, from_name: str, from_email: str,
                   parent_message_id: str = "") -> dict:
    body = re.sub(r"<[^>]+>", "", body)
    msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = to
    msg["from"] = f"{from_name} <{from_email}>"
    msg["subject"] = subject
    msg["Reply-To"] = from_email
    if parent_message_id:
        msg["In-Reply-To"] = parent_message_id
        msg["References"] = parent_message_id
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


def send_email(service, to: str, subject: str, body: str,
               from_name: str, from_email: str, parent_message_id: str = "",
               compliance_cfg: dict = None) -> dict:
    footer = build_footer(compliance_cfg, sender_email=from_email) if compliance_cfg else ""
    if footer:
        body = body + footer
    for attempt in range(MAX_RETRIES):
        try:
            message = create_message(to, subject, body, from_name, from_email, parent_message_id)
            result = service.users().messages().send(userId="me", body=message).execute()
            return {
                "message_id": result.get("id", ""),
                "thread_id": result.get("threadId", ""),
                "status": "sent",
            }
        except HttpError as e:
            status_code = e.resp.status if hasattr(e, "resp") else 0
            if status_code == 429:
                if attempt < MAX_RETRIES - 1:
                    delay = BACKOFF_DELAYS[attempt]
                    print(f"  {Fore.YELLOW}Rate limited, retrying in {delay}s... ({attempt+1}/{MAX_RETRIES}){Style.RESET_ALL}")
                    time.sleep(delay)
                    continue
                return {"message_id": "", "thread_id": "", "status": "quota_exceeded"}
            # 5xx errors are temporary — retry
            if status_code >= 500 and attempt < MAX_RETRIES - 1:
                delay = BACKOFF_DELAYS[attempt]
                print(f"  {Fore.YELLOW}Server error {status_code}, retrying in {delay}s... ({attempt+1}/{MAX_RETRIES}){Style.RESET_ALL}")
                time.sleep(delay)
                continue
            return {"message_id": "", "thread_id": "", "status": f"failed: {str(e)[:100]}"}
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                delay = BACKOFF_DELAYS[attempt]
                print(f"  {Fore.YELLOW}Temporary error, retrying in {delay}s... ({attempt+1}/{MAX_RETRIES}){Style.RESET_ALL}")
                time.sleep(delay)
                continue
            return {"message_id": "", "thread_id": "", "status": f"failed: {str(e)[:100]}"}
    return {"message_id": "", "thread_id": "", "status": "failed: max retries exceeded"}


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

def send_one(to: str, subject: str, body: str, sender_name: str = ""):
    service, email, msg = get_auth_service()
    if not service:
        print(msg)
        sys.exit(1)

    compliance_cfg = load_compliance()

    if not sender_name:
        sender_name = email.split("@")[0].capitalize()

    result = send_email(service, to, subject, body, sender_name, email, compliance_cfg=compliance_cfg)

    if result["status"] == "sent":
        print(f"{Fore.GREEN}SUCCESS: Email sent!{Style.RESET_ALL}")
        print(f"To: {to}")
        print(f"Subject: {subject}")
        print(f"From: {sender_name} <{email}>")
    elif result["status"] == "quota_exceeded":
        print(f"{Fore.RED}Quota exceeded! Stopping for today.{Style.RESET_ALL}")
        sys.exit(1)
    else:
        print(f"{Fore.RED}FAILED: {result['status']}{Style.RESET_ALL}")
        sys.exit(1)


# ── Send Sequences from CSV ───────────────────────────────────────────────────

def send_sequences_from_csv(sequences_csv: str, daily_limit: int = 450,
                             dry_run: bool = False):
    if not os.path.exists(sequences_csv):
        print(f"{Fore.RED}Error: Sequences file not found: {sequences_csv}{Style.RESET_ALL}")
        sys.exit(1)

    service, email, msg = get_auth_service()
    if not service:
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
    sender_name = first_seq.get("sender_name", email.split("@")[0].capitalize())
    sender_email = first_seq.get("sender_email", email)
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
    if history_skipped:
        print(f"{Fore.YELLOW}⚠️  {len(history_skipped)} skipped (already sent in history){Style.RESET_ALL}")
    if history_suppressed:
        print(f"{Fore.RED}🚫 {len(history_suppressed)} suppressed (opted-out/bounced){Style.RESET_ALL}")
    print()

    sent_count = 0
    failed_count = 0

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

        result = send_email(service, to_email, subject, body, sender_name, sender_email, parent_message_id, compliance_cfg=compliance_cfg)

        if result["status"] == "sent":
            seq["status"] = "sent"
            seq["sent_at"] = datetime.now().isoformat()
            if result.get("message_id"):
                seq["message_id"] = result["message_id"]
                if int(email_num) == 1:
                    message_id_by_lead[lead_id] = result["message_id"]
            if result.get("thread_id"):
                seq["thread_id"] = result["thread_id"]
            sent_count += 1
            state["sent_today"] = state.get("sent_today", 0) + 1
            print(f"{Fore.GREEN}✓{Style.RESET_ALL} Sent #{email_num} to {to_email} ({company})")
            oh.record_contact(
                email=to_email,
                company_name=company,
                campaign=campaign_name,
                status="sent",
                subject=subject,
            )
        elif result["status"] == "quota_exceeded":
            print(f"{Fore.RED}Quota exceeded — stopping for today.{Style.RESET_ALL}")
            break
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
        print(f"  Daily total: {state.get('sent_today', 0)}/{daily_limit}")


def _flush_csv(path: str, sequences: list):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        if sequences:
            writer = csv.DictWriter(f, fieldnames=list(sequences[0].keys()))
            writer.writeheader()
            writer.writerows(sequences)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gmail API Outreach Sender")
    parser.add_argument("--check-auth", action="store_true",
                        help="Validate Gmail auth and exit")
    parser.add_argument("--generate-auth-url", action="store_true",
                        help="Print OAuth2 sign-in URL for Telegram recovery")
    parser.add_argument("--exchange-code", metavar="CODE",
                        help="Exchange OAuth2 code for token (called by bot after user authorizes)")
    parser.add_argument("--sequences", default=None,
                        help="Path to sequences CSV")
    parser.add_argument("--daily-limit", type=int, default=450,
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
    args = parser.parse_args()

    if args.generate_auth_url:
        url = generate_auth_url()
        if not url:
            print(f"{Fore.RED}Error: {CREDENTIALS_FILE} not found.{Style.RESET_ALL}")
            sys.exit(1)
        print(url)
        return

    if args.exchange_code:
        try:
            email = exchange_code(args.exchange_code)
            print(f"{Fore.GREEN}SUCCESS: Authenticated as {email}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}FAILED: {e}{Style.RESET_ALL}")
            sys.exit(1)
        return

    if args.check_auth:
        service, email, msg = get_auth_service()
        print(msg)
        sys.exit(0 if service else 1)

    if args.to:
        if not args.subject or not args.body:
            print(f"{Fore.RED}Error: --to requires --subject and --body{Style.RESET_ALL}")
            sys.exit(1)
        send_one(args.to, args.subject, args.body, args.sender_name)
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
