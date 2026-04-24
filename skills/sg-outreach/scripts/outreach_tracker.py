#!/usr/bin/env python3
"""SG Outreach — Reply/Bounce Tracker and Report Generator.

Checks Gmail inbox for replies to sent sequences and generates
performance reports by tier, variant, and subject line.

Usage:
    python3 outreach_tracker.py --sequences leads/sg_sequences_20260407.csv --check-replies
    python3 outreach_tracker.py --sequences leads/sg_sequences_20260407.csv --report
"""

import argparse
import csv
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    print(f"{Fore.RED}Error: Google API libraries not installed.{Style.RESET_ALL}")
    print("Run: pip install google-auth google-auth-oauthlib google-api-python-client")
    sys.exit(1)

# Import global outreach history
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import outreach_history as oh

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
TOKEN_FILE = ".gmail_token.json"


def get_service():
    """Get authenticated Gmail service."""
    token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", TOKEN_FILE)
    if not os.path.exists(token_path):
        print(f"{Fore.RED}Error: No Gmail token found. Run gmail_sender.py --setup first.{Style.RESET_ALL}")
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    return build("gmail", "v1", credentials=creds)


def check_replies(sequences_csv: str, lookback_days: int = 7) -> dict:
    """Check Gmail inbox for replies to sent threads.

    Updates sequences CSV in-place with replied timestamps.
    Returns summary dict.
    """
    service = get_service()

    with open(sequences_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        sequences = list(reader)

    # Get sent emails with thread_id
    sent_sequences = [
        s for s in sequences
        if s.get("status") == "sent" and s.get("thread_id")
    ]

    if not sent_sequences:
        print(f"{Fore.YELLOW}No sent emails with thread_id found.{Style.RESET_ALL}")
        return {"replied": 0, "pending": len(sequences) - len(sent_sequences)}

    print(f"{Fore.CYAN}Checking {len(sent_sequences)} sent emails for replies...{Style.RESET_ALL}")

    replied_count = 0
    sequences_to_pause = []

    for seq in sent_sequences:
        thread_id = seq.get("thread_id", "")
        to_email = seq.get("to_email", "")
        company = seq.get("company_name", "")

        try:
            # Search for replies in this thread
            thread = service.users().threads().get(
                userId="me",
                id=thread_id,
                format="minimal",
            ).execute()

            messages = thread.get("messages", [])
            if len(messages) > 1:
                # More than 1 message means there's a reply
                last_msg = messages[-1]
                sender = ""
                for header in last_msg.get("payload", {}).get("headers", []):
                    if header.get("name") == "From":
                        sender = header.get("value", "")
                        break

                # Check if reply is FROM the prospect (not us)
                if to_email.lower() not in sender.lower():
                    if seq.get("replied") != "True":
                        seq["replied"] = "True"
                        seq["status"] = "replied"
                        seq["replied_at"] = datetime.now().isoformat()
                        replied_count += 1
                        print(f"{Fore.GREEN}✓ Reply from {company} ({to_email}) — {sender[:50]}{Style.RESET_ALL}")
                        sequences_to_pause.append(seq)

                    # Check for unsubscribe
                    body_snippet = ""
                    for part_id in last_msg.get("payload", {}).get("parts", [{}]):
                        if part_id.get("mimeType") == "text/plain":
                            data = part_id.get("body", {}).get("data", "")
                            if data:
                                import base64
                                try:
                                    body_snippet = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                                except Exception:
                                    pass
                            break

                    if any(word in body_snippet.lower() for word in
                           ["unsubscribe", "remove me", "opt out", "stop", "not interested"]):
                        seq["status"] = "unsubscribed"
                        print(f"{Fore.RED}⚠️  Unsubscribe from {company}{Style.RESET_ALL}")
                        oh.suppress_email(to_email, "unsubscribed")

        except HttpError as e:
            if "404" in str(e) or "not found" in str(e).lower():
                # Thread deleted or inaccessible
                pass
            else:
                print(f"{Fore.YELLOW}⚠️  Error checking {company}: {str(e)[:80]}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.YELLOW}⚠️  Error checking {company}: {str(e)[:80]}{Style.RESET_ALL}")

        # Rate limit
        time.sleep(0.5)

    # ── Bounce detection via Gmail API ───────────────────────────────────────
    bounce_count = 0
    try:
        # Search for bounce notifications in inbox
        bounce_query = (
            'subject:"Delivery Status Notification" OR '
            'from:mailer-daemon OR from:"Mail Delivery Subsystem"'
        )
        bounce_results = service.users().messages().list(
            userId="me", q=bounce_query, maxResults=50
        ).execute()
        bounce_msgs = bounce_results.get("messages", [])
        for bm in bounce_msgs:
            try:
                msg = service.users().messages().get(
                    userId="me", id=bm["id"], format="full"
                ).execute()
                parts = msg.get("payload", {}).get("parts", [msg.get("payload", {})])
                body = ""
                for part in parts:
                    if part.get("mimeType") == "text/plain":
                        data = part.get("body", {}).get("data", "")
                        if data:
                            import base64
                            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                        break
                # Extract bounced email
                bounced_email = ""
                for line in body.splitlines():
                    line_lower = line.lower()
                    if "original-recipient:" in line_lower or "final-recipient:" in line_lower:
                        if "rfc822;" in line_lower:
                            bounced_email = line.split("rfc822;")[-1].strip().lower()
                        else:
                            bounced_email = line.split(":")[-1].strip().lower()
                        break
                if bounced_email:
                    is_hard = any(kw in body.lower() for kw in [
                        "550", "551", "552", "553", "no such user", "user unknown",
                        "mailbox unavailable", "recipient address rejected", "does not exist"
                    ])
                    if is_hard:
                        oh.record_contact(bounced_email, status="bounced")
                        bounce_count += 1
            except Exception:
                continue
    except Exception as e:
        print(f"{Fore.YELLOW}⚠ Bounce check skipped: {e}{Style.RESET_ALL}")

    # Save updated CSV
    with open(sequences_csv, "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = list(sequences[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sequences)

    pending = sum(1 for s in sequences if s.get("status") in ("pending", "sent"))

    print(f"\n{Fore.CYAN}Reply Check Complete:{Style.RESET_ALL}")
    print(f"  Replies found: {replied_count}")
    if bounce_count:
        print(f"  Bounces detected: {bounce_count}")
    print(f"  Pending: {pending}")
    print(f"  Sequences to pause: {len(sequences_to_pause)}")

    return {
        "replied": replied_count,
        "pending": pending,
        "sequences_to_pause": sequences_to_pause,
        "bounces": bounce_count,
    }


def generate_report(sequences_csv: str):
    """Generate formatted outreach performance report."""
    if not os.path.exists(sequences_csv):
        print(f"{Fore.RED}Error: Sequences file not found: {sequences_csv}{Style.RESET_ALL}")
        sys.exit(1)

    with open(sequences_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        sequences = list(reader)

    if not sequences:
        print(f"{Fore.YELLOW}No sequences found.{Style.RESET_ALL}")
        return

    # Count statuses
    status_counts = Counter(s.get("status", "") for s in sequences)
    total = len(sequences)
    sent = status_counts.get("sent", 0) + status_counts.get("replied", 0)
    replied = status_counts.get("replied", 0)
    response_rate = (replied / sent * 100) if sent > 0 else 0

    # By tier
    tier_stats = defaultdict(lambda: {"sent": 0, "replied": 0})
    for s in sequences:
        tier = s.get("sequence_tier", "unknown")
        if s.get("status") in ("sent", "replied"):
            tier_stats[tier]["sent"] += 1
        if s.get("status") == "replied":
            tier_stats[tier]["replied"] += 1

    # By template variant
    variant_stats = defaultdict(lambda: {"sent": 0, "replied": 0})
    for s in sequences:
        variant = s.get("template_variant", "unknown")
        if s.get("status") in ("sent", "replied"):
            variant_stats[variant]["sent"] += 1
        if s.get("status") == "replied":
            variant_stats[variant]["replied"] += 1

    # By subject line
    subject_stats = defaultdict(lambda: {"sent": 0, "replied": 0})
    for s in sequences:
        subj = s.get("subject", "")[:60]
        if s.get("status") in ("sent", "replied"):
            subject_stats[subj]["sent"] += 1
        if s.get("status") == "replied":
            subject_stats[subj]["replied"] += 1

    # Print report
    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}         SG OUTREACH PERFORMANCE REPORT{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Total emails: {total}")
    print(f"Sent: {sent}")
    print(f"Replied: {replied}")
    print(f"Response rate: {response_rate:.1f}%")
    print(f"Pending: {status_counts.get('pending', 0)}")
    print(f"Unsubscribed: {status_counts.get('unsubscribed', 0)}")
    print()

    print(f"{Fore.YELLOW}Response Rate by Tier:{Style.RESET_ALL}")
    for tier in sorted(tier_stats.keys()):
        stats = tier_stats[tier]
        rate = (stats["replied"] / stats["sent"] * 100) if stats["sent"] > 0 else 0
        print(f"  Tier {tier}: {stats['replied']}/{stats['sent']} ({rate:.1f}%)")
    print()

    print(f"{Fore.YELLOW}Response Rate by Variant:{Style.RESET_ALL}")
    for variant, stats in sorted(variant_stats.items(), key=lambda x: -x[1]["replied"]):
        rate = (stats["replied"] / stats["sent"] * 100) if stats["sent"] > 0 else 0
        print(f"  {variant}: {stats['replied']}/{stats['sent']} ({rate:.1f}%)")
    print()

    print(f"{Fore.YELLOW}Best Subject Lines (by replies):{Style.RESET_ALL}")
    sorted_subjects = sorted(subject_stats.items(), key=lambda x: -x[1]["replied"])
    for subj, stats in sorted_subjects[:5]:
        rate = (stats["replied"] / stats["sent"] * 100) if stats["sent"] > 0 else 0
        print(f"  [{stats['replied']}/{stats['sent']} {rate:.0f}%] {subj}")
    print()

    # Leads for human follow-up
    replied_leads = [s for s in sequences if s.get("replied") == "True"]
    if replied_leads:
        print(f"{Fore.GREEN}Leads to Flag for Human Follow-up ({len(replied_leads)}):{Style.RESET_ALL}")
        for lead in replied_leads:
            print(f"  - {lead.get('company_name', 'Unknown')} ({lead.get('to_email', '')})")
        print()

    # Leads to remove
    removed = [s for s in sequences if s.get("status") in ("unsubscribed",)]
    if removed:
        print(f"{Fore.RED}Leads to Remove ({len(removed)}):{Style.RESET_ALL}")
        for lead in removed:
            print(f"  - {lead.get('company_name', 'Unknown')} ({lead.get('to_email', '')})")


def main():
    parser = argparse.ArgumentParser(description="SG Outreach Tracker")
    parser.add_argument("--sequences", default=None, help="Path to sequences CSV")
    parser.add_argument("--check-replies", action="store_true", help="Check for replies")
    parser.add_argument("--report", action="store_true", help="Generate performance report")
    parser.add_argument("--lookback", type=int, default=7, help="Days to look back for replies")
    args = parser.parse_args()

    if not args.sequences:
        leads_dir = "leads"
        if os.path.exists(leads_dir):
            files = [f for f in os.listdir(leads_dir) if f.startswith("sg_sequences_")]
            if files:
                files.sort(reverse=True)
                args.sequences = os.path.join(leads_dir, files[0])

    if not args.sequences or not os.path.exists(args.sequences):
        print(f"{Fore.RED}Error: No sequences file found.{Style.RESET_ALL}")
        sys.exit(1)

    if args.check_replies:
        check_replies(args.sequences, args.lookback)

    if args.report:
        generate_report(args.sequences)

    if not args.check_replies and not args.report:
        parser.print_help()


if __name__ == "__main__":
    main()
