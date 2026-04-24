"""
normalize_upload.py — Normalize a user-uploaded CSV or email list into the
standard OpenClaw leads schema and save to /root/.openclaw/workspace/leads/.

Handles:
  - Plain email lists (no header, one email per line)
  - CSVs with non-standard column names
  - UTF-8, UTF-8-BOM, UTF-16, Latin-1 encoding
  - Semicolon / tab / comma delimiters

Usage:
  python3 normalize_upload.py /tmp/upload_raw.csv
  python3 normalize_upload.py /tmp/upload_raw.csv --output /root/.openclaw/workspace/leads/sg_leads_mylist_21042026.csv
"""

import argparse
import csv
import io
import os
import re
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# Column name normalisers
# ---------------------------------------------------------------------------
COLUMN_MAP = {
    # company
    "company": "company_name",
    "company name": "company_name",
    "company_name": "company_name",
    "organisation": "company_name",
    "organization": "company_name",
    "org": "company_name",
    "firm": "company_name",
    "business": "company_name",
    "business name": "company_name",
    "name": "company_name",        # only if no separate dm name column
    # email
    "email": "email",
    "email address": "email",
    "e-mail": "email",
    "e-mail address": "email",
    "mail": "email",
    # phone
    "phone": "phone",
    "phone number": "phone",
    "tel": "phone",
    "telephone": "phone",
    "mobile": "phone",
    "contact number": "phone",
    "hp": "phone",
    # website
    "website": "website",
    "url": "website",
    "web": "website",
    "homepage": "website",
    "domain": "website",
    "site": "website",
    # address
    "address": "address",
    "location": "address",
    # decision maker
    "contact": "decision_maker_name",
    "contact name": "decision_maker_name",
    "decision maker": "decision_maker_name",
    "decision_maker_name": "decision_maker_name",
    "dm": "decision_maker_name",
    "person": "decision_maker_name",
    "full name": "decision_maker_name",
    # title
    "title": "decision_maker_title",
    "job title": "decision_maker_title",
    "role": "decision_maker_title",
    "position": "decision_maker_title",
    "designation": "decision_maker_title",
    "decision_maker_title": "decision_maker_title",
    # industry
    "industry": "industry",
    "sector": "industry",
    "category": "industry",
    # notes
    "notes": "notes",
    "note": "notes",
    "remarks": "notes",
    "comment": "notes",
}

# Standard output columns in preferred order
STANDARD_COLUMNS = [
    "company_name", "phone", "email", "website", "address", "area",
    "industry", "uen", "registration_status", "linkedin_url",
    "decision_maker_name", "decision_maker_title",
    "employee_count", "rating", "review_count",
    "source", "lead_score", "lead_tier", "notes",
]

EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


