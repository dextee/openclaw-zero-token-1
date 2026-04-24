#!/usr/bin/env python3
"""Decision-maker contact enrichment for Singapore B2B leads.

Extracts emails (priority #1), phone numbers (priority #2), and decision makers
from company websites using SSL bypass, Cloudflare decode, JSON-LD parsing,
and contact page discovery. Zero paid APIs.
"""
import argparse
import csv
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-SG,en;q=0.9",
}

MAX_HTML_BYTES = 250_000

# ── SSL context for broken SG certs ──────────────────────────────────────────
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# ── Regexes ──────────────────────────────────────────────────────────────────
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"([+]\d[\d\s-]{7,})")
CF_EMAIL_RE = re.compile(r'data-cfemail=["\']([0-9a-fA-F]+)["\']', re.IGNORECASE)
WA_RE = re.compile(r'(?:wa\.me|api\.whatsapp\.com/send[^"\']*phone=|whatsapp://send[^"\']*phone=)/?(\+?[\d]{8,15})', re.IGNORECASE)
JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE
)
SG_PHONE_FULL = re.compile(r'(?:\+65|65)[\s\-]?([689]\d{3})[\s\-]?(\d{4})')
SG_PHONE_BARE = re.compile(r'(?<!\d)([689]\d{3})[\s\-]?(\d{4})(?!\d)')
CONTACT_PAGE_RE = re.compile(
    r'href=["\']([^"\']*(?:contact|about|team|people|management|leadership|get[-_]?in[-_]?touch)[^"\']*)["\']',
    re.IGNORECASE
)
INVALID_EMAIL_PATTERNS = re.compile(
    r"\.(png|jpg|jpeg|gif|svg|webp|css|js|json|xml|pdf)@|"
    r"@[a-z0-9]+\.(png|jpg|jpeg|gif|svg|webp|css|js|json|xml|pdf)$",
    re.IGNORECASE,
)

BLOCKED_DOMAINS = {
    "schema.org", "w3.org", "example.com", "siteground.com", "oceanthemes.net",
    "wordpress.org", "elementor.com", "envato.com", "themeforest.net",
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
}
GENERIC_PREFIXES = {
    "info@", "admin@", "support@", "hello@", "contact@", "sales@",
    "enquiry@", "marketing@", "noreply@", "no-reply@", "webmaster@",
    "help@", "careers@", "jobs@", "media@", "press@", "legal@",
}
DM_REJECT_WORDS = {
    "your", "our", "for", "and", "or", "google", "microsoft", "amazon",
    "instagram", "facebook", "automation", "anywhere", "premier", "certified",
    "information", "officer", "interim", "acting", "strategic", "finance",
    "capital", "sales", "marketing", "systems", "management", "consulting",
    "commission", "factory", "partner", "services", "solutions", "technology",
    "group", "holdings", "pte", "ltd", "private", "limited", "incorporated",
    "contact", "us", "about", "team", "home", "menu", "search", "close",
    "news", "blog", "careers", "jobs", "press", "media", "events",
    # Garbage words seen in production from HTML/CSS noise extraction
    "appliances", "honesty", "staying", "integrity", "excellence", "innovation",
    "quality", "reliability", "transparency", "professionalism", "commitment",
    "beamp", "headquartered", "singapore", "academy", "institute", "university",
    "association", "chamber", "federation", "society", "council", "board",
    "redefining", "leading", "trusted", "award", "certified", "accredited",
    "established", "founded", "incorporated", "registered", "licensed",
    # Common label words that aren't personal names
    "event", "name", "email", "phone", "address", "website", "title", "role",
    "position", "department", "office", "location", "profile", "staff",
    "directory", "company", "firm", "business", "enterprise",
}
# Junk title patterns that indicate a non-person entry (used in validation)
JUNK_TITLE_PATTERNS = re.compile(
    r"\b(site\s+visit|meeting|workshop|webinar|event|seminar|conference|launch|opening|ceremony|announcement|signing|award|press\s+release|news|article|blog|post|update|newsletter)\b",
    re.IGNORECASE,
)
TITLE_WORDS = {
    "ceo", "founder", "co-founder", "cofounder", "director", "managing director",
    "m.d.", "md", "coo", "cto", "cfo", "cmo", "head", "vp", "vice president",
    "general manager", "country manager", "partner", "principal", "chairman",
    "president", "owner",
}

