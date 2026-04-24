#!/usr/bin/env python3
"""Google Workspace IMAP reply tracker for SG Outreach sequences.

Uses IMAP4_SSL (port 993) with an App Password — tokens NEVER expire.
Correlates replies by searching for emails FROM the recipient address
that arrived AFTER the sequence `sent_at` timestamp.

Auth file (shared with workspace_smtp_sender.py):
  - .workspace_smtp_config.json

Usage:
    # Check for replies (looks back 30 days by default):
    python3 workspace_imap_tracker.py --sequences leads/sg_sequences_20260408.csv

    # Generate performance report:
    python3 workspace_imap_tracker.py --sequences leads/sg_sequences_20260408.csv --report
"""

import argparse
import csv
import email
import email.policy
import imaplib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(SKILL_DIR, ".workspace_smtp_config.json")

# Import global outreach history
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
import outreach_history as oh

DEFAULT_LOOKBACK_DAYS = 30


def _load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _connect_imap(config: dict):
    host = config.get("imap_host", "imap.gmail.com")
    port = int(config.get("imap_port", 993))
    email_addr = config.get("email", "").strip()
    password = config.get("app_password", "").strip()

    mail = imaplib.IMAP4_SSL(host, port)
    mail.login(email_addr, password)
    mail.select("inbox")
    return mail


def _search_replies_from(mail: imaplib.IMAP4_SSL, from_email: str, since_date: datetime) -> list[dict]:
    """Search inbox for emails from `from_email` since `since_date`."""
    replies = []
    # IMAP SEARCH date format: DD-Mon-YYYY
    since_str = since_date.strftime("%d-%b-%Y")
    query = f'(FROM "{from_email}" SINCE "{since_str}")'
    status, data = mail.search(None, query)
    if status != "OK":
        return replies

    msg_ids = data[0].split()
    for msg_id in msg_ids:
        status, fetch_data = mail.fetch(msg_id, "(RFC822)")
        if status != "OK" or not fetch_data:
            continue
        raw_msg = fetch_data[0][1]
        if not raw_msg:
            continue
        parsed = email.message_from_bytes(raw_msg, policy=email.policy.default)
        date_hdr = parsed.get("Date", "")
        try:
            received = email.utils.parsedate_to_datetime(date_hdr)
            if received.tzinfo:
                received = received.replace(tzinfo=None)
        except Exception:
            received = datetime.now()

        body = ""
        if parsed.is_multipart():
            for part in parsed.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    try:
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    except Exception:
                        pass
                    break
        else:
            try:
                body = parsed.get_payload(decode=True).decode("utf-8", errors="ignore")
            except Exception:
                pass

        replies.append({
            "from": from_email,
            "subject": parsed.get("Subject", ""),
            "received": received,
            "body": body,
        })
    return replies


def classify_reply(body: str, subject: str) -> str:
    """Classify reply sentiment."""
    text = f"{subject} {body}".lower()
    positive = ["interested", "yes", "book", "schedule", "meeting", "call", "demo", "send", "details", "worth exploring"]
    negative = ["unsubscribe", "not interested", "remove", "stop", "no thanks", "wrong person", "never", "don't contact"]
    ooo = ["out of office", "on leave", "away until", "vacation", "annual leave", "maternity leave", "paternity leave"]

    for kw in ooo:
        if kw in text:
            return "OOO"
    for kw in negative:
        if kw in text:
            return "Negative"
    for kw in positive:
        if kw in text:
            return "Positive"
    return "Neutral"


