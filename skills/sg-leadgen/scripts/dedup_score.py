#!/usr/bin/env python3
"""
dedup_score.py — Deduplicate and score Singapore lead lists.

Reads one or more CSV files, deduplicates by company name/phone/domain/UEN,
applies the scoring model, and outputs a scored, classified CSV.

Usage:
    python3 dedup_score.py input.csv [input2.csv ...] [-o output.csv]
    python3 dedup_score.py *.csv -o sg_leads_scored.csv
"""

import sys
import csv
import json
import re
import os
import argparse
from collections import defaultdict
from datetime import datetime

def normalize_phone(phone):
    if not phone:
        return ''
    digits = re.sub(r'[^0-9]', '', str(phone))
    if digits.startswith('65') and len(digits) > 8:
        digits = digits[2:]
    return digits

def normalize_domain(url):
    if not url:
        return ''
    url = str(url).lower().strip()
    url = re.sub(r'^https?://', '', url)
    url = re.sub(r'^www\.', '', url)
    url = re.sub(r'/.*$', '', url)
    return url

def normalize_company(name):
    if not name:
        return ''
    name = str(name).lower().strip()
    name = re.sub(r'[\.,\-\(\)]', '', name)
    name = re.sub(r'\s+', ' ', name)
    name = re.sub(r'\b(pte|ltd|private|limited|corporation|inc|llp|plc)\b', '', name)
    return name.strip()

def fuzzy_match(a, b, threshold=0.90):
    """Simple fuzzy match using character-level similarity."""
    if not a or not b:
        return False
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    # Use ratio of matching characters
    if len(a) == 0 or len(b) == 0:
        return False
    # Simple approach: check if one contains the other or edit distance is small
    if a in b or b in a:
        ratio = min(len(a), len(b)) / max(len(a), len(b))
        return ratio >= threshold
    # Character n-gram overlap
    n = 3
    if len(a) < n or len(b) < n:
        return False
    a_grams = set(a[i:i+n] for i in range(len(a)-n+1))
    b_grams = set(b[i:i+n] for i in range(len(b)-n+1))
    if not a_grams or not b_grams:
        return False
    overlap = len(a_grams & b_grams) / min(len(a_grams), len(b_grams))
    return overlap >= threshold

# ── Scoring models ───────────────────────────────────────────────────────────

def score_lead(lead):
    """Default scoring model. Returns (score, tier)."""
    score = 0

    # Verified email (25)
    email = str(lead.get('email', '') or lead.get('direct_email', '')).strip()
    if email and '@' in email and '.' in email:
        score += 25

    # Verified phone (15)
    phone = str(lead.get('phone', '') or lead.get('direct_phone', '')).strip()
    if phone and len(re.sub(r'[^0-9]', '', phone)) >= 8:
        score += 15

    # ACRA verified active (20)
    status = str(lead.get('registration_status', '') or lead.get('uen_status_desc', '')).lower()
    if status and any(s in status for s in ['active', 'registered', 'live', 'registered - local company']):
        score += 20

    # LinkedIn company page (10)
    linkedin = str(lead.get('linkedin_url', '')).strip()
    if linkedin and 'linkedin.com' in linkedin:
        score += 10

    # Website with contact page (10)
    website = str(lead.get('website', '')).strip()
    if website:
        score += 10

    # Decision maker identified (15)
    dm_name = str(lead.get('decision_maker_name', '')).strip()
    dm_title = str(lead.get('decision_maker_title', '')).strip()
    if dm_name and dm_title:
        score += 15
    elif dm_name or dm_title:
        score += 8

    # Recent activity (5)
    notes = str(lead.get('notes', '')).lower()
    if 'recent' in notes or '2025' in notes or '2026' in notes:
        score += 5

    if score >= 70:
        tier = 'Hot'
    elif score >= 40:
        tier = 'Warm'
    else:
        tier = 'Cold'

    return score, tier


ADVISORY_ICP_INDUSTRIES = {
    "construction", "building", "contractor", "developer", "real estate",
    "property", "manufacturing", "industrial", "logistics", "transport",
    "warehouse", "shipping", "freight", "f&b", "food & beverage",
    "restaurant", "catering", "hospitality", "hotel", "professional services",
    "consulting", "advisory", "accounting", "audit", "legal", "law",
    "engineering", "architect", "design", "interior design",
    "healthcare", "medical", "pharmaceutical", "biotech",
    "technology", "software", "it services", "fintech",
    "retail", "wholesale", "distribution", "trading",
    "education", "training", "tuition",
}

CFINANCE_TITLES = {
    "cfo", "chief financial officer", "finance director", "director of finance",
    "head of finance", "vp finance", "vice president finance",
    "finance manager", "financial controller", "controller",
    "group cfo", "deputy cfo", "assistant cfo",
    "senior finance manager", "finance lead",
}