# ── ACRA enrichment ──────────────────────────────────────────────────────────
ACRA_RESOURCE_ID = "d_3f960c10fed6145404ca7b821f263b87"
ACRA_CACHE_DIR = "/root/.openclaw/cache/acra"
ACRA_TTL_DAYS = 30
ACRA_NEGATIVE_TTL_DAYS = 7

# ── MAS enrichment ───────────────────────────────────────────────────────────
MAS_CACHE_DIR = "/root/.openclaw/cache/mas"
MAS_TTL_DAYS = 30
SEARXNG_URL = "http://localhost:8080/search"


def _normalize_company_name(name: str) -> str:
    n = name.lower()
    n = re.sub(r"\bpte\b|\bltd\b|\binc\b|\blimited\b|\bprivate\b|\b\.\b", "", n)
    n = re.sub(r"[^a-z0-9]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _cache_path(cache_dir: str, key: str) -> str:
    safe = re.sub(r"[^a-z0-9_-]", "_", key.lower())[:64]
    return os.path.join(cache_dir, f"{safe}.json")


def _cache_load(path: str, ttl_days: int):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        age = (datetime.now() - datetime.fromisoformat(data["_cached_at"])).days
        if age > ttl_days:
            return None
        return data["_payload"]
    except Exception:
        return None


def _cache_save(path: str, payload: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"_cached_at": datetime.now().isoformat(), "_payload": payload}, f)


def acra_lookup(company_name: str) -> dict | None:
    """Return {uen, entity_name, entity_type_desc, uen_status_desc,
    reg_street_name, reg_postal_code} or None. Always safe."""
    try:
        norm = _normalize_company_name(company_name)
        if not norm:
            return None
        cache = _cache_path(ACRA_CACHE_DIR, f"acra_{norm}")
        cached = _cache_load(cache, ACRA_TTL_DAYS)
        if cached is not None:
            return cached if cached else None

        url = (
            f"https://data.gov.sg/api/action/datastore_search"
            f"?resource_id={ACRA_RESOURCE_ID}&q={urllib.parse.quote(norm)}&limit=5"
        )
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "sg-enrich/1.0"})
        best = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=6) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                records = data.get("result", {}).get("records", [])
                norm_tokens = set(norm.split())
                for rec in records:
                    entity = str(rec.get("entity_name", "")).lower()
                    if not entity:
                        continue
                    entity_tokens = set(entity.split())
                    score = len(norm_tokens & entity_tokens)
                    # Reject unless ≥50 % token overlap OR norm is a substring of entity
                    min_score = max(1, len(norm_tokens) // 2)
                    if score < min_score and norm not in entity:
                        continue
                    if best is None or score > best["_match_score"]:
                        best = {
                            "uen": rec.get("uen", ""),
                            "entity_name": rec.get("entity_name", ""),
                            "entity_type_desc": rec.get("entity_type_desc", ""),
                            "uen_status_desc": rec.get("uen_status_desc", ""),
                            "reg_street_name": rec.get("reg_street_name", ""),
                            "reg_postal_code": rec.get("reg_postal_code", ""),
                            "_match_score": score,
                        }
                break
            except Exception:
                time.sleep((1 << attempt) + random.random() * 0.3)

        payload = None
        if best:
            best.pop("_match_score", None)
            payload = best
        _cache_save(cache, payload or {})
        return payload
    except Exception:
        return None


def mas_licensed_check(company_name: str) -> str:
    """Return 'yes' | 'no' | 'unknown'. Uses SearXNG. Never raises."""
    try:
        norm = _normalize_company_name(company_name)
        if not norm:
            return "unknown"
        cache = _cache_path(MAS_CACHE_DIR, f"mas_{norm}")
        cached = _cache_load(cache, MAS_TTL_DAYS)
        if cached is not None:
            return cached.get("licensed", "unknown")

        query = f'site:eservices.mas.gov.sg/fid "{company_name}"'
        encoded = urllib.parse.quote(query)
        url = f"{SEARXNG_URL}?q={encoded}&format=json"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "sg-enrich/1.0"})
        result = "unknown"
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            for r in results:
                u = r.get("url", "")
                if "/fid/institution/detail/" in u:
                    result = "yes"
                    break
            if result == "unknown" and results:
                result = "no"
        except Exception:
            pass

        _cache_save(cache, {"licensed": result})
        return result
    except Exception:
        return "unknown"