def check_bounces(mail: imaplib.IMAP4_SSL, since_date: datetime) -> list[dict]:
    """Search inbox for bounce notifications and return list of bounced emails."""
    bounces = []
    since_str = since_date.strftime("%d-%b-%Y")
    # Search for delivery status notifications and mailer daemon bounces
    queries = [
        f'(SUBJECT "Delivery Status Notification" SINCE "{since_str}")',
        f'(FROM "mailer-daemon" SINCE "{since_str}")',
        f'(FROM "Mail Delivery Subsystem" SINCE "{since_str}")',
    ]
    seen_ids = set()
    for query in queries:
        status, data = mail.search(None, query)
        if status != "OK":
            continue
        for msg_id in data[0].split():
            if msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)
            status, fetch_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK" or not fetch_data:
                continue
            raw_msg = fetch_data[0][1]
            if not raw_msg:
                continue
            parsed = email.message_from_bytes(raw_msg, policy=email.policy.default)
            body = ""
            if parsed.is_multipart():
                for part in parsed.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        except Exception:
                            pass
                        break
            else:
                try:
                    body = parsed.get_payload(decode=True).decode("utf-8", errors="ignore")
                except Exception:
                    pass

            # Try to extract the original recipient email from bounce body
            bounced_email = ""
            # Common patterns in bounce messages
            for line in body.splitlines():
                line_lower = line.lower()
                if "original-recipient:" in line_lower or "final-recipient:" in line_lower:
                    if "rfc822;" in line_lower:
                        bounced_email = line.split("rfc822;")[-1].strip().lower()
                    else:
                        bounced_email = line.split(":")[-1].strip().lower()
                    break
                if "to:" in line_lower and "@" in line:
                    bounced_email = line.split(":")[-1].strip().lower()
                    break

            # Determine hard vs soft bounce
            is_hard = any(kw in body.lower() for kw in [
                "550", "551", "552", "553", "no such user", "user unknown",
                "mailbox unavailable", "recipient address rejected", "does not exist"
            ])
            bounces.append({
                "email": bounced_email,
                "is_hard": is_hard,
                "subject": parsed.get("Subject", ""),
                "body_snippet": body[:500],
            })
    return bounces