def detect_encoding(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read(4)
    if raw[:3] == b'\xef\xbb\xbf':
        return "utf-8-sig"
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return "utf-16"
    try:
        open(path, encoding="utf-8").read(1024)
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def detect_delimiter(sample: str) -> str:
    for delim in (",", ";", "\t", "|"):
        if sample.count(delim) >= 1:
            return delim
    return ","


def is_plain_email_list(lines: list[str]) -> bool:
    """True if >80% of non-empty lines look like email addresses."""
    non_empty = [l.strip() for l in lines if l.strip()]
    if not non_empty:
        return False
    email_count = sum(1 for l in non_empty if EMAIL_RE.match(l))
    return email_count / len(non_empty) >= 0.8


def domain_to_company(email: str) -> str:
    """Guess company name from email domain: contact@acme.com.sg → Acme"""
    domain = email.split("@")[-1].lower()
    # strip common TLDs
    domain = re.sub(r'\.(com\.sg|sg|com|net|org|io|co)$', '', domain)
    return domain.replace("-", " ").replace(".", " ").title()


def normalize_col(raw: str) -> str:
    key = raw.strip().lower()
    return COLUMN_MAP.get(key, raw.strip())


def load_csv(path: str) -> tuple[list[str], list[dict]]:
    enc = detect_encoding(path)
    with open(path, encoding=enc, errors="replace") as f:
        sample = f.read(2048)
        f.seek(0)
        lines = f.readlines()

    if is_plain_email_list(lines):
        # plain email list — synthesize company_name from domain
        rows = []
        for line in lines:
            email = line.strip()
            if EMAIL_RE.match(email):
                rows.append({"email": email, "company_name": domain_to_company(email)})
        return ["email", "company_name"], rows

    delim = detect_delimiter(sample)
    enc2 = detect_encoding(path)
    with open(path, encoding=enc2, newline="", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=delim)
        raw_cols = reader.fieldnames or []
        rows = list(reader)

    return raw_cols, rows


def remap_columns(raw_cols: list[str], rows: list[dict]) -> list[dict]:
    # Build column name mapping (raw → normalised)
    # Special case: if CSV has a "name" column AND a DM-name-like column, prefer DM for "name"
    has_company = any(normalize_col(c) == "company_name" and c.lower() not in ("name",) for c in raw_cols)
    remapped = []
    for row in rows:
        new_row: dict = {}
        for raw_col, val in row.items():
            norm = normalize_col(raw_col)
            # "name" → company_name only if no explicit company column
            if raw_col.strip().lower() == "name" and has_company:
                norm = "decision_maker_name"
            if norm in new_row:
                # avoid overwriting already-mapped columns — keep first occurrence
                continue
            new_row[norm] = (val or "").strip()
        remapped.append(new_row)
    return remapped


def fill_standard_columns(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        full = {col: "" for col in STANDARD_COLUMNS}
        # preserve any extra cols not in our schema
        for k, v in row.items():
            full[k] = v
        out.append(full)
    return out


def derive_lead_tier(row: dict) -> str:
    if row.get("lead_tier"):
        return row["lead_tier"]
    has_email = bool(row.get("email", "").strip())
    has_phone = bool(row.get("phone", "").strip())
    has_website = bool(row.get("website", "").strip())
    if has_email and has_website:
        return "Hot"
    if has_email or (has_phone and has_website):
        return "Warm"
    return "Cold"


def derive_lead_score(row: dict) -> str:
    if row.get("lead_score"):
        return row["lead_score"]
    tier = derive_lead_tier(row)
    return {"Hot": "80", "Warm": "50", "Cold": "20"}.get(tier, "20")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input CSV or email list")
    parser.add_argument("--output", help="Output path (default: auto-generated in leads dir)")
    parser.add_argument("--source", default="upload", help="Source label (default: upload)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    raw_cols, rows = load_csv(args.input)
    if not rows:
        print("ERROR: no rows found in input file", file=sys.stderr)
        sys.exit(1)

    rows = remap_columns(raw_cols, rows)
    rows = fill_standard_columns(rows)

    for row in rows:
        if not row.get("source"):
            row["source"] = args.source
        if not row.get("lead_tier"):
            row["lead_tier"] = derive_lead_tier(row)
        if not row.get("lead_score"):
            row["lead_score"] = derive_lead_score(row)

    # Build output path
    if args.output:
        out_path = args.output
    else:
        leads_dir = "/root/.openclaw/workspace/leads"
        os.makedirs(leads_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(args.input))[0]
        safe = re.sub(r'[^a-z0-9_]', '_', base.lower()).strip("_")
        date_tag = datetime.now().strftime("%d%m%Y")
        out_path = os.path.join(leads_dir, f"sg_leads_{safe}_{date_tag}.csv")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # Merge STANDARD_COLUMNS with any extra cols from input
    all_cols = list(STANDARD_COLUMNS)
    for row in rows:
        for k in row:
            if k not in all_cols:
                all_cols.append(k)

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    total = len(rows)
    with_email = sum(1 for r in rows if r.get("email", "").strip())
    with_phone = sum(1 for r in rows if r.get("phone", "").strip())
    with_website = sum(1 for r in rows if r.get("website", "").strip())
    hot = sum(1 for r in rows if r.get("lead_tier") == "Hot")
    warm = sum(1 for r in rows if r.get("lead_tier") == "Warm")
    cold = sum(1 for r in rows if r.get("lead_tier") == "Cold")
    columns_detected = [c for c in STANDARD_COLUMNS if any(r.get(c, "").strip() for r in rows)]

    print(f"SAVED: {out_path}")
    print(f"STATS: total={total} emails={with_email} phones={with_phone} websites={with_website} hot={hot} warm={warm} cold={cold}")
    print(f"COLUMNS: {', '.join(columns_detected)}")


if __name__ == "__main__":
    main()
