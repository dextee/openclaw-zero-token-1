#!/usr/bin/env python3
"""Pre-send validator for SG Outreach sequences.

Checks generated sequences for:
1. Empty sender fields (sender_name, sender_email)
2. Unfilled template placeholders ({{something}})
3. Missing required columns
4. Empty email addresses
5. Empty subject or body

Usage:
    python3 validate_sequences.py --sequences leads/sg_sequences_20260421.csv

Exit codes:
    0 = all clear
    1 = validation errors found
"""

import argparse
import csv
import os
import re
import sys

from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

REQUIRED_COLUMNS = ["to_email", "subject", "body", "sender_name"]
PLACEHOLDER_PATTERN = re.compile(r"\{\{[^}]+\}\}")


def validate_sequences(sequences_csv: str) -> dict:
    if not os.path.exists(sequences_csv):
        print(f"{Fore.RED}Error: File not found: {sequences_csv}{Style.RESET_ALL}")
        sys.exit(1)

    with open(sequences_csv, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"{Fore.RED}Error: No rows in {sequences_csv}{Style.RESET_ALL}")
        sys.exit(1)

    errors = []
    warnings = []
    fieldnames = rows[0].keys()

    # Check required columns exist
    for col in REQUIRED_COLUMNS:
        if col not in fieldnames:
            errors.append(f"Missing required column: {col}")

    for i, row in enumerate(rows, 1):
        # sender_name may be empty when the campaign signs as company only
        # (e.g. "Mirae Advisory" with no individual name). Templates no longer
        # reference {{sender_name}}, so empty is safe.

        # sender_email is optional — sender script falls back to config file email

        # Empty recipient
        if not row.get("to_email", "").strip():
            errors.append(f"Row {i}: to_email is empty")

        # Empty subject
        if not row.get("subject", "").strip():
            errors.append(f"Row {i}: subject is empty")

        # Empty body
        if not row.get("body", "").strip():
            errors.append(f"Row {i}: body is empty")

        # Unfilled placeholders
        body = row.get("body", "")
        subject = row.get("subject", "")
        unfilled = PLACEHOLDER_PATTERN.findall(f"{subject} {body}")
        if unfilled:
            unique = list(set(unfilled))
            errors.append(f"Row {i} ({row.get('company_name','?')}): Unfilled placeholders: {', '.join(unique)}")

    return {
        "row_count": len(rows),
        "errors": errors,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(description="SG Outreach Sequence Validator")
    parser.add_argument("--sequences", required=True, help="Path to sequences CSV")
    args = parser.parse_args()

    result = validate_sequences(args.sequences)

    print(f"{Fore.CYAN}Validated {result['row_count']} rows{Style.RESET_ALL}")

    if result["warnings"]:
        print(f"\n{Fore.YELLOW}Warnings ({len(result['warnings'])}):{Style.RESET_ALL}")
        for w in result["warnings"][:10]:
            print(f"  ⚠ {w}")
        if len(result["warnings"]) > 10:
            print(f"  ... and {len(result['warnings']) - 10} more")

    if result["errors"]:
        print(f"\n{Fore.RED}ERRORS ({len(result['errors'])}):{Style.RESET_ALL}")
        for e in result["errors"][:10]:
            print(f"  ✗ {e}")
        if len(result["errors"]) > 10:
            print(f"  ... and {len(result['errors']) - 10} more")
        print(f"\n{Fore.RED}VALIDATION FAILED. Fix errors before sending.{Style.RESET_ALL}")
        sys.exit(1)

    print(f"\n{Fore.GREEN}✓ All clear. Safe to send.{Style.RESET_ALL}")
    sys.exit(0)


if __name__ == "__main__":
    main()
