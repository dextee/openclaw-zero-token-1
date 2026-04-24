#!/usr/bin/env python3
"""SG Outreach — Personalized Email Sequence Generator.

Reads enriched lead list and generates multi-email sequences with
personalized copy. Outputs CSV ready for Gmail sending or Saleshandy import.

Usage:
    python3 generate_sequences.py leads/sg_leads_enriched.csv \\
        --sender-name "John Doe" --sender-title "Founder" --sender-company "MyCo"
"""

import argparse
import csv
import hashlib
import os
import re
import sys
import urllib.parse
from datetime import datetime

from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

# Add parent dir to path for template import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "references"))
from sequence_templates import TIERS, VARIANTS, SPAM_WORDS

# Import global outreach history
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import outreach_history as oh


def _get_config_email() -> str:
    """Read sender email from Workspace SMTP config if available."""
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(skill_dir, ".workspace_smtp_config.json")
    if os.path.exists(config_path):
        import json
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("email", "").strip()
    return ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def fill_template(template: str, row: dict, sender: dict, extra_defaults: dict = None) -> str:
    """Replace {{tokens}} with actual values. Unfilled tokens become empty."""
    dm_name = row.get("decision_maker_name", "").strip()
    first_name = dm_name.split()[0] if dm_name else "there"
    defaults = {
        "first_name": first_name,
        "decision_maker_name": dm_name or row.get("company_name", "your team"),
        "company_name": row.get("company_name", ""),
        "industry": row.get("industry", ""),
        "area": row.get("area", "Singapore"),
        "personalization_hook": row.get("personalization_hook", ""),
        "tech_stack_item": row.get("tech_stack", "").split(",")[0].strip() if row.get("tech_stack") else "modern tools",
        "hiring_signal": row.get("hiring_signals", "").split(",")[0].strip() if row.get("hiring_signals") else "new team members",
        "tender_value": row.get("tender_value", "recent"),
        "sender_name": sender.get("sender_name", ""),
        "sender_title": sender.get("sender_title", ""),
        "sender_company": sender.get("sender_company", ""),
    }
    if extra_defaults:
        defaults.update(extra_defaults)
    result = template
    for token, value in defaults.items():
        result = result.replace("{{" + token + "}}", str(value))
    # Strip any remaining unfilled tokens
    result = re.sub(r"\{\{[^}]+\}\}", "", result)
    return result


def select_variant(row: dict) -> str:
    """Choose template variant based on available data."""
    # Explicit variant override takes highest priority
    explicit = row.get("variant", "").strip().lower()
    if explicit and explicit in VARIANTS:
        return explicit
    # Default to financing variant for all leads (client requirement)
    return "financing_variant"


def check_spam_words(text: str) -> list:
    """Check text for spam trigger words. Returns list of found words."""
    text_lower = text.lower()
    found = []
    for word in SPAM_WORDS:
        if word in text_lower:
            found.append(word)
    return found


def determine_tier(row: dict, force_tier: str = None) -> str:
    """Determine sequence tier from score or explicit field."""
    if force_tier and force_tier.upper() in ("A", "B", "C"):
        return force_tier.upper()

    tier_field = row.get("email_sequence_tier", "").strip().upper()
    if tier_field in ("A", "B", "C"):
        return tier_field

    try:
        score = int(row.get("lead_score_v2", row.get("lead_score", 0)))
    except (ValueError, TypeError):
        score = 0

    if score >= 80:
        return "A"
    elif score >= 45:
        return "B"
    else:
        return "C"