def print_progress(msg):
    print(f"PROGRESS: {msg}", flush=True)


def fetch(url, timeout=8):
    if not url or not url.startswith("http"):
        return ""
    req = urllib.request.Request(url, headers=HEADERS)
    for _url in (url, url.replace("https://", "http://", 1)):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                return resp.read(MAX_HTML_BYTES).decode("utf-8", errors="ignore")
        except Exception:
            if _url == url:
                req = urllib.request.Request(_url.replace("https://", "http://", 1), headers=HEADERS)
            continue
    return ""


def decode_cf_email(encoded):
    if len(encoded) < 4:
        return ""
    try:
        key = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
    except Exception:
        return ""


def _jsonld_scan(obj, out):
    if isinstance(obj, dict):
        if obj.get("@type") in ("Person", "ContactPoint"):
            name = obj.get("name", "")
            job = obj.get("jobTitle", "")
            email = obj.get("email", "")
            # jobTitle and name can be lists in some schemas
            if isinstance(name, list):
                name = name[0] if name else ""
            if isinstance(job, list):
                job = job[0] if job else ""
            if isinstance(email, list):
                email = email[0] if email else ""
            name = str(name).strip()
            job = str(job).strip()
            if name and job:
                out["people"].append((name, job))
            if email:
                out["emails"].append(str(email).strip())
        for v in obj.values():
            _jsonld_scan(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _jsonld_scan(v, out)


def extract_jsonld(html):
    out = {"emails": [], "people": []}
    for block in JSONLD_RE.findall(html):
        try:
            _jsonld_scan(json.loads(block), out)
        except Exception:
            continue
    return out


def is_valid_email(email):
    if INVALID_EMAIL_PATTERNS.search(email):
        return False
    user, _, domain = email.partition("@")
    if not user or not domain:
        return False
    if "." not in domain:
        return False
    if "@2x" in email or "@3x" in email or email.startswith("."):
        return False
    if re.fullmatch(r"[0-9a-f]{12,}", user, re.I):
        return False
    if re.search(r"20\d{2}[-_]?\d{2}[-_]?\d{2}", user):
        return False
    if "-@-" in email or "_at_" in email.lower():
        return False
    # Reject emails with HTML/JSON unicode escape prefix e.g. "u003esales@domain.com" (> = >)
    if re.match(r'^u[0-9a-f]{4}[a-z]', user, re.I):
        return False
    if domain.lower() in BLOCKED_DOMAINS:
        return False
    if _PLACEHOLDER_PREFIXES.match(user):
        return False
    return True


def extract_emails(html):
    found = list(set(e for e in EMAIL_RE.findall(html) if is_valid_email(e)))
    for encoded in CF_EMAIL_RE.findall(html):
        dec = decode_cf_email(encoded)
        if dec and is_valid_email(dec) and dec not in found:
            found.append(dec)
    jld = extract_jsonld(html)
    for e in jld["emails"]:
        if is_valid_email(e) and e not in found:
            found.append(e)
    return found


def extract_phones(html):
    raw = list(set(PHONE_RE.findall(html)))
    for m in SG_PHONE_FULL.findall(html):
        raw.append(f"+65 {m[0]} {m[1]}")
    for m in SG_PHONE_BARE.findall(html):
        raw.append(f"+65 {m[0]} {m[1]}")
    return raw


def clean_phone(phone):
    digits = re.sub(r"[^\d+]", "", phone)
    if len(digits) < 8 or len(set(digits)) <= 2:
        return ""
    if digits.startswith("65") and len(digits) == 10:
        return "+" + digits
    if len(digits) == 8 and digits[0] in "689":
        return "+65" + digits
    if digits.startswith("+") and len(digits) >= 10:
        return digits
    if len(digits) >= 10:
        return "+" + digits
    return ""


def discover_contact_pages(html, base_url):
    found = set()
    for m in CONTACT_PAGE_RE.finditer(html):
        href = m.group(1)
        if href.startswith("http"):
            found.add(href)
        elif href.startswith("/"):
            parsed = urllib.parse.urlparse(base_url)
            found.add(f"{parsed.scheme}://{parsed.netloc}{href}")
    return list(found)


def extract_decision_makers(html):
    found = []
    seen = set()
    # Strip HTML tags, then decode HTML entities (&nbsp; &copy; &amp; etc.)
    import html as _htmllib
    text = re.sub(r"<[^>]+>", " ", html)
    text = _htmllib.unescape(text)
    # Collapse multi-whitespace (from &nbsp; and similar)
    text = re.sub(r"[\xa0 ​]+", " ", text)  # non-breaking spaces
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) > 200:
            continue
        has_title = any(t in line.lower() for t in TITLE_WORDS)
        if not has_title:
            continue
        for sep in (" — ", " – ", " - ", " | ", ", ", "  ", "\t"):
            if sep in line:
                parts = line.split(sep, 1)
                name_part = parts[0].strip()
                title_part = parts[1].strip()
                if 3 <= len(name_part) <= 35 and len(title_part) <= 60:
                    if JUNK_TITLE_PATTERNS.search(title_part):
                        continue
                    words = name_part.split()
                    if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
                        if any(w.lower().rstrip(".,;:") in DM_REJECT_WORDS for w in words):
                            continue
                        while words and words[-1].lower().rstrip(".") in TITLE_WORDS:
                            words.pop()
                        if not words:
                            continue
                        clean_name = " ".join(words)
                        key = (clean_name.lower(), title_part.lower())
                        if key not in seen:
                            seen.add(key)
                            found.append((clean_name, title_part))
                        break
    html_patterns = [
        r'<(h3|h4)[^>]*>([^<]{3,40})</\1>\s*(?:<[^>]+>){0,5}\s*<(p|div|span)[^>]*>([^<]{3,60}(?:CEO|Founder|Director|Manager|Head|President|Partner)[^<]{0,40})</\3>',
        r'<(div|span)[^>]*>([^<]{3,40})</\1>\s*(?:<[^>]+>){0,3}\s*<(div|span|p)[^>]*>([^<]{3,60}(?:CEO|Founder|Director|Manager|Head|President|Partner)[^<]{0,40})</\3>',
    ]
    for pat in html_patterns:
        for m in re.finditer(pat, html, re.IGNORECASE | re.DOTALL):
            name = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            title = re.sub(r"<[^>]+>", "", m.group(4)).strip()
            words = name.split()
            if name and title and 2 <= len(words) <= 4 and len(title) <= 60:
                if JUNK_TITLE_PATTERNS.search(title):
                    continue
                if any(w.lower().rstrip(".,;:") in DM_REJECT_WORDS for w in words):
                    continue
                while words and words[-1].lower().rstrip(".") in TITLE_WORDS:
                    words.pop()
                if not words:
                    continue
                clean_name = " ".join(words)
                key = (clean_name.lower(), title.lower())
                if key not in seen:
                    seen.add(key)
                    found.append((clean_name, title))
    jld = extract_jsonld(html)
    for name, title in jld["people"]:
        words = name.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
            if any(w.lower().rstrip(".,;:") in DM_REJECT_WORDS for w in words):
                continue
            key = (name.lower(), title.lower())
            if key not in seen:
                seen.add(key)
                found.append((name, title))
    return found


