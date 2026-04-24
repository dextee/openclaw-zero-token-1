#!/usr/bin/env python3
"""Export SG Outreach sequences to Saleshandy CSV import format.

Saleshandy builds sequences internally, so we export one row per prospect
(not per email) with custom fields for personalization.

Usage:
    python3 export_saleshandy.py leads/sg_sequences_20260407.csv
    python3 export_saleshandy.py leads/sg_sequences_20260407.csv --output leads/saleshandy_import.csv
"""

import argparse
import csv
import os
import sys
from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)


def export_to_saleshandy(sequences_csv: str, output_path: str):
    """Convert sequences CSV to Saleshandy import format."""
    if not os.path.exists(sequences_csv):
        print(f"{Fore.RED}Error: Sequences file not found: {sequences_csv}{Style.RESET_ALL}")
        sys.exit(1)

    with open(sequences_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        sequences = list(reader)

    if not sequences:
        print(f"{Fore.YELLOW}No sequences found.{Style.RESET_ALL}")
        return

    # Get only email_number == 1 rows (one per prospect)
    prospects = {}
    for seq in sequences:
        if int(seq.get("email_number", 1)) == 1:
            lead_id = seq.get("lead_id", "")
            prospects[lead_id] = seq

    print(f"{Fore.CYAN}Found {len(prospects)} unique prospects{Style.RESET_ALL}")

    # Saleshandy field mapping
    fieldnames = [
        "First Name", "Last Name", "Email", "Company",
        "Custom1", "Custom2", "Custom3", "Custom4", "Custom5",
        "Custom6", "Custom7", "Custom8", "Custom9", "Custom10",
    ]

    rows = []
    for lead_id, seq in prospects.items():
        # Split decision_maker_name into first/last
        name = seq.get("to_name", seq.get("company_name", "")).strip()
        parts = name.split()
        first_name = parts[0] if parts else ""
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        row = {
            "First Name": first_name,
            "Last Name": last_name,
            "Email": seq.get("to_email", ""),
            "Company": seq.get("company_name", ""),
            "Custom1": seq.get("industry", ""),          # Industry
            "Custom2": seq.get("area", ""),               # Area
            "Custom3": seq.get("tech_stack", ""),         # Tech stack
            "Custom4": seq.get("personalization_hook", ""),  # Personalization hook
            "Custom5": seq.get("whatsapp_number", ""),    # WhatsApp
            "Custom6": seq.get("hiring_signals", ""),     # Hiring signals
            "Custom7": seq.get("news_signal", ""),        # News signal
            "Custom8": seq.get("lead_score_v2", ""),      # Lead score
            "Custom9": seq.get("sequence_tier", ""),      # Sequence tier
            "Custom10": seq.get("email_source", ""),      # Source
        }
        rows.append(row)

    # Write output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{Fore.GREEN}Exported {len(rows)} prospects to {output_path}{Style.RESET_ALL}")
    print(f"\nSaleshandy field mapping:")
    print(f"  Custom1  → Industry")
    print(f"  Custom2  → Area")
    print(f"  Custom3  → Tech stack")
    print(f"  Custom4  → Personalization hook")
    print(f"  Custom5  → WhatsApp number")
    print(f"  Custom6  → Hiring signals")
    print(f"  Custom7  → News signal")
    print(f"  Custom8  → Lead score (v2)")
    print(f"  Custom9  → Sequence tier")
    print(f"  Custom10 → Email source")


def main():
    parser = argparse.ArgumentParser(description="Export to Saleshandy format")
    parser.add_argument("input", nargs="?", default="leads/sg_sequences_latest.csv")
    parser.add_argument("--output", default=None, help="Output CSV path")
    args = parser.parse_args()

    if args.output:
        output_path = args.output
    else:
        base, _ = os.path.splitext(args.input)
        output_path = f"{base}_saleshandy.csv"

    export_to_saleshandy(args.input, output_path)


if __name__ == "__main__":
    main()
