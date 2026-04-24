#!/usr/bin/env python3
"""
extract_leads.py — Browser extraction helper for sg-leadgen skill.
Extracts lead data from a page via CDP proxy and outputs JSON.

Usage:
    python3 extract_leads.py <proxy_url> <extraction_type> [options]

Examples:
    python3 extract_leads.py http://localhost:3456 yellowpages
    python3 extract_leads.py http://localhost:3456 googlemaps
    python3 extract_leads.py http://localhost:3456 yelu
    python3 extract_leads.py http://localhost:3456 acra --query "Acme Pte Ltd"
"""

import sys
import json
import urllib.request
import urllib.parse
import time
import re

PROXY_URL = "http://localhost:3456"

def navigate(url):
    """Navigate browser to URL."""
    encoded = urllib.parse.quote(url, safe=':/?&=')
    resp = urllib.request.urlopen(f"{PROXY_URL}/navigate?url={encoded}")
    time.sleep(2)  # Wait for page load
    return json.loads(resp.read())

def eval_js(script):
    """Execute JavaScript and return result."""
    req = urllib.request.Request(
        f"{PROXY_URL}/eval",
        data=script.encode('utf-8'),
        headers={'Content-Type': 'text/plain'},
        method='POST'
    )
    resp = urllib.request.urlopen(req)
    raw = resp.read().decode('utf-8')
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw

def extract_yellowpages():
    """Extract leads from Yellow Pages SG search results."""
    js = """
    JSON.stringify([...document.querySelectorAll('.listing-item, .search-result, .media-box')].map(el => ({
        name: (el.querySelector('.business-name, h3, .company-name, a.media-box__title') || {}).textContent || '',
        phone: (el.querySelector('.phone, [itemprop="telephone"], .contact-phone') || {}).textContent || '',
        address: (el.querySelector('.address, [itemprop="address"], .contact-address') || {}).textContent || '',
        website: (el.querySelector('.website a, .website-link, a[href*="http"]') || {}).href || '',
        category: (el.querySelector('.category-tag, .business-type') || {}).textContent || '',
        email: (el.querySelector('.email, [itemprop="email"]') || {}).textContent || ''
    })).filter(x => x.name && x.name.trim())
    """
    return eval_js(js)

def extract_googlemaps():
    """Extract leads from Google Maps search results."""
    js = """
    JSON.stringify([...document.querySelectorAll('[role="feed"] [jsaction], [role="article"], .Nv2PK')].map(el => ({
        name: (el.querySelector('.hfpxzc, .a4gq8e-aVT7Ab, .qBF1Pd') || {}).textContent || '',
        rating: (el.querySelector('.MW4etd, .CEj1yb') || {}).textContent || '',
        reviews: (el.querySelector('.UY7F9, .BaRft') || {}).textContent || '',
        address: (el.querySelector('.W4Efsd, .UjYfZ') || {}).textContent || '',
        phone: (el.querySelector('[data-item-id="phone"]') || {}).textContent || '',
        website: (el.querySelector('[data-item-id="authority"]') || {}).href || '',
        category: (el.querySelector('.DkEaL, .PPBpm') || {}).textContent || '',
        hours: (el.querySelector('[data-item-id="hours"]') || {}).textContent || ''
    })).filter(x => x.name && x.name.trim())
    """
    return eval_js(js)

def extract_yelu():
    """Extract leads from Yelu.sg search results."""
    js = """
    JSON.stringify([...document.querySelectorAll('.listing, .business-card, .result-item')].map(el => ({
        name: (el.querySelector('.business-name, h2, h3, .name') || {}).textContent || '',
        rating: (el.querySelector('.rating, .stars, .score') || {}).textContent || '',
        reviews: (el.querySelector('.review-count, .reviews') || {}).textContent || '',
        address: (el.querySelector('.address, .location') || {}).textContent || '',
        phone: (el.querySelector('.phone, .telephone') || {}).textContent || '',
        website: (el.querySelector('.website a, .website-link') || {}).href || '',
        category: (el.querySelector('.category, .industry') || {}).textContent || '',
        email: (el.querySelector('.email') || {}).textContent || ''
    })).filter(x => x.name && x.name.trim())
    """
    return eval_js(js)

def extract_acra():
    """Extract company info from ACRA BizFile search results."""
    js = """
    JSON.stringify([...document.querySelectorAll('tr, .result-item, .entity-row')].map(el => ({
        company_name: (el.querySelector('.entity-name, .company-name, td:first-child') || {}).textContent || '',
        uen: (el.querySelector('.uen, td:nth-child(2)') || {}).textContent || '',
        status: (el.querySelector('.status, td:nth-child(3)') || {}).textContent || '',
        type: (el.querySelector('.entity-type, td:nth-child(4)') || {}).textContent || ''
    })).filter(x => x.company_name && x.company_name.trim())
    """
    return eval_js(js)

def extract_generic(css_selector, field_mapping):
    """Generic extraction using custom CSS selectors and field mapping.
    
    css_selector: CSS selector for each result row
    field_mapping: dict of {field_name: css_selector_for_field}
    """
    fields = []
    for fname, sel in field_mapping.items():
        fields.append(f"{fname}: (el.querySelector('{sel}') || {{}}).textContent || ''")
    
    js = f"""
    JSON.stringify([...document.querySelectorAll('{css_selector}')].map(el => ({{
        {', '.join(fields)}
    }})).filter(x => Object.values(x).some(v => v.trim())))
    """
    return eval_js(js)

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    global PROXY_URL
    PROXY_URL = sys.argv[1]
    extraction_type = sys.argv[2].lower()
    
    extractors = {
        'yellowpages': extract_yellowpages,
        'yellowpages.com.sg': extract_yellowpages,
        'googlemaps': extract_googlemaps,
        'google_maps': extract_googlemaps,
        'google-maps': extract_googlemaps,
        'yelu': extract_yelu,
        'yelu.sg': extract_yelu,
        'acra': extract_acra,
        'bizfile': extract_acra,
    }
    
    extractor = extractors.get(extraction_type)
    if not extractor:
        print(f"Unknown extraction type: {extraction_type}")
        print(f"Available: {', '.join(extractors.keys())}")
        sys.exit(1)
    
    try:
        results = extractor()
        if isinstance(results, str):
            results = json.loads(results)
        print(json.dumps(results, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