BLOCKED_EMAIL_PATTERNS = {
    "user@domain.com", "user@example.com", "test@test.com", "admin@localhost",
    "email@domain.com", "name@domain.com", "info@domain.com", "contact@domain.com",
}
# Prefixes that are clearly placeholder/example names in emails
_PLACEHOLDER_PREFIXES = re.compile(
    r"^(?:jane\.?doe|john\.?doe|firstname|lastname|yourname|example|dummy|sample|placeholder|test\.?user|user\d*|admin\d*)\b",
    re.IGNORECASE,
)

def _domain_root_tokens(domain):
    """Extract brand tokens from a domain for cross-checking.
    e.g., 'hans.com.sg' -> {'hans'},  'poshliving.com.sg' -> {'poshliving'}"""
    if not domain:
        return set()
    d = domain.lower().strip()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    d = d.split("/")[0].split("?")[0].split("#")[0]
    # Strip common TLDs/ccTLDs
    for tld in (".com.sg", ".co.sg", ".net.sg", ".org.sg", ".sg",
                ".com.my", ".com",  ".net", ".org", ".io", ".co"):
        if d.endswith(tld):
            d = d[:-len(tld)]
            break
    # Split on . and - (for multi-token domains like "posh-living")
    parts = [p for p in re.split(r"[.\-]", d) if len(p) >= 2]
    return set(parts)


