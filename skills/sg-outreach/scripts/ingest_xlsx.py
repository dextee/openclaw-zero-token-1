#!/usr/bin/env python3
"""XLSX → CSV converter for uploaded lead lists.

Normalizes column names, cleans phone numbers, filters invalid emails,
and reports data-quality issues.

Usage:
    python3 ingest_xlsx.py --input leads.xlsx --output leads.csv
"""

import argparse
import json
import os
import re
import sys


def normalize_phone(val: str) -> str:
    """Collapse to +65xxxxxxxx."""
    if not val:
        return ""
    digits = re.sub(r"\D", "", str(val))
    if digits.startswith("65") and len(digits) >= 9:
        return "+" + digits
    if len(digits) >= 8:
        return "+65" + digits
    return ""


def is_valid_email(email: str) -> bool:
    if not email or str(email).strip().lower() in ("nan", "n/a", "-", "", "nil", "null"):
        return False
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(email).strip()))


def looks_like_personal_name(company: str) -> bool:
    """Heuristic: personal names lack legal suffixes and are short."""
    if not company:
        return False
    lowered = company.lower()
    legal_suffixes = ("pte ltd", " ltd", "llp", "inc", "plc", "gmbh", "s.a.", "corp", "co.")
    has_suffix = any(s in lowered for s in legal_suffixes)
    word_count = len(company.split())
    return not has_suffix and word_count < 3


def ingest_xlsx(input_path: str, output_path: str) -> dict:
    try:
        import openpyxl
    except ImportError:
        print(json.dumps({"error": "openpyxl not installed"}))
        sys.exit(1)

    wb = openpyxl.load_workbook(input_path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    raw_rows = list(ws.iter_rows(values_only=True))

    if not raw_rows:
        return {"rows_total": 0, "rows_kept": 0, "rows_dropped": 0,
                "drop_reasons": {}, "warnings": {}}

    # Detect header row (first row with an email-like string in any cell)
    header_idx = 0
    for i, row in enumerate(raw_rows):
        if any(is_valid_email(str(c)) for c in row if c):
            header_idx = max(0, i - 1)
            break

    headers = [str(h or "").strip().lower() if h else "" for h in raw_rows[header_idx]]
    data_rows = raw_rows[header_idx + 1:]

    # Column name mapping
    col_map = {
        "company_name": ["company name", "company", "organisation", "organization", "firm", "business name"],
        "email": ["email", "e-mail", "email address", "e-mail address", "mail"],
        "phone": ["phone", "mobile", "mobile no", "mobile number", "tel", "contact", "contact number"],
        "decision_maker_name": ["name", "contact name", "decision maker", "dm name", "person name"],
        "industry": ["industry", "sector", "category", "business type"],
        "loan_amount": ["loan amount", "amount", "financing amount", "requested amount"],
        "loan_status": ["loan status", "status", "application status"],
        "source_date": ["date", "submission date", "created date", "date submitted"],
    }

    def map_header(h: str) -> str:
        for canonical, aliases in col_map.items():
            if h in aliases:
                return canonical
        return h

    mapped_headers = [map_header(h) for h in headers]

    # Build output rows
    out_headers = ["company_name", "email", "phone", "decision_maker_name",
                   "industry", "loan_amount", "loan_status", "source_date",
                   "sent_at", "message_id", "delivery_status"]

    kept = []
    drop_reasons = {"invalid_email": 0, "missing_email": 0, "duplicate_email": 0}
    warnings = {"personal_name_as_company": 0, "placeholder_values": 0, "personal_domain": 0}
    seen_emails = set()

    for row in data_rows:
        if not any(row):
            continue
        row_dict = {}
        for idx, val in enumerate(row):
            if idx < len(mapped_headers):
                row_dict[mapped_headers[idx]] = str(val or "").strip()

        email = row_dict.get("email", "").strip().lower()

        # Drop filters
        if not email:
            drop_reasons["missing_email"] += 1
            continue
        if not is_valid_email(email):
            drop_reasons["invalid_email"] += 1
            continue
        if email in seen_emails:
            drop_reasons["duplicate_email"] += 1
            continue
        seen_emails.add(email)

        # Warnings
        company = row_dict.get("company_name", "")
        if looks_like_personal_name(company):
            warnings["personal_name_as_company"] += 1
        if company.lower() in ("nan", "n/a", "-", ""):
            warnings["placeholder_values"] += 1
        domain = email.split("@")[-1]
        if domain in ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com"):
            warnings["personal_domain"] += 1

        # Normalize phone
        phone = normalize_phone(row_dict.get("phone", ""))

        out_row = {
            "company_name": company,
            "email": email,
            "phone": phone,
            "decision_maker_name": row_dict.get("decision_maker_name", ""),
            "industry": row_dict.get("industry", ""),
            "loan_amount": row_dict.get("loan_amount", ""),
            "loan_status": row_dict.get("loan_status", ""),
            "source_date": row_dict.get("source_date", ""),
            "sent_at": "",
            "message_id": "",
            "delivery_status": "",
        }
        kept.append(out_row)

    # Write CSV
    import csv
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=out_headers)
        writer.writeheader()
        writer.writerows(kept)

    return {
        "rows_total": len(data_rows),
        "rows_kept": len(kept),
        "rows_dropped": len(data_rows) - len(kept),
        "drop_reasons": drop_reasons,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(description="Ingest xlsx lead list → normalized CSV")
    parser.add_argument("--input", required=True, help="Path to .xlsx file")
    parser.add_argument("--output", required=True, help="Path to output .csv")
    args = parser.parse_args()

    result = ingest_xlsx(args.input, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