def check_replies(sequences_csv: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> dict:
    config = _load_config()
    if not config:
        print(f"{Fore.RED}Error: {CONFIG_FILE} not found.{Style.RESET_ALL}")
        sys.exit(1)

    with open(sequences_csv, "r", encoding="utf-8-sig") as f:
        sequences = list(csv.DictReader(f))

    sent_sequences = [
        s for s in sequences
        if s.get("status") == "sent" and s.get("sent_at") and s.get("to_email")
    ]

    if not sent_sequences:
        print(f"{Fore.YELLOW}No sent emails found in {sequences_csv}{Style.RESET_ALL}")
        return {"replied": 0, "pending": len(sequences)}

    print(f"{Fore.CYAN}Checking {len(sent_sequences)} sent emails for replies via IMAP...{Style.RESET_ALL}")

    mail = _connect_imap(config)
    now = datetime.now()
    cutoff = now - timedelta(days=lookback_days)

    replied_count = 0
    sequences_to_pause = []

    # Group by recipient email to avoid duplicate IMAP searches
    by_recipient: dict[str, list[dict]] = defaultdict(list)
    for seq in sent_sequences:
        by_recipient[seq["to_email"].lower().strip()].append(seq)

    for recipient, seqs in by_recipient.items():
        # Find the earliest sent_at among sequences to this recipient
        earliest_sent = min(
            datetime.fromisoformat(s["sent_at"])
            for s in seqs if s.get("sent_at")
        )
        search_since = max(cutoff, earliest_sent)

        try:
            replies = _search_replies_from(mail, recipient, search_since)
        except Exception as e:
            print(f"  {Fore.YELLOW}⚠ IMAP search failed for {recipient}: {e}{Style.RESET_ALL}")
            continue

        if not replies:
            continue

        # Sort replies by received time
        replies.sort(key=lambda r: r["received"])

        for seq in seqs:
            sent_at = datetime.fromisoformat(seq["sent_at"])
            # Find first reply that arrived after this sequence was sent
            for reply in replies:
                if reply["received"] > sent_at:
                    seq["replied"] = "true"
                    seq["replied_at"] = reply["received"].isoformat()
                    sentiment = classify_reply(reply["body"], reply["subject"])
                    seq["reply_sentiment"] = sentiment
                    replied_count += 1
                    if sentiment in ("Negative", "OOO"):
                        sequences_to_pause.append(seq)
                    if sentiment == "Negative":
                        oh.suppress_email(seq.get("to_email", ""), "negative_reply")
                    break

    # ── Bounce detection ─────────────────────────────────────────────────────
    bounce_count = 0
    try:
        bounces = check_bounces(mail, cutoff)
        for bounce in bounces:
            bounced_email = bounce.get("email", "").lower().strip()
            if not bounced_email:
                continue
            is_hard = bounce.get("is_hard", True)
            if is_hard:
                oh.record_contact(bounced_email, status="bounced")
                bounce_count += 1
            else:
                # Soft bounce — only record if not already in history
                entry = oh.get_history_entry(bounced_email)
                if not entry:
                    oh.record_contact(bounced_email, status="failed")
                    bounce_count += 1
    except Exception as e:
        print(f"{Fore.YELLOW}⚠ Bounce check failed: {e}{Style.RESET_ALL}")

    mail.logout()

    # Write updated CSV
    with open(sequences_csv, "w", newline="", encoding="utf-8-sig") as f:
        if sequences:
            writer = csv.DictWriter(f, fieldnames=list(sequences[0].keys()))
            writer.writeheader()
            writer.writerows(sequences)

    print(f"{Fore.GREEN}✓{Style.RESET_ALL} {replied_count} new replies found")
    if bounce_count:
        print(f"{Fore.RED}📨 {bounce_count} bounces detected and suppressed{Style.RESET_ALL}")
    if sequences_to_pause:
        print(f"{Fore.YELLOW}⚠ {len(sequences_to_pause)} sequences flagged for pause (Negative / OOO){Style.RESET_ALL}")

    return {"replied": replied_count, "pending": len(sequences) - len(sent_sequences), "bounces": bounce_count}


def generate_report(sequences_csv: str):
    with open(sequences_csv, "r", encoding="utf-8-sig") as f:
        sequences = list(csv.DictReader(f))

    total = len(sequences)
    sent = [s for s in sequences if s.get("status") == "sent"]
    replied = [s for s in sequences if s.get("replied") == "true"]
    pending = [s for s in sequences if s.get("status") == "pending"]

    tier_counts = Counter(s.get("sequence_tier", "?") for s in sequences)
    tier_sent = Counter(s.get("sequence_tier", "?") for s in sent)
    tier_replied = Counter(s.get("sequence_tier", "?") for s in replied)

    variant_counts = Counter(s.get("template_variant", "generic_variant") for s in sequences)
    variant_replied = Counter(s.get("template_variant", "generic_variant") for s in replied)

    sentiment_counts = Counter(s.get("reply_sentiment", "Unknown") for s in replied)

    print()
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  SG Outreach Report — {os.path.basename(sequences_csv)}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print()
    print(f"Total sequences:   {total}")
    print(f"Sent:              {len(sent)} ({len(sent)/total*100:.1f}%)")
    print(f"Replied:           {len(replied)} ({len(replied)/len(sent)*100:.1f}% of sent)")
    print(f"Pending:           {len(pending)}")
    print()
    print("By Tier:")
    for tier in ("A", "B", "C"):
        t_total = tier_counts.get(tier, 0)
        t_sent = tier_sent.get(tier, 0)
        t_replied = tier_replied.get(tier, 0)
        reply_rate = t_replied / t_sent * 100 if t_sent else 0
        print(f"  Tier {tier}: {t_total} seqs | {t_sent} sent | {t_replied} replied ({reply_rate:.1f}%)")
    print()
    print("By Variant (top 5):")
    for variant, count in variant_counts.most_common(5):
        v_replied = variant_replied.get(variant, 0)
        print(f"  {variant}: {count} seqs | {v_replied} replies")
    print()
    print("Reply Sentiment:")
    for senti, count in sentiment_counts.most_common():
        print(f"  {senti}: {count}")
    print()
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Workspace IMAP Reply Tracker")
    parser.add_argument("--sequences", required=True, help="Path to sequences CSV")
    parser.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_DAYS,
                        help="Days to look back for replies (default: 30)")
    parser.add_argument("--report", action="store_true",
                        help="Generate performance report after checking replies")
    args = parser.parse_args()

    check_replies(args.sequences, lookback_days=args.lookback)

    if args.report:
        generate_report(args.sequences)


if __name__ == "__main__":
    main()