def pick_best_email(emails, company_domain=""):
    """Pick the best email. If company_domain given, prefer emails whose domain
    shares a brand token with the company's website (reject unrelated scraped emails).
    """
    if not emails:
        return ""
    directory_domains = {"yelu.sg", "yellowpages.com.sg", "yellowpages.sg", "kompass.com", "dnb.com"}
    # Reject emails from directory sites and obvious placeholders
    clean = [e for e in emails if not any(d in e.lower() for d in directory_domains)]
    clean = [e for e in clean if e.lower() not in BLOCKED_EMAIL_PATTERNS]

    # ── Email-domain cross-check ──
    # When we know the company's website, ONLY accept emails whose domain shares
    # a brand token with the company's website. This blocks unrelated scraped
    # emails (e.g., Han's Cafe at hans.com.sg getting "info@stagheaddesigns.com").
    # Better to return no email than a wrong one.
    if company_domain:
        co_tokens = _domain_root_tokens(company_domain)
        if co_tokens:
            matching = []
            for e in clean:
                email_domain = e.split("@")[-1].lower() if "@" in e else ""
                em_tokens = _domain_root_tokens(email_domain)
                # Accept if any brand token overlaps (company:hans + email:hans.com.sg)
                if co_tokens & em_tokens:
                    matching.append(e)
            clean = matching  # strict: only return domain-matched emails
            if not clean:
                return ""  # no valid match → no email is better than wrong email

    direct = [e for e in clean if not any(e.lower().startswith(g) for g in GENERIC_PREFIXES)]
    chosen = direct if direct else clean
    if not chosen:
        return ""
    sg_emails = [e for e in chosen if e.lower().endswith((".com.sg", ".sg"))]
    return sg_emails[0] if sg_emails else chosen[0]


def pick_best_phone(phones):
    cleaned = [clean_phone(p) for p in phones if clean_phone(p)]
    if not cleaned:
        return ""
    sg = [p for p in cleaned if p.startswith("+65")]
    return sg[0] if sg else cleaned[0]


def pick_best_dm(dms, top_n=3, company_name=""):
    """Return top N decision makers ranked by title seniority. Returns list of (score, name, title).

    If company_name is given, filter out DMs whose title/affiliation doesn't
    share a brand token with the target company. Blocks cross-contamination
    from search results that mention the company but extract unrelated people
    (e.g., "Anshul Laroia - Global Commercial" for Coffee Bean Singapore).
    """
    if not dms:
        return []
    priority = {
        "ceo": 1, "founder": 2, "co-founder": 2, "cofounder": 2,
        "managing director": 3, "director": 4, "country manager": 5,
        "head of": 6, "partner": 7, "vp": 8, "vice president": 8,
        "coo": 9, "cto": 9, "cfo": 9, "cmo": 9,
    }
    seen_names = set()
    scored = []
    for name, title in dms:
        if name.lower() in seen_names:
            continue
        # Cross-check: DM title/affiliation must reference target company
        if company_name and not _dm_title_matches_company(title, company_name):
            continue
        seen_names.add(name.lower())
        tlower = title.lower()
        score = 99
        for k, v in priority.items():
            if k in tlower:
                score = v
                break
        scored.append((score, name, title))
    scored.sort()
    return scored[:top_n]


def extract_whatsapp(html):
    """Extract WhatsApp number from wa.me links or whatsapp:// URIs."""
    for m in WA_RE.finditer(html):
        num = re.sub(r"[^\d+]", "", m.group(1))
        if num.startswith("65") and len(num) == 10:
            return "+" + num
        if len(num) == 8 and num[0] in "689":
            return "+65" + num
        if len(num) >= 10:
            return "+" + num.lstrip("+")
    return ""


def normalize_domain(url):
    if not url:
        return ""
    url = str(url).lower().strip()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    url = re.sub(r"/.*$", "", url)
    return url


def searxng_search(query, limit=8):
    encoded = urllib.parse.quote(query)
    url = f"http://localhost:8080/search?q={encoded}&format=json"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "sg-enrich/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {"results": []}


_DM_GENERIC_WORDS = {
    "pte", "ltd", "private", "limited", "group", "holdings", "co", "corp",
    "pl", "inc", "llp", "llc", "the", "and", "of", "at", "in", "for",
    "services", "solutions", "singapore", "sg", "asia", "international",
    "group", "enterprises", "partners", "partnership",
}


