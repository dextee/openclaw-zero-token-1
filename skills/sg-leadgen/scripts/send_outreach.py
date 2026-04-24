#!/usr/bin/env python3
"""
Mirae Advisory — Cold Outreach Sender
Sends templated emails via Google Workspace SMTP Relay (no password needed).
Usage: python3 send_outreach.py --csv leads.csv --template A --from-name "Melvin Teo"
"""

import csv
import smtplib
import socket
import argparse
import time
import random
import os
import json
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Config ────────────────────────────────────────────────────────────────────
SMTP_HOST       = "smtp-relay.gmail.com"
SMTP_PORT       = 587
FROM_EMAIL      = "Admin@miraeadvisory.com"
BOOKING_LINK    = "https://calendar.app.google/Vt8th4ByKcCxD4Fv6"
WEBSITE         = "miraeadvisory.com"
ADDRESS         = "7 Temasek Boulevard, #12-07, Suntec Tower One"
LOG_FILE        = os.path.join(os.path.dirname(__file__), "../../../leads/outreach_log.json")
DELAY_MIN       = 45   # seconds between emails (min)
DELAY_MAX       = 90   # seconds between emails (max)

# ── Templates ─────────────────────────────────────────────────────────────────
def build_email(template, first_name, company_name, from_name, industry=""):
    ctx = {
        "first_name":    first_name or "there",
        "company_name":  company_name or "your company",
        "from_name":     from_name,
        "booking_link":  BOOKING_LINK,
        "website":       WEBSITE,
        "address":       ADDRESS,
        "from_email":    FROM_EMAIL,
        "industry":      industry or "your industry",
    }

    if template == "A":
        subject = f"Quick question about your funding options, {ctx['company_name']}"
        body = f"""Hi {ctx['first_name']},

I noticed {ctx['company_name']} has been growing — congrats on that.

I'm reaching out from Mirae Advisory. We're a boutique SME financing firm founded by ex-bankers (20+ years in business banking at both traditional banks and alternative lenders). We set up specifically because we saw how hard it is for SMEs to navigate funding options without paying for advice that just ends up selling them the wrong product.

We help Singapore SMEs with:
- Unsecured business loans & working capital facilities
- Trade and invoice financing
- Commercial property financing & refinancing

No fluff — we assess your situation, tell you honestly what you qualify for, and connect you with the right lender.

If it makes sense, you can grab a 15-minute slot directly here: {ctx['booking_link']}

Regards,
{ctx['from_name']}
Mirae Advisory
{ctx['address']}"""

    elif template == "B":
        subject = "Commercial property + financing — one call, both covered"
        body = f"""Hi {ctx['first_name']},

Are you looking to buy, rent, or refinance commercial space for {ctx['company_name']}?

Most advisors handle either the property search or the financing — not both. At Mirae Advisory, our team has deep roots in commercial banking and real estate, so we can run both in parallel for you: find the right space and structure the financing at the same time.

We've helped Singapore SMEs avoid the classic mistake of signing a lease or purchase before locking in their facility — which can cost months of delays.

Worth a quick call? Book a time directly here: {ctx['booking_link']}

Best,
{ctx['from_name']}
Mirae Advisory | Suntec Tower One
{ctx['website']}"""

    elif template == "C":
        subject = "SME financing from ex-bankers — 15 mins?"
        body = f"""Hi {ctx['first_name']},

Mirae Advisory here — we are a Singapore-based SME financing firm led by former bankers. We help businesses like {ctx['company_name']} get the right funding without the run-around.

We offer:
- Working Capital Loan
- Trade Lines
- Invoice Factoring
- Revenue Based Financing
- Property Backed Loan
- Personal Loan

Quick question: is {ctx['company_name']} looking to expand or optimize your funding setup in the next 6 months?

If yes, grab a 15-min slot here and we'll walk you through what you'd likely qualify for — no obligation: {ctx['booking_link']}

{ctx['from_name']} | Mirae Advisory | {ctx['website']}"""

    else:
        raise ValueError(f"Unknown template: {template}. Use A, B, or C.")

    return subject, body


# ── SMTP (force IPv4) ─────────────────────────────────────────────────────────
def force_ipv4():
    orig = socket.getaddrinfo
    def ipv4_only(host, port, family=0, *args, **kwargs):
        return orig(host, port, socket.AF_INET, *args, **kwargs)
    socket.getaddrinfo = ipv4_only

def send_email(to_email, subject, body, from_name):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{from_name} <{FROM_EMAIL}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        server.ehlo("miraeadvisory.com")
        server.starttls()
        server.ehlo("miraeadvisory.com")
        server.sendmail(FROM_EMAIL, [to_email], msg.as_string())


# ── Logging ───────────────────────────────────────────────────────────────────
def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            return json.load(f)
    return {}

def save_log(log):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)

def already_sent(log, email):
    return email.lower() in {k.lower() for k in log}


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Mirae Advisory outreach sender")
    parser.add_argument("--csv",       required=True, help="Path to leads CSV file")
    parser.add_argument("--template",  default="auto", help="Template A, B, C, or 'auto' (score-based)")
    parser.add_argument("--from-name", default="Melvin Teo", help="Sender name")
    parser.add_argument("--dry-run",   action="store_true", help="Preview without sending")
    parser.add_argument("--limit",     type=int, default=0, help="Max emails to send (0 = all)")
    args = parser.parse_args()

    force_ipv4()
    log  = load_log()
    sent = 0
    skip = 0

    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        leads  = list(reader)

    print(f"\nLoaded {len(leads)} leads from {args.csv}")
    print(f"Already sent: {len(log)} | Dry run: {args.dry_run}\n")

    for lead in leads:
        if args.limit and sent >= args.limit:
            break

        email   = (lead.get("email") or "").strip()
        company = (lead.get("company_name") or lead.get("company") or "").strip()
        name    = (lead.get("decision_maker_name") or lead.get("contact_name") or "").strip()
        score   = int(lead.get("lead_score") or 0)
        industry= (lead.get("industry") or "").strip()

        first_name = name.split()[0] if name else ""

        if not email:
            print(f"  SKIP (no email): {company}")
            skip += 1
            continue

        if already_sent(log, email):
            print(f"  SKIP (already sent): {email}")
            skip += 1
            continue

        # Auto template selection based on lead score
        template = args.template
        if template == "auto":
            template = "A" if score >= 70 else "C"

        subject, body = build_email(template, first_name, company, args.from_name, industry)

        print(f"  {'[DRY RUN] ' if args.dry_run else ''}Sending Template {template} → {email} ({company}, score={score})")
        print(f"    Subject: {subject}")

        if not args.dry_run:
            try:
                send_email(email, subject, body, args.from_name)
                log[email.lower()] = {
                    "company":   company,
                    "template":  template,
                    "sent_at":   datetime.now().isoformat(),
                    "from_name": args.from_name,
                }
                save_log(log)
                sent += 1
                print(f"    ✓ Sent")
                delay = random.randint(DELAY_MIN, DELAY_MAX)
                print(f"    Waiting {delay}s before next send...")
                time.sleep(delay)
            except Exception as e:
                print(f"    ✗ FAILED: {e}")
        else:
            sent += 1

    print(f"\nDone. Sent: {sent} | Skipped: {skip} | Log: {LOG_FILE}")


if __name__ == "__main__":
    main()