TRIGGER_EVENTS = {
    "expansion", "expanding", "new project", "new branch", "new office",
    "funding", "raised", "series", "investment", "acquisition", "acquired",
    "merger", "merged", "ipo", "listing", "listed", "growth", "growing",
    "hiring", "recruiting", "new launch", "product launch",
}


def score_lead_mirae(lead):
    """Mirae Advisory scoring model. Returns (score, tier)."""
    score = 0
    signals = []

    # Verified email (15)
    email = str(lead.get('email', '') or lead.get('direct_email', '')).strip()
    if email and '@' in email and '.' in email:
        score += 15
        signals.append("verified_email")

    # Verified phone (10)
    phone = str(lead.get('phone', '') or lead.get('direct_phone', '')).strip()
    if phone and len(re.sub(r'[^0-9]', '', phone)) >= 8:
        score += 10
        signals.append("verified_phone")

    # ACRA active (20)
    status = str(lead.get('registration_status', '') or lead.get('uen_status_desc', '')).lower()
    if status and any(s in status for s in ['active', 'registered', 'live', 'registered - local company']):
        score += 20
        signals.append("acra_active")

    # MAS licensed (15) — only if explicitly yes
    if lead.get('mas_licensed') == 'yes':
        score += 15
        signals.append("mas_licensed")

    # Title match c-finance (25)
    dm_title = str(lead.get('decision_maker_title', '')).lower()
    if any(t in dm_title for t in CFINANCE_TITLES):
        score += 25
        signals.append("title_match_cfinance")

    # Industry advisory ICP (20)
    industries = ' '.join([
        str(lead.get('industry', '')),
        str(lead.get('detected_industry', '')),
        str(lead.get('notes', '')),
    ]).lower()
    if any(icp in industries for icp in ADVISORY_ICP_INDUSTRIES):
        score += 20
        signals.append("industry_advisory_icp")

    # SG signal (10)
    sg = str(lead.get('sg_signals', '')).lower()
    if sg and len(sg) > 3:
        score += 10
        signals.append("sg_signal")

    # Trigger event (30)
    combined = ' '.join([
        str(lead.get('notes', '')),
        str(lead.get('source', '')),
        str(lead.get('_source_file', '')),
    ]).lower()
    if any(trig in combined for trig in TRIGGER_EVENTS):
        score += 30
        signals.append("trigger_event")

    # Recency bonus (5)
    if '2025' in combined or '2026' in combined:
        score += 5
        signals.append("recency_bonus")

    # LinkedIn source (5)
    linkedin = str(lead.get('linkedin_url', '')).strip()
    if linkedin and 'linkedin.com' in linkedin:
        score += 5
        signals.append("linkedin_source")

    # Classification
    if score >= 80:
        tier = 'Hot'
    elif score >= 60:
        tier = 'Warm'
    elif score >= 40:
        tier = 'Cool'
    else:
        tier = 'Cold'

    lead['_mirae_signals'] = ', '.join(signals)
    return score, tier

DIRECTORY_DOMAINS = {
    "yelu.sg", "yellowpages.com.sg", "yellowpages.sg",
    "kompass.com", "dnb.com", "dunn-bradstreet.com",
    "sgdirectory.sg", "businesslist.com.sg", "bizhub.sg",
}


def deduplicate(leads):
    """Deduplicate leads by company name, phone, domain, or UEN."""
    seen_names = {}
    seen_phones = {}
    seen_domains = {}
    seen_uens = {}
    merged = []
    
    for lead in leads:
        name_norm = normalize_company(lead.get('company_name', ''))
        phone_norm = normalize_phone(lead.get('phone', ''))
        domain_norm = normalize_domain(lead.get('website', ''))
        uen_norm = str(lead.get('uen', '')).strip().upper()
        
        # Check for duplicates
        duplicate_idx = None
        
        # UEN match (exact)
        if uen_norm and uen_norm in seen_uens:
            duplicate_idx = seen_uens[uen_norm]
        
        # Phone match (exact)
        if duplicate_idx is None and phone_norm and phone_norm in seen_phones:
            duplicate_idx = seen_phones[phone_norm]
        
        # Domain match (exact) — skip for directory/profile sites
        is_directory_domain = False
        if domain_norm:
            for d in DIRECTORY_DOMAINS:
                if domain_norm == d or domain_norm.endswith('.' + d):
                    is_directory_domain = True
                    break
        if duplicate_idx is None and domain_norm and not is_directory_domain and domain_norm in seen_domains:
            duplicate_idx = seen_domains[domain_norm]
        
        # Name match (fuzzy)
        if duplicate_idx is None and name_norm:
            for seen_name, idx in seen_names.items():
                if fuzzy_match(name_norm, seen_name):
                    duplicate_idx = idx
                    break
        
        if duplicate_idx is not None:
            # Merge: fill in missing fields from new lead
            existing = merged[duplicate_idx]
            for key, val in lead.items():
                if val and not existing.get(key):
                    existing[key] = val
                elif key == 'notes' and val:
                    existing[key] = existing.get(key, '') + '; ' + val
                elif key == 'source' and val and val not in existing.get(key, ''):
                    existing[key] = existing.get(key, '') + ', ' + val
        else:
            # New unique lead
            idx = len(merged)
            merged.append(lead)
            
            if name_norm:
                seen_names[name_norm] = idx
            if phone_norm:
                seen_phones[phone_norm] = idx
            if domain_norm:
                seen_domains[domain_norm] = idx
            if uen_norm:
                seen_uens[uen_norm] = idx
    
    return merged