def _dm_title_matches_company(title, company_name):
    """Check if DM's title/affiliation contains at least one brand token from the company.

    Uses substring matching so "Swensen's" matches "Swensens", "Hans" matches "Hans Cafe".
    Rejects cases like: target="Shiok Kitchen Catering" but DM title is
    "Lai Fong - National University of Singapore" (no shared tokens).
    Accepts: target="Soup Restaurant", DM title "Executive Director at Soup Restaurant".
    """
    co_tokens = {
        w.lower() for w in re.sub(r"[^a-zA-Z0-9 ]", " ", company_name).split()
        if len(w) >= 3 and w.lower() not in _DM_GENERIC_WORDS
    }
    if not co_tokens:
        return True  # No meaningful brand tokens to check — don't filter
    title_lower = re.sub(r"[^a-zA-Z0-9 ]", " ", title).lower()
    title_tokens = [w for w in title_lower.split() if len(w) >= 3]
    # Substring match: company token appears as prefix of any title token (or vice versa)
    # Catches "swensen" ⊆ "swensens", "hans" ⊆ "hans", "shiok" ⊆ "shiok"
    for co in co_tokens:
        for tt in title_tokens:
            if co in tt or tt in co:
                return True
    return False


def _parse_dm_from_title(title, company_name):
    """Extract (name, role) from a search result title like 'John Tan - CEO at Acme | LinkedIn'."""
    # Decode HTML entities and collapse whitespace (guard against &nbsp; &copy; etc.)
    import html as _htmllib
    title = _htmllib.unescape(title or "")
    title = re.sub(r"\s+", " ", title).strip()
    # Strip site name suffix
    title = re.sub(
        r'\s*[|\-–]\s*(LinkedIn|Facebook|Twitter|Bloomberg|Crunchbase|ContactOut|ZoomInfo|RocketReach|Hunter\.io|Lusha|SignalHire).*$',
        '', title, flags=re.IGNORECASE,
    ).strip()
    for sep in [' - ', ' | ', ' – ', '—', ', ']:
        if sep in title:
            parts = title.split(sep, 1)
            name_part = parts[0].strip()
            rest = parts[1].strip()
            words = name_part.split()
            if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
                # Strip trailing punctuation when checking reject words
                if any(w.lower().rstrip(".,;:") in DM_REJECT_WORDS for w in words):
                    continue
                if JUNK_TITLE_PATTERNS.search(rest):
                    continue
                has_title = any(t in rest.lower() for t in TITLE_WORDS)
                if not has_title:
                    continue
                # Cross-check: DM's title/affiliation must reference the target company.
                # Blocks cross-contamination like "Lai Fong - NUS" for Shiok Kitchen.
                if not _dm_title_matches_company(rest, company_name):
                    continue
                # Reject long prose (LinkedIn post content, not a title)
                # Real titles are short; post content has lots of punctuation/sentences
                if len(rest) > 80 or rest.count(';') >= 2 or rest.count('.') >= 3:
                    continue
                return (name_part, rest)
    return None


