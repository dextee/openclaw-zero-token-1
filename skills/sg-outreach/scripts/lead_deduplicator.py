#!/usr/bin/env python3
"""SG Outreach — Lead Deduplicator.

Compares a new leads CSV against all previous sequence campaigns and the
global outreach history to remove duplicates, already-contacted leads, and
suppressed emails.

Usage:
    python3 lead_deduplicator.py \
        --input leads/sg_leads_enriched.csv \
        --output leads/sg_leads_deduped.csv

Optional:
    --previous leads/sg_sequences_20260401.csv   (specific previous campaign)
    --skip-history                              (skip global history check)
"""

import argparse
import csv
import os
import sys
from datetime import datetime

from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEADS_DIR = os.path.join(SKILL_DIR, "leads")

sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
import outreach_history as oh


def _get_email(row: dict) -> str:
    for col in ("email", "Email", "EMAIL", "direct_email"):
        val = row.get(col, "").strip()
        if val:
            return val.lower()
    return ""


def _get_company(row: dict) -> str:
    return row.get("company_name", "").strip().lower()


def scan_previous_sequences(leads_dir: str) -> tuple[set, set]:
    """Scan all sg_sequences_*.csv files and return (emails_seen, companies_seen)."""
    emails = set()
    companies = set()
    if not os.path.exists(leads_dir):
        return emails, companies

    for fname in os.listdir(leads_dir):
        if not fname.startswith("sg_sequences_") or not fname.endswith(".csv"):
            continue
        path = os.path.join(leads_dir, fname)
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    email = row.get("to_email", "").strip().lower()
                    company = row.get("company_name", "").strip().lower()
                    if email:
                        emails.add(email)
                    if company:
                        companies.add(company)
        except Exception:
            continue
    return emails, companies


def deduplicate(input_path: str, output_path: str, previous_csv: str = "",
                skip_history: bool = False):
    if not os.path.exists(input_path):
        print(f"{Fore.RED}Error: Input file not found: {input_path}{Style.RESET_ALL}")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"{Fore.YELLOW}No leads in input file.{Style.RESET_ALL}")
        sys.exit(0)

    print(f"{Fore.CYAN}Loaded {len(rows)} leads from {input_path}{Style.RESET_ALL}")

    # Gather previous contacts
    prev_emails = set()
    prev_companies = set()

    if previous_csv and os.path.exists(previous_csv):
        with open(previous_csv, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                email = row.get("to_email", "").strip().lower()
                company = row.get("company_name", "").strip().lower()
                if email:
                    prev_emails.add(email)
                if company:
                    prev_companies.add(company)
        print(f"Checked specific previous campaign: {previous_csv}")
    else:
        prev_emails, prev_companies = scan_previous_sequences(LEADS_DIR)
        seq_count = len([f for f in os.listdir(LEADS_DIR)
                        if f.startswith("sg_sequences_") and f.endswith(".csv")]) if os.path.exists(LEADS_DIR) else 0
        print(f"Scanned {seq_count} previous sequence files in {LEADS_DIR}")

    history = oh._load_history() if not skip_history else {}
    history_emails = set(history.keys())

    kept = []
    removed_dup_email = []
    removed_dup_company = []
    removed_history = []
    removed_suppressed = []

    for row in rows:
        email = _get_email(row)
        company = _get_company(row)

        if not email and not company:
            continue

        # Check suppression first (most serious)
        if email:
            is_supp, supp_reason = oh.is_suppressed(email)
            if is_supp:
                removed_suppressed.append((email, company, supp_reason))
                continue

        # Check global history
        if email and email in history_emails:
            entry = history[email]
            removed_history.append((email, company, entry.get("status", ""), entry.get("last_sent_at", "")))
            continue

        # Check previous sequences by email
        if email and email in prev_emails:
            removed_dup_email.append((email, company))
            continue

        # Check previous sequences by company name (fuzzy — same company, different email)
        if company and company in prev_companies:
            removed_dup_company.append((email, company))
            continue

        kept.append(row)

    # Write output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=kept[0].keys() if kept else rows[0].keys())
        writer.writeheader()
        writer.writerows(kept)

    # Report
    print()
    print(f"{Fore.CYAN}{'='*50}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}DEDUPLICATION REPORT{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*50}{Style.RESET_ALL}")
    print(f"Input:    {len(rows)} leads")
    print(f"Output:   {len(kept)} leads ({len(kept)/len(rows)*100:.1f}% kept)")
    print(f"Removed:  {len(rows) - len(kept)} leads")
    print()

    if removed_suppressed:
        print(f"{Fore.RED}🚫 Suppressed ({len(removed_suppressed)}):{Style.RESET_ALL}")
        for email, company, reason in removed_suppressed[:10]:
            print(f"  - {company or 'Unknown'} <{email}>: {reason}")
        if len(removed_suppressed) > 10:
            print(f"  ... and {len(removed_suppressed) - 10} more")
        print()

    if removed_history:
        print(f"{Fore.YELLOW}📚 In global history ({len(removed_history)}):{Style.RESET_ALL}")
        for email, company, status, last_sent in removed_history[:10]:
            print(f"  - {company or 'Unknown'} <{email}>: {status} on {last_sent}")
        if len(removed_history) > 10:
            print(f"  ... and {len(removed_history) - 10} more")
        print()

    if removed_dup_email:
        print(f"{Fore.YELLOW}📧 Duplicate email ({len(removed_dup_email)}):{Style.RESET_ALL}")
        for email, company in removed_dup_email[:10]:
            print(f"  - {company or 'Unknown'} <{email}>")
        if len(removed_dup_email) > 10:
            print(f"  ... and {len(removed_dup_email) - 10} more")
        print()

    if removed_dup_company:
        print(f"{Fore.YELLOW}🏢 Duplicate company ({len(removed_dup_company)}):{Style.RESET_ALL}")
        for email, company in removed_dup_company[:10]:
            print(f"  - {company or 'Unknown'} <{email}>")
        if len(removed_dup_company) > 10:
            print(f"  ... and {len(removed_dup_company) - 10} more")
        print()

    print(f"{Fore.GREEN}✓ Deduplicated file written to:{Style.RESET_ALL} {output_path}")


def main():
    parser = argparse.ArgumentParser(description="SG Outreach Lead Deduplicator")
    parser.add_argument("--input", required=True, help="New leads CSV")
    parser.add_argument("--output", required=True, help="Deduplicated output CSV")
    parser.add_argument("--previous", default="", help="Specific previous sequences CSV to compare")
    parser.add_argument("--skip-history", action="store_true", help="Skip global history check")
    args = parser.parse_args()

    deduplicate(args.input, args.output, args.previous, args.skip_history)


if __name__ == "__main__":
    main()