def main():
    parser = argparse.ArgumentParser(description='Deduplicate and score Singapore lead lists')
    parser.add_argument('inputs', nargs='+', help='Input CSV file(s)')
    parser.add_argument('-o', '--output', default=None, help='Output CSV file')
    parser.add_argument('--min-score', type=int, default=0, help='Minimum score to include')
    parser.add_argument('--tier', choices=['Hot', 'Warm', 'Cold', 'Cool'], default=None,
                       help='Filter by tier')
    parser.add_argument('--mode', choices=['default', 'mirae'], default='default',
                       help='Scoring model: default or mirae (default: default)')
    args = parser.parse_args()
    
    # Read all input CSVs
    all_leads = []
    for filepath in args.inputs:
        if not os.path.exists(filepath):
            print(f"Warning: {filepath} not found, skipping", file=sys.stderr)
            continue
        with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row['_source_file'] = os.path.basename(filepath)
                all_leads.append(row)
    
    print(f"Read {len(all_leads)} total leads from {len(args.inputs)} file(s)")
    
    # Deduplicate
    unique_leads = deduplicate(all_leads)
    print(f"After dedup: {len(unique_leads)} unique leads")
    
    # Score and classify
    scorer = score_lead_mirae if args.mode == 'mirae' else score_lead
    for lead in unique_leads:
        score, tier = scorer(lead)
        lead['lead_score'] = score
        lead['lead_tier'] = tier
    
    # Filter
    if args.min_score > 0:
        unique_leads = [l for l in unique_leads if l['lead_score'] >= args.min_score]
        print(f"After score filter (>={args.min_score}): {len(unique_leads)} leads")
    
    if args.tier:
        unique_leads = [l for l in unique_leads if l['lead_tier'] == args.tier]
        print(f"After tier filter ({args.tier}): {len(unique_leads)} leads")
    
    # Sort by score descending
    unique_leads.sort(key=lambda x: x.get('lead_score', 0), reverse=True)
    
    # Write output
    fieldnames = [
        'company_name', 'phone', 'email', 'website', 'address', 'area',
        'industry', 'industry_confidence', 'detected_industry', 'sg_signals',
        'uen', 'registration_status', 'entity_type_desc', 'uen_status_desc',
        'reg_street_name', 'reg_postal_code', 'mas_licensed',
        'linkedin_url', 'direct_email', 'direct_phone', 'whatsapp',
        'decision_maker_name', 'decision_maker_title',
        'contact_1_name', 'contact_1_title',
        'contact_2_name', 'contact_2_title',
        'contact_3_name', 'contact_3_title',
        'employee_count',
        'rating', 'review_count', 'source', 'lead_score', 'lead_tier',
        '_mirae_signals', 'notes',
        'email_verified', 'email_confidence', 'email_source',
        'email_status_detail', 'mx_provider', 'is_catch_all', '_contacts_found',
    ]
    
    output_path = args.output
    if not output_path:
        date_str = datetime.now().strftime('%Y%m%d')
        output_path = f'sg_leads_scored_{date_str}.csv'
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(unique_leads)
    
    # Summary
    hot = sum(1 for l in unique_leads if l.get('lead_tier') == 'Hot')
    warm = sum(1 for l in unique_leads if l.get('lead_tier') == 'Warm')
    cold = sum(1 for l in unique_leads if l.get('lead_tier') == 'Cold')
    
    cool = sum(1 for l in unique_leads if l.get('lead_tier') == 'Cool')
    print(f"\nOutput: {output_path}")
    print(f"  Hot:  {hot}")
    print(f"  Warm: {warm}")
    print(f"  Cool: {cool}")
    print(f"  Cold: {cold}")

if __name__ == '__main__':
    main()