def find_contacts_via_search(company_name):
    contacts = {"emails": [], "phones": [], "people": []}
    # Strip parentheticals and legal suffixes for cleaner search queries
    search_name = re.sub(r"\s*\(.*\)\s*$", "", company_name).strip()
    search_name = re.sub(r"\s+(?:pte\.?\s*ltd\.?|private\s+limited|ltd\.?|inc\.?|corp\.?|co\.?)$", "", search_name, flags=re.IGNORECASE).strip()

    queries = [
        f'"{search_name}" CEO OR founder OR director Singapore',
        f'site:linkedin.com/in "{search_name}" Singapore',
        f'"{search_name}" contact email Singapore',
    ]
    search_name_lower = search_name.lower()
    # Key tokens from the company name (ignore generic words)
    _generic = {"pte", "ltd", "private", "limited", "group", "holdings", "co", "corp", "construction", "services", "solutions", "international", "singapore"}
    company_tokens = {w for w in re.sub(r"[^a-z0-9 ]", " ", search_name_lower).split() if w not in _generic and len(w) > 2}

    for q in queries:
        data = searxng_search(q, limit=5)
        for r in data.get("results", []):
            title = r.get("title", "")
            snippet = r.get("content", "") or ""
            url = r.get("url", "")
            combined = (title + " " + snippet).lower()

            # Only accept this result if it mentions the company
            result_mentions_company = (
                search_name_lower in combined or
                (company_tokens and sum(1 for t in company_tokens if t in combined) >= max(1, len(company_tokens) // 2))
            )

            # Extract emails and phones from snippet regardless (they may be generic contact info)
            for e in extract_emails(title + " " + snippet):
                if e not in contacts["emails"]:
                    contacts["emails"].append(e)
            for p in extract_phones(title + " " + snippet):
                cp = clean_phone(p)
                if cp and cp not in contacts["phones"]:
                    contacts["phones"].append(cp)

            # Only extract DMs if result is about the target company
            if result_mentions_company:
                dm = _parse_dm_from_title(title, search_name)
                if dm and dm not in contacts["people"]:
                    contacts["people"].append(dm)

            # Fetch contact pages for deeper extraction (only if relevant)
            if result_mentions_company and ("linkedin.com/in/" in url or "contact" in url.lower()):
                html = fetch(url, timeout=5)
                if html:
                    for e in extract_emails(html):
                        if e not in contacts["emails"]:
                            contacts["emails"].append(e)
                    for p in extract_phones(html):
                        cp = clean_phone(p)
                        if cp and cp not in contacts["phones"]:
                            contacts["phones"].append(cp)
                    for person in extract_decision_makers(html):
                        if person not in contacts["people"]:
                            contacts["people"].append(person)
    return contacts


def enrich_contact(lead):
    url = lead.get("website", "").strip()
    company = lead.get("company_name", "").strip()
    if not url or not url.startswith("http"):
        return lead

    all_emails = []
    all_phones = []
    all_people = []
    all_wa = []

    # Fetch homepage + discover contact pages from it
    html = fetch(url, timeout=6)
    contact_urls = []
    if html:
        all_emails.extend(extract_emails(html))
        for p in extract_phones(html):
            cp = clean_phone(p)
            if cp:
                all_phones.append(cp)
        all_people.extend(extract_decision_makers(html))
        contact_urls = discover_contact_pages(html, url)
        wa = extract_whatsapp(html)
        if wa:
            all_wa.append(wa)

    parsed = urllib.parse.urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    for path in ("/contact", "/contact-us", "/about-us", "/team", "/leadership"):
        contact_urls.append(base + path)
    seen_urls = set()
    unique_urls = []
    for u in contact_urls:
        if u not in seen_urls:
            seen_urls.add(u)
            unique_urls.append(u)

    for page_url in unique_urls[:4]:
        page_html = fetch(page_url, timeout=6)
        if page_html:
            all_emails = list(dict.fromkeys(all_emails + extract_emails(page_html)))
            for p in extract_phones(page_html):
                cp = clean_phone(p)
                if cp and cp not in all_phones:
                    all_phones.append(cp)
            all_people = list(dict.fromkeys(all_people + extract_decision_makers(page_html)))
            wa = extract_whatsapp(page_html)
            if wa and wa not in all_wa:
                all_wa.append(wa)

    # Search augmentation — always run for LinkedIn DM discovery
    if len(all_people) < 3 or not all_emails:
        search_contacts = find_contacts_via_search(company)
        for e in search_contacts["emails"]:
            if e not in all_emails:
                all_emails.append(e)
        for p in search_contacts["phones"]:
            if p not in all_phones:
                all_phones.append(p)
        for person in search_contacts["people"]:
            if person not in all_people:
                all_people.append(person)

    # Filter DMs whose title doesn't reference target company (blocks cross-contamination)
    company_name = (lead.get("company_name") or "").strip()
    top_people = pick_best_dm(all_people, top_n=3, company_name=company_name)
    # Pass company website so pick_best_email can reject unrelated domains
    company_site = (lead.get("website") or lead.get("domain") or "").strip()
    chosen_email = pick_best_email(all_emails, company_domain=company_site)
    chosen_phone = pick_best_phone(all_phones)

    # Primary contact — kept as decision_maker_name/title for backward compat
    if top_people:
        lead["decision_maker_name"] = top_people[0][1]
        lead["decision_maker_title"] = top_people[0][2]
    # Additional contacts
    for i, person in enumerate(top_people[:3], start=1):
        lead[f"contact_{i}_name"] = person[1]
        lead[f"contact_{i}_title"] = person[2]

    if chosen_email:
        lead["direct_email"] = chosen_email
    if chosen_phone:
        lead["direct_phone"] = chosen_phone
    if all_wa:
        lead["whatsapp"] = all_wa[0]

    lead["_contacts_found"] = f"{len(top_people)} people, {len(all_emails)} emails, {len(all_phones)} phones"
    return lead


def main():
    parser = argparse.ArgumentParser(description="Enrich leads with decision-maker contacts")
    parser.add_argument("input", help="Input CSV path")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--workers", type=int, default=3, help="Concurrent workers (default: 3, max: 4)")
    parser.add_argument("--limit", type=int, default=0, help="Max leads to process (0=all). Use ≤10 per batch for stability.")
    parser.add_argument("--offset", type=int, default=0, help="Start at row N (0-based). Use with --limit for chunked batches.")
    parser.add_argument("--acra", action=argparse.BooleanOptionalAction, default=False, help="ACRA UEN lookup (disabled — data.gov.sg API unreliable)")
    parser.add_argument("--mas", action=argparse.BooleanOptionalAction, default=False, help="MAS licensed check via SearXNG (default: off — smoke-test gated, defer to v2)")
    args = parser.parse_args()

    workers = min(args.workers, 4)

    with open(args.input, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for col in [
        "direct_email", "direct_phone", "whatsapp",
        "decision_maker_name", "decision_maker_title",
        "contact_1_name", "contact_1_title",
        "contact_2_name", "contact_2_title",
        "contact_3_name", "contact_3_title",
        "mas_licensed", "_contacts_found",
    ]:
        if col not in fieldnames:
            fieldnames.append(col)

    # Apply offset + limit for chunked batch processing
    if args.offset > 0:
        rows = rows[args.offset:]
    if args.limit > 0:
        rows = rows[:args.limit]

    total = len(rows)
    print_progress(f"0/{total} — Starting contact enrichment for {total} leads")

    enriched = []
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(enrich_contact, dict(row)): row for row in rows}
        for future in as_completed(futures):
            enriched.append(future.result())
            completed += 1
            if completed % 2 == 0 or completed == total:
                print_progress(f"{completed}/{total} — Contact enrichment ({round(completed/total*100)}%)")

    # ── Phase 1: ACRA enrichment ──
    if args.acra:
        print_progress(f"0/{total} — ACRA lookup")
        acra_done = 0
        for lead in enriched:
            acra = acra_lookup(lead.get("company_name", ""))
            if acra:
                lead["uen"] = acra.get("uen", "")
                lead["entity_type_desc"] = acra.get("entity_type_desc", "")
                lead["uen_status_desc"] = acra.get("uen_status_desc", "")
                lead["reg_street_name"] = acra.get("reg_street_name", "")
                lead["reg_postal_code"] = acra.get("reg_postal_code", "")
            acra_done += 1
            if acra_done % 2 == 0 or acra_done == total:
                print_progress(f"{acra_done}/{total} — ACRA lookup ({round(acra_done/total*100)}%)")

    # ── Phase 2: MAS licensed check (smoke-test gated) ──
    if args.mas:
        print_progress(f"0/{total} — MAS licensed check")
        mas_done = 0
        for lead in enriched:
            lead["mas_licensed"] = mas_licensed_check(lead.get("company_name", ""))
            mas_done += 1
            if mas_done % 2 == 0 or mas_done == total:
                print_progress(f"{mas_done}/{total} — MAS check ({round(mas_done/total*100)}%)")

    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched)

    summary = {
        "status": "success",
        "input": args.input,
        "output": args.output,
        "processed": len(enriched),
        "with_dm_name": sum(1 for r in enriched if r.get("decision_maker_name", "").strip()),
        "with_email": sum(1 for r in enriched if r.get("direct_email", "").strip()),
        "with_phone": sum(1 for r in enriched if r.get("direct_phone", "").strip()),
        "with_acra": sum(1 for r in enriched if r.get("uen", "").strip()),
        "mas_yes": sum(1 for r in enriched if r.get("mas_licensed") == "yes"),
    }
    print(f"ENRICHMENT_SUMMARY: {json.dumps(summary)}", flush=True)


if __name__ == "__main__":
    main()
