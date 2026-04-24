"""WhatsApp number finder — extracts WhatsApp numbers from websites.

Searches for wa.me links, WhatsApp API links, and text patterns
mentioning WhatsApp near phone numbers.
"""

import re

import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def clean_phone(phone: str) -> str:
    """Clean phone number to +65XXXXXXXX format for Singapore."""
    if not phone:
        return ""
    digits = re.sub(r'[^\d]', '', phone)
    if not digits:
        return ""
    # If 8 digits starting with 6, 8, 9 → SG mobile/landline
    if len(digits) == 8 and digits[0] in ('6', '8', '9'):
        return f"+65{digits}"
    # If already has 65 prefix
    if digits.startswith('65') and len(digits) == 10:
        return f"+{digits}"
    return f"+{digits}" if digits else ""


def find_whatsapp(url: str, phone: str = None, timeout: int = 8) -> tuple:
    """Find WhatsApp number on a website.

    Returns: (whatsapp_number, source)
    source: 'website_link' / 'website_text' / 'phone_match' / 'not_found'
    """
    if not url:
        return ("", "not_found")
    if not url.startswith("http"):
        url = "https://" + url

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SG-Enrich/1.0)"},
            timeout=timeout,
            allow_redirects=True,
            verify=False,
        )
        soup = BeautifulSoup(resp.text, "lxml")

        # Step 1: Search for wa.me links
        wa_links = soup.find_all("a", href=re.compile(
            r'wa\.me|whatsapp\.com/send|api\.whatsapp', re.IGNORECASE
        ))
        for link in wa_links:
            href = link.get("href", "")
            # Extract number from wa.me/NUMBER or api.whatsapp.com/send?phone=NUMBER
            match = re.search(r'(?:wa\.me/|phone=)(\d+)', href)
            if match:
                num = match.group(1)
                cleaned = clean_phone(num)
                if cleaned:
                    return (cleaned, "website_link")

        # Step 2: Search in plain text for WhatsApp mentions near phone numbers
        text = soup.get_text()
        wa_pattern = re.compile(
            r'(?i)whatsapp[:\s]*[\+\(]?(\d[\d\s\-\(\)]{7,14}\d)'
        )
        wa_match = wa_pattern.search(text)
        if wa_match:
            num = wa_match.group(1)
            cleaned = clean_phone(num)
            if cleaned:
                if phone and clean_phone(phone) == cleaned:
                    return (cleaned, "phone_match")
                return (cleaned, "website_text")

        # Step 3: If phone provided, check if it's near WhatsApp text
        if phone:
            cleaned_phone_val = clean_phone(phone)
            # Look for WhatsApp text near the phone number
            phone_pattern = re.compile(
                r'(?i)(?:whatsapp|wa)[\s:]{0,3}.*?' + re.escape(phone[:6]),
                re.DOTALL
            )
            if phone_pattern.search(text):
                return (cleaned_phone_val, "phone_match")

        return ("", "not_found")

    except Exception:
        return ("", "not_found")
