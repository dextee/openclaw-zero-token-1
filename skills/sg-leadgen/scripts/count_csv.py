#!/usr/bin/env python3
"""
count_csv.py — Reliable lead file counter.

Prevents the counting bugs that happen when bots use ad-hoc one-liners.
Handles BOM, empty values, "nan" strings, and duplicate detection.

Usage:
  python3 count_csv.py /path/to/leads.csv
  python3 count_csv.py /path/to/leads.csv --dedup-email
"""

import argparse
import csv
import os
import sys
from collections import Counter


def is_valid_email(val: str) -> bool:
    if not val:
        return False
    v = val.strip().lower()
    if v in ("", "nan", "none", "null", "n/a", "-"):
        return False
    if "@" not in v:
        return False
    return True


def is_valid_phone(val: str) -> bool:
    if not val:
        return False
    v = str(val).strip().lower()
    if v in ("", "nan", "none", "null", "n/a", "-"):
        return False
    # Must contain at least 2 digits
    digits = sum(c.isdigit() for c in v)
    return digits >= 2


def count_file(path: str, dedup_email: bool = False):
    if not os.path.exists(path):
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    # Try encodings in order of likelihood
    rows = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                break
        except UnicodeDecodeError:
            continue

    if rows is None:
        print("ERROR: could not decode file", file=sys.stderr)
        sys.exit(1)

    total = len(rows)
    emails = [r.get("email", "").strip() for r in rows]
    phones = [r.get("phone", "").strip() for r in rows]
    companies = [r.get("company_name", "").strip() for r in rows if r.get("company_name", "").strip()]

    valid_emails = [e for e in emails if is_valid_email(e)]
    valid_phones = [p for p in phones if is_valid_phone(p)]
    invalid_emails = total - len(valid_emails)

    unique_emails = len(set(e.lower() for e in valid_emails))
    unique_phones = len(set(p.lower() for p in valid_phones))

    email_counts = Counter(e.lower() for e in valid_emails)
    duplicates = sum(1 for e, c in email_counts.items() if c > 1)
    duplicate_rows = sum(c - 1 for e, c in email_counts.items() if c > 1)

    if dedup_email:
        deduped = unique_emails
    else:
        deduped = None

    # Output format matches normalize_upload.py for consistency
    print(f"FILE: {path}")
    print(f"STATS: total={total} emails={len(valid_emails)} phones={len(valid_phones)} companies={len(companies)} websites=0")
    print(f"VALID: emails={len(valid_emails)} phones={len(valid_phones)} companies={len(companies)}")
    print(f"INVALID: emails={invalid_emails}")
    print(f"UNIQUE: emails={unique_emails} phones={unique_phones}")
    print(f"DUPLICATES: email_duplicates={duplicates} duplicate_rows={duplicate_rows}")
    if deduped is not None:
        print(f"DEDUPED: {deduped} rows after removing duplicate emails")
    print(f"COLUMNS: {', '.join(rows[0].keys()) if rows else 'none'}")


def main():
    parser = argparse.ArgumentParser(description="Reliable CSV lead counter")
    parser.add_argument("input", help="Input CSV file")
    parser.add_argument("--dedup-email", action="store_true", help="Also report count after deduplicating by email")
    args = parser.parse_args()
    count_file(args.input, args.dedup_email)


if __name__ == "__main__":
    main()