def generate_lead_id(row: dict) -> str:
    """Generate unique lead ID from company name + domain."""
    name = row.get("company_name", "")
    domain = row.get("website", "").split("/")[-1] if row.get("website") else ""
    raw = f"{name}|{domain}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def generate_sequence(row: dict, sender: dict, tier: str) -> list:
    """Generate full email sequence for one lead."""
    tier_config = TIERS[tier]
    variant_key = select_variant(row)
    variant_config = VARIANTS.get(variant_key, VARIANTS["financing_variant"])

    emails = []
    for i, email_config in enumerate(tier_config["emails"]):
        email_num = email_config["email_number"]

        # Financing variant provides bodies for ALL emails in the sequence.
        # Email 1 = main body, Email 2 = followup, Email 3+ = breakup.
        if email_num == 1:
            subjects = variant_config["subjects"]
            body_template = variant_config["body"]
        elif email_num == 2 and variant_config.get("followup_body"):
            subjects = variant_config.get("followup_subjects", email_config["subjects"])
            body_template = variant_config["followup_body"]
        elif email_num >= 3 and variant_config.get("breakup_body"):
            subjects = variant_config.get("breakup_subjects", email_config["subjects"])
            body_template = variant_config["breakup_body"]
        else:
            subjects = email_config["subjects"]
            body_template = email_config["body"]

        # Build unsubscribe URL (mailto for v1 — no web endpoint required)
        to_email = ""
        for col in ("email", "Email", "EMAIL"):
            val = row.get(col, "").strip()
            if val:
                to_email = val
                break
        unsub_url = ""
        if to_email:
            unsub_url = f"mailto:unsubscribe@miraeadvisory.com?subject=Unsubscribe%20{urllib.parse.quote(to_email)}"
        extra_defaults = {"unsubscribe_url": unsub_url}

        # Rotate subjects deterministically so each lead gets a different subject
        # Uses lead_id hash for even distribution and reproducibility
        subject_index = int(generate_lead_id(row), 16) % len(subjects)
        subject = fill_template(subjects[subject_index], row, sender, extra_defaults)
        body = fill_template(body_template, row, sender, extra_defaults)

        # Strip any HTML that might have slipped in
        body = re.sub(r'<[^>]+>', '', body)

        # Spam check
        spam_found = check_spam_words(subject) + check_spam_words(body)

        to_name = row.get("decision_maker_name", row.get("company_name", "")).strip()

        # Track which subject variant was used (for A/B testing)
        subject_variant = ""
        if email_num == 1 and len(subjects) > 1:
            subject_variant = f"subj_{subject_index + 1}_of_{len(subjects)}"

        emails.append({
            "lead_id": generate_lead_id(row),
            "company_name": row.get("company_name", ""),
            "to_email": to_email,
            "to_name": to_name,
            "subject": subject,
            "body": body,
            "send_delay_days": email_config["send_delay_days"],
            "email_number": email_num,
            "sequence_tier": tier,
            "template_variant": variant_key,
            "subject_variant": subject_variant,
            "outreach_channel": row.get("outreach_channel", "email"),
            "whatsapp_number": row.get("whatsapp_number", ""),
            "sender_name": sender.get("sender_name", ""),
            "sender_email": sender.get("sender_email", ""),
            "status": "pending",
            "sent_at": "",
            "message_id": "",
            "parent_message_id": "",
            "opened": "",
            "replied": "",
            "spam_warnings": ",".join(spam_found) if spam_found else "",
        })

    return emails


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SG Outreach Sequence Generator")
    parser.add_argument("input", nargs="?", default="leads/sg_leads_enriched.csv")
    parser.add_argument("--output", default=None, help="Output sequences CSV path")
    parser.add_argument("--sender-name", default="", help="Your name (MANDATORY — bot must ask user if empty)")
    parser.add_argument("--sender-title", default="Business Development", help="Your title")
    parser.add_argument("--sender-company", default="Mirae Advisory", help="Your company name")
    parser.add_argument("--sender-email", default="", help="Your sending email address (optional — sender script falls back to config)")
    parser.add_argument("--tier", default="all", choices=["A", "B", "C", "all"],
                        help="Sequence tier to generate (default: all)")
    parser.add_argument("--min-score", type=int, default=20,
                        help="Minimum lead_score_v2 to include (default: 20)")
    parser.add_argument("--channel", default="email", choices=["email", "whatsapp", "all"],
                        help="Outreach channel (default: email)")
    parser.add_argument("--skip-history-check", action="store_true",
                        help="Skip global history deduplication check (not recommended)")
    parser.add_argument("--campaign-name", default="",
                        help="Campaign name for history tracking")
    parser.add_argument("--single", action="store_true",
                        help="Generate only email #1 (one-off send, no follow-ups)")
    args = parser.parse_args()

    input_path = args.input
    if not os.path.exists(input_path):
        print(f"{Fore.RED}Error: Input file not found: {input_path}{Style.RESET_ALL}")
        sys.exit(1)

    sender_email = args.sender_email.strip() or _get_config_email()
    sender = {
        "sender_name": args.sender_name.strip(),
        "sender_title": args.sender_title.strip(),
        "sender_company": args.sender_company.strip(),
        "sender_email": sender_email,
    }

    # ── Sender validation ───────────────────────────────────────────────────
    if not sender["sender_name"]:
        print(f"{Fore.RED}ERROR: --sender-name is required.{Style.RESET_ALL}")
        print(f"{Fore.RED}The bot MUST ask the user: 'What sender name should I use?' before generating sequences.{Style.RESET_ALL}")
        sys.exit(1)

    # Read enriched CSV
    with open(input_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Filter by min score
    rows = [r for r in rows if int(r.get("lead_score_v2", r.get("lead_score", 0))) >= args.min_score]

    # Filter by valid email
    rows = [r for r in rows if any(r.get(col, "").strip() for col in ("email", "Email", "EMAIL"))]

    # ── Global history deduplication check ───────────────────────────────────
    campaign_name = args.campaign_name or os.path.basename(args.output or "")
    skipped = []
    suppressed = []
    if not args.skip_history_check:
        filtered_rows = []
        for r in rows:
            email = ""
            for col in ("email", "Email", "EMAIL"):
                val = r.get(col, "").strip()
                if val:
                    email = val
                    break
            is_supp, supp_reason = oh.is_suppressed(email)
            if is_supp:
                suppressed.append((email, r.get("company_name", ""), supp_reason))
                continue
            was_sent, sent_reason = oh.was_already_sent(email, campaign_name)
            if was_sent:
                skipped.append((email, r.get("company_name", ""), sent_reason))
                continue
            filtered_rows.append(r)
        rows = filtered_rows

    print(f"{Fore.CYAN}Loaded {len(rows)} eligible leads from {input_path}{Style.RESET_ALL}")
    print(f"Sender: '{sender['sender_name']}' / '{sender['sender_title']}' / '{sender['sender_company']}' / '{sender['sender_email']}'")
    print(f"Tier filter: {args.tier} | Min score: {args.min_score} | Channel: {args.channel}")
    if skipped:
        print(f"{Fore.YELLOW}⚠️  Skipped {len(skipped)} already-contacted leads (see history){Style.RESET_ALL}")
    if suppressed:
        print(f"{Fore.RED}🚫 Suppressed {len(suppressed)} opted-out/bounced leads{Style.RESET_ALL}")
    print()

    # Generate sequences
    all_sequences = []
    tier_counts = {"A": 0, "B": 0, "C": 0}
    tier_emails = {"A": 0, "B": 0, "C": 0}
    whatsapp_count = 0

    for row in rows:
        tier = determine_tier(row, args.tier if args.tier != "all" else None)
        if args.tier != "all" and tier != args.tier:
            continue

        sequence = generate_sequence(row, sender, tier)
        if args.single:
            sequence = [s for s in sequence if int(s.get("email_number", 1)) == 1]
            # Force send_delay_days to 0 for immediate send
            for s in sequence:
                s["send_delay_days"] = 0
        all_sequences.extend(sequence)
        tier_counts[tier] += 1
        tier_emails[tier] += len(sequence)
        if row.get("whatsapp_number", "").strip():
            whatsapp_count += 1

        # Record pending entries in global history
        email = ""
        for col in ("email", "Email", "EMAIL"):
            val = row.get(col, "").strip()
            if val:
                email = val
                break
        if email:
            oh.record_contact(
                email=email,
                company_name=row.get("company_name", ""),
                campaign=campaign_name,
                status="pending",
            )

    if not all_sequences:
        print(f"{Fore.YELLOW}No sequences generated. Check min-score and tier filters.{Style.RESET_ALL}")
        sys.exit(0)

    # Write output
    if args.output:
        output_path = args.output
    else:
        date_str = datetime.now().strftime("%Y%m%d")
        output_path = f"leads/sg_sequences_{date_str}.csv"

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    fieldnames = list(all_sequences[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_sequences)

    total_emails = len(all_sequences)
    est_days = max(
        tier_counts["A"] * 6 if tier_counts["A"] else 0,
        tier_counts["B"] * 20 if tier_counts["B"] else 0,
        tier_counts["C"] * 35 if tier_counts["C"] else 0,
    )

    print(f"{Fore.GREEN}✉️  Tier A sequences: {tier_counts['A']} ({tier_emails['A']} emails total){Style.RESET_ALL}")
    print(f"{Fore.BLUE}✉️  Tier B sequences: {tier_counts['B']} ({tier_emails['B']} emails total){Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}✉️  Tier C sequences: {tier_counts['C']} ({tier_emails['C']} emails total){Style.RESET_ALL}")
    print(f"{Fore.YELLOW}📱 WhatsApp touchpoints: {whatsapp_count}{Style.RESET_ALL}")
    print(f"Total emails generated: {total_emails}")
    print(f"Estimated send duration: {est_days} days")
    print(f"\n{Fore.CYAN}Sequences written to: {output_path}{Style.RESET_ALL}")

    if skipped:
        print(f"\n{Fore.YELLOW}⚠️  Already contacted (skipped):{Style.RESET_ALL}")
        for email, company, reason in skipped[:10]:
            print(f"  - {company} <{email}>: {reason}")
        if len(skipped) > 10:
            print(f"  ... and {len(skipped) - 10} more")

    if suppressed:
        print(f"\n{Fore.RED}🚫 Suppressed (opted-out / bounced):{Style.RESET_ALL}")
        for email, company, reason in suppressed[:10]:
            print(f"  - {company} <{email}>: {reason}")
        if len(suppressed) > 10:
            print(f"  ... and {len(suppressed) - 10} more")


if __name__ == "__main__":
    main()
