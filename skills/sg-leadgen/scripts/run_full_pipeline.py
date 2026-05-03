#!/usr/bin/env python3
"""One-shot sg-leadgen pipeline: search → extract → enrich → dedup → CSV."""
import argparse
import csv
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
LEADS_DIR = "/root/.openclaw/workspace/leads"

# Optional: industry synonyms + cross-run seen-companies (fail gracefully if missing)
try:
    from industry_synonyms import expand_industry, is_unknown_industry
    _SYNONYMS_OK = True
except ImportError:
    _SYNONYMS_OK = False
    def expand_industry(x):  # type: ignore
        return [x]
    def is_unknown_industry(x):  # type: ignore
        return False

try:
    from seen_companies import filter_new, commit as commit_seen, get_run_count
    _SEEN_OK = True
except ImportError:
    _SEEN_OK = False
    def filter_new(rows, industry=""):  # type: ignore
        return rows, []
    def commit_seen(*a, **kw):  # type: ignore
        pass
    def get_run_count(industry: str) -> int:  # type: ignore
        return 0

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

# ── Regexes ──────────────────────────────────────────────────────────────────
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"([+]\d[\d\s-]{7,})")
CF_EMAIL_RE = re.compile(r'data-cfemail=["\']([0-9a-fA-F]+)["\']', re.IGNORECASE)
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

# ── Blocked / generic filters ────────────────────────────────────────────────
INVALID_EMAIL_PATTERNS = re.compile(
    r"\.(png|jpg|jpeg|gif|svg|webp|css|js|json|xml|pdf)@|"
    r"@[a-z0-9]+\.(png|jpg|jpeg|gif|svg|webp|css|js|json|xml|pdf)$",
    re.IGNORECASE,
)
BLOCKED_DOMAINS = {
    "schema.org", "w3.org", "example.com", "domain.com", "siteground.com", "oceanthemes.net",
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
    # Common English words that look capitalised but aren't names
    "appliances", "honesty", "staying", "integrity", "excellence", "quality",
    "innovation", "commitment", "sustainability", "transparency", "reliability",
    "welcome", "overview", "summary", "mission", "vision", "values", "purpose",
    "headquarters", "headquartered", "established", "founded", "incorporated",
    "overview", "introduction", "background", "history", "singapore",
}
TITLE_WORDS = {
    "ceo", "founder", "co-founder", "cofounder", "director", "managing director",
    "m.d.", "md", "coo", "cto", "cfo", "cmo", "head", "vp", "vice president",
    "general manager", "country manager", "partner", "principal", "chairman",
    "president", "owner",
}
# Word-boundary regex for TITLE_WORDS — prevents "partner" matching "partnerships", "head" matching "headquarters"
_TITLE_WORDS_RE = re.compile(
    r'\b(?:' + '|'.join(re.escape(t) for t in sorted(TITLE_WORDS, key=len, reverse=True)) + r')\b',
    re.IGNORECASE
)

# ── Brand-token filter (cross-industry junk name rejection) ─────────────────
# A name has a brand token if it contains at least one word that is neither a
# generic business word nor an industry-specific descriptor. Names with a
# corporate suffix (Pte, Ltd, LLP, …) always pass — they're legally registered.
GENERIC_WORDS = {
    # Purely generic business descriptors (never brand tokens)
    "service", "services", "solution", "solutions", "company", "companies",
    "firm", "firms", "group", "agency", "agencies", "consulting", "consultancy",
    "professional", "specialist", "specialists", "expert", "experts",
    "provider", "providers", "contractor", "contractors", "contracting",
    "work", "works", "project", "projects", "management",
    "maintenance", "operation", "operations", "integrated",
    "advanced", "total", "global", "enterprise", "one", "stop",
    "digital", "marketing", "support", "it", "ict",
    "system", "systems", "media", "development",
    "security", "data", "network", "communication", "communications",
    "finance", "financial", "accounting", "legal", "recruitment", "staffing",
    "supply", "chain", "property", "real", "estate", "facilities",
    "wholesale", "import", "export",
    # Location words
    "singapore", "sg", "asia",
    # Articles, prepositions, pronouns
    "the", "a", "an", "and", "or", "for", "of", "in", "at", "to", "by", "&",
    "our", "your", "us", "we", "you", "with", "new",
    # Superlatives and promotional words
    "best", "top", "premier", "premium", "leading", "award", "winning",
    "trusted", "welcome", "home", "about", "contact", "get", "touch",
    "make", "dream", "reality", "turn", "explore", "discover", "experience",
    "become", "good", "great",
    # General descriptors
    "general", "commercial", "residential", "industrial", "corporate",
    "local", "national", "international", "certified", "licensed", "accredited",
    # Service delivery descriptors
    "packages", "package", "plan", "plans", "scheme", "rates", "pricing",
    # Property types — not brand tokens
    "condominium", "condo", "hdb", "shophouse", "apartment", "office", "landed",
}
_CORP_SUFFIX_RE = re.compile(
    r'\b(pte|ltd|llp|llc|corp|inc|pl|co\.?|group|holdings)\b', re.I
)


def has_brand_token(name, industry_terms=()):
    """Return True if name contains at least one word that is not a generic
    business word and not a plain descriptor from the current industry terms.
    Names with a corporate suffix always pass (they are legally registered).
    Apply only to 3+ word names; shorter names bypass this check.
    """
    if _CORP_SUFFIX_RE.search(name):
        return True
    bad = GENERIC_WORDS | {
        w.lower().strip(".,&-")
        for term in industry_terms
        for w in term.split()
        if len(w) >= 3
    }
    # Split on spaces AND hyphens so "Fit-Out" → ["fit", "out"], both generic
    raw_tokens = [sub for tok in name.split() for sub in tok.split("-")]
    words = [w.lower().strip(".,&") for w in raw_tokens if len(w) >= 2]
    return any(w and w not in bad for w in words)


# ── Low-quality filters ──────────────────────────────────────────────────────
LOW_QUALITY_TITLE_PATTERNS = [
    r"^top\s+\d+", r"^best\s+\d+", r"^\d+\s+best", r"^\d+\s+top",
    r"ranking\b", r"ranked\b", r"company\s+ranking",
    r"list\s+of",
    r"fintech\s+companies", r"startup\s+companies",
    r"complete\s+guide", r"your\s+complete\s+guide",
    r"festival\s+\d", r"festival\s+202", r"association\b", r"directory\b",
    r"what\s+is\s+", r"how\s+to\s+", r"home\s*$", r"blog\b", r"news\b",
    r"article\b", r"sustaining\s+growth",
    r"visit\s+singapore", r"mice\b", r"event\s+listing",
    r" government's ", r"government\b", r"mas\.gov\.sg",
    r"builtinsingapore\.com", r"techinasia\.com",
    r"big-picture\.com", r"builtin\.com",
    r"careers\b", r"jobs\b", r"portal\b", r"mycareersfuture",
    r"job\s+portal", r"startups\s+in",
    r"download\b", r"report\b", r"vulnerability\b", r"watch\b",
    r"session\s+recording", r"co-working\b", r"coworking\b",
    r"rise\s+as", r"deep\s+dive", r"investment\s+and",
    r"shaping\s+policy", r"pr\s+partner", r"legal\s*$",
    r"app\s+now", r"qr\d+", r"statista\b",
    # Association/directory category entries — not real company names
    r"certified\s+firms?\b", r"registered\s+firms?\b", r"approved\s+firms?\b",
    r"member\s+companies\b", r"accredited\s+companies\b",
]

LOW_QUALITY_DOMAIN_PATTERNS = [
    r"visitsingapore\.com", r"builtin\.com", r"builtinsingapore\.com",
    r"lusha\.com", r"apollo\.io", r"zoominfo\.com", r"crunchbase\.com", r"ensun\.io",
    r"getprospect\.com", r"getprospect\.io", r"contactout\.com", r"rocketreach\.co",
    r"hunter\.io", r"skrapp\.io", r"snov\.io", r"uplead\.com",
    r"big-picture\.com", r"techinasia\.com", r"fintechnews\.sg",
    r"mas\.gov\.sg", r"pwc\.com", r"mckinsey\.com", r"deloitte\.com",
    r"sgpbusiness\.com", r"emis\.com", r"tracxn\.com", r"bouncewatch\.com",
    r"mycareersfuture\.gov\.sg", r"jobs\.", r"careers\.",
    r"fintechfestival\.sg", r"ceec\.org\.sg", r"statista\.com",
    r"tech\.gov\.sg", r"gftn\.co", r"selbyjennings\.com",
    r"qr\d+\.be", r"allenandgledhill\.com", r"cognitomedia\.com",
    r"tenity\.com",
    # Loan/finance providers (not the target — we want SMEs that need loans, not loan providers)
    r"ibusinessloan\.com", r"smesg\.com", r"gbhelios\.com",
    r"moneylender", r"capitall\.sg", r"validus\.sg", r"funding\.sg",
    # Government and academic domains
    r"\.gov\.sg$", r"\.edu\.sg$", r"\.ac\.sg$", r"\.nus\.edu$",
    r"\.ntu\.edu$", r"\.smu\.edu$", r"\.suss\.edu$",
    # Law firms, consultancies, big-four, LEI registries
    r"dlapiper\.com", r"dlapiperintelligence\.com", r"rahmatlim\.com",
    r"jtlegal\.com", r"kpmg\.com", r"ey\.com", r"grantthornton\.com",
    r"lei\.bloomberg\.com", r"bloomberg\.com",
    # Chambers, associations, directories, event orgs
    r"chambers\.com", r"britcham\.org\.sg", r"companies\.sg",
    r"singaporefintech\.org", r"switchsg\.org", r"acclime\.com",
    r"robeco\.com", r"fintech-consult\.com", r"globalfintechinstitute\.org",
    r"sgfintech-sg\.com", r"heysara\.sg",
    # Dictionaries and unrelated reference sites
    r"merriam-webster\.com", r"oxfordlearnersdictionaries\.com",
    r"collinsdictionary\.com", r"dictionary\.cambridge\.org",
    r"hsbcinnovationbanking\.com",
    r"baidu\.com", r"zhidao\.baidu\.com",
    r"zhihu\.com", r"runoob\.com", r"csdn\.net",
    # News, think-tank, and research/consulting article domains
    r"brookings\.edu", r"fortunebusinessinsights\.com", r"thomsonreuters\.com",
    r"cnbc\.com", r"time\.com", r"weforum\.org", r"mordorintelligence\.com",
    r"analysysmason\.com", r"gartner\.com", r"forrester\.com", r"idc\.com",
    # Major platform portals — not company websites
    r"grabacademy", r"grab\.com",
    r"twitter\.com", r"x\.com", r"facebook\.com", r"instagram\.com",
    r"youtube\.com", r"tiktok\.com", r"pinterest\.com",
    # App stores and platforms
    r"apps\.apple\.com", r"play\.google\.com",
    # Job boards — company profiles on job boards are not company websites
    r"foundit\.sg", r"foundit\.in", r"jobstreet\.com", r"jobscentral\.com\.sg",
    r"indeed\.com", r"linkedin\.com", r"glassdoor\.com", r"seek\.com\.au",
    r"monster\.com", r"careerjet\.sg",
    # Singapore construction/industry directories
    r"asiabuilders\.com\.sg", r"sgprocessindustries\.com",
    r"yellowpages\.com\.sg", r"sgdirectory\.sg", r"businesslist\.com\.sg",
    r"bizvibe\.com", r"smergers\.com", r"smehorizon\.com",
    r"bizdirlib\.com", r"recordowl\.com", r"wallpapertoon\.com",
    r"bilkuj\.com", r"amkio\.com", r"lonelyplanet\.com",
    r"optimathemes\.com",
    r"sgcustomerservicenumbers\.com", r"singapore-sme\.com",
    r"kompass\.com", r"dnb\.com", r"dunn-bradstreet\.com",
    r"scal\.com\.sg", r"bca\.gov\.sg",
    r"timesdirectories\.com", r"singapore\.businesslist\.", r"bizhub\.sg",
    # Review and listing aggregators — not company websites
    r"yelp\.com", r"tripadvisor\.com", r"google\.com/maps",
    # Academic journals and research portals (not companies)
    r"academypublishing\.org", r"journalsonline\.", r"springer\.com",
    r"sciencedirect\.com", r"researchgate\.net", r"arxiv\.org",
    r"mdpi\.com", r"ieee\.org", r"acm\.org", r"wiley\.com",
    r"tandfonline\.com", r"frontiersin\.org", r"elsevier\.com",
]

# Global brands that commonly appear in "top fintech" listicles but are not SG-based
GLOBAL_BRAND_DOMAINS = {
    "shopify.com", "robinhood.com", "wealthsimple.com", "intuit.com",
    "upstart.com", "square.com", "stripe.com", "plaid.com", "klarna.com",
    "affirm.com", "nubank.com", "revolut.com", "monzo.com", "n26.com",
    "chime.com", "sofi.com", "betterment.com", "coinbase.com", "binance.com",
    "kraken.com", "gemini.com", "blockfi.com", "celsius.network",
    "paypal.com", "venmo.com", "wise.com", "transferwise.com",
    # Singapore large conglomerates (not SME targets)
    "sembcorp.com", "keppel.com", "comfortdelgro.com", "sats.com.sg",
    "singtel.com", "starhub.com", "m1.com.sg", "dbs.com.sg", "ocbc.com",
    "uob.com.sg", "capitaland.com", "mapletree.com.sg", "ascendas.com",
    "psalimited.com.sg", "hyflux.com", "sia.com.sg", "cwt.com.sg",
}

SKIP_LISTICLE_DOMAINS = {"bizvibe.com"}

SOCIAL_DOMAINS = {"jobstreet.com", "clutch.co", "reddit.com", "suss.edu.sg", "ibm.com",
                  "indeed.com", "linkedin.com", "facebook.com", "twitter.com", "youtube.com",
                  "instagram.com", "tiktok.com", "pinterest.com", "medium.com", "tracxn.com",
                  "bouncewatch.com", "mycareersfuture.gov.sg", "sgpbusiness.com", "emis.com",
                  "jobstreet.com.sg", "jobsdb.com", "glassdoor.com",
                  "wa.link", "wa.me", "x.com", "t.me"}

# ── Industry verification keywords ────────────────────────────────────────────
# Maps claimed industry → list of confirmation keywords expected on homepage.
INDUSTRY_KEYWORDS = {
    "construction": ["contractor", "builder", "renovation", "civil engineering", "construction", "building"],
    "engineering": ["engineering", "engineer", "mechanical", "electrical", "civil", "structural"],
    "logistics": ["freight", "shipping", "warehouse", "supply chain", "logistics", "transport", "cargo"],
    "manufacturing": ["manufacturing", "factory", "fabrication", "oem", "precision engineering", "production"],
    "fintech": ["payment", "lending", "digital bank", "blockchain", "crypto", "wealth management", "fintech"],
    "it": ["software", "it solutions", "technology", "digital", "cloud", "cybersecurity"],
    "software": ["software", "saas", "application", "platform", "developer"],
    "marketing": ["marketing", "branding", "advertising", "digital marketing", "seo", "media"],
    "accounting": ["accounting", "audit", "bookkeeping", "tax", "cpa"],
    "interior design": ["interior design", "renovation", "fit-out", "space planning"],
}

# ── SG signal patterns (for .com/.io domain verification) ─────────────────────
SG_PHONE_SIGNAL = re.compile(r'(?:\+65|65)\s*[\s\-]?[689]\d{3}[\s\-]?\d{4}')
SG_POSTAL_SIGNAL = re.compile(r'Singapore\s+\d{6}')
SG_UEN_SIGNAL = re.compile(r'\b(?:UEN|ACRA|BizFile)\b', re.IGNORECASE)


def print_progress(stage, detail):
    print(f"PROGRESS: Stage {stage} — {detail}", flush=True)


_YELU_CATEGORY_MAP = {
    # Construction / renovation
    "construction": "construction-services",
    "building": "construction-services",
    "renovation": "Renovation",
    "interior design": "Interior-Design",
    "interior fitting": "Interior-Design",
    "id firm": "Interior-Design",
    # Technology
    "it": "Information-Technology",
    "information technology": "Information-Technology",
    "software": "Software",
    "technology": "Information-Technology",
    "digital": "Information-Technology",
    "tech": "Information-Technology",
    "web design": "web-design",
    # Professional services
    "marketing": "Marketing",
    "advertising": "Marketing",
    "engineering": "Engineering",
    "printing": "Printing",
    "security": "Security",
    "training": "Training",
    "legal": "Legal-Services",
    "law": "lawyers",
    "law firm": "lawyers",
    # F&B
    "food": "restaurants",
    "food and beverage": "restaurants",
    "f&b": "restaurants",
    "restaurant": "restaurants",
    "catering": "Catering",
    # Logistics
    "logistics": "Logistics",
    "transport": "Logistics",
    "shipping": "Logistics",
    "freight": "Logistics",
    # Education
    "education": "Education",
    "tuition": "Education",
    "school": "schools-singapore",
    # Healthcare
    "healthcare": "hospitals",
    "medical": "doctors-and-clinics",
    "clinic": "doctors-and-clinics",
    "dental": "dentists",
    # Real estate / property
    "real estate": "estate-agents",
    "property": "estate-agents",
    # HR / staffing
    "hr": "employment-agencies",
    "recruitment": "employment-agencies",
    "staffing": "employment-agencies",
    # Beauty / wellness
    "beauty": "beauty-salons",
    "salon": "beauty-salons",
    # Hospitality / travel
    "hospitality": "hotels-singapore",
    "hotel": "hotels-singapore",
    "travel": "travel-agents",
    "tourism": "travel-agents",
}

_YELU_SKIP_DOMAINS = {
    "yelu.sg", "google.com", "googleapis.com", "facebook.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "instagram.com", "wa.me", "wa.link",
    "bootstrapcdn.com", "doubleclick.net", "googlesyndication.com", "maps.google.com",
    "googletagmanager.com", "fundingchoicesmessages.google.com",
}


def _yelu_sg_search(keyword, limit=20, start_page=1):
    """Scrape yelu.sg Singapore business directory — primary SG lead source.

    start_page: which page to begin from (1-indexed). Used for run-based pagination:
    run 0 → pages 1-3, run 1 → pages 4-6, etc. Yelu.sg has 11+ pages per category.
    """
    import html as htmllib

    # Map keyword to yelu.sg category slug
    kw_lower = keyword.lower().strip()
    category = None
    for key, slug in _YELU_CATEGORY_MAP.items():
        if key in kw_lower:
            category = slug
            break
    if not category:
        # Fallback: use first word, title-cased
        category = kw_lower.split()[0].title()

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    def fetch_html(url, timeout=12):
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-SG,en;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
                return resp.read(300_000).decode("utf-8", errors="ignore")
        except Exception:
            return ""

    # Parse company listing: <h3><a href="/company/ID/slug">Name</a></h3>
    company_pat = re.compile(r'<h3><a href="(/company/\d+/[^"]+)"[^>]*>(.*?)</a></h3>', re.S)
    phone_pat = re.compile(r'fa-phone[^>]*>\s*</i>\s*<span>([\+\d\s\-\(\)]+)</span>')
    addr_pat = re.compile(r'<div class="address">(.*?)</div>', re.S)

    # Fetch multiple pages until we have enough companies
    all_companies = []
    all_phones = []
    all_addrs = []
    max_pages = 3
    for page in range(start_page, start_page + max_pages):
        if page == 1:
            cat_url = f"https://www.yelu.sg/category/{category}"
        else:
            cat_url = f"https://www.yelu.sg/category/{category}/{page}"
        raw = fetch_html(cat_url)
        if not raw or "captcha" in raw.lower():
            break
        companies = company_pat.findall(raw)
        phones_raw = phone_pat.findall(raw)
        addrs_raw = [htmllib.unescape(re.sub(r"<[^>]+>", "", m)).strip() for m in addr_pat.findall(raw)]
        if not companies:
            break
        all_companies.extend(companies)
        all_phones.extend(phones_raw)
        all_addrs.extend(addrs_raw)
        if len(all_companies) >= limit:
            break

    if not all_companies:
        return {"results": [], "error": f"no companies parsed from yelu.sg category: {category}"}

    # Build initial lead stubs
    stubs = []
    for i, (profile_path, name_html) in enumerate(all_companies[:limit]):
        name = htmllib.unescape(re.sub(r"<[^>]+>", "", name_html)).strip()
        phone = all_phones[i].strip() if i < len(all_phones) else ""
        address = all_addrs[i] if i < len(all_addrs) else ""
        stubs.append({
            "name": name,
            "phone": phone,
            "address": address,
            "profile_url": f"https://www.yelu.sg{profile_path}",
        })

    # Fetch profile pages in parallel to get actual company websites
    def get_company_website(stub):
        html_raw = fetch_html(stub["profile_url"], timeout=10)
        if not html_raw:
            return stub
        for href in re.findall(r'href="(https?://[^"]{5,})"', html_raw):
            domain = re.sub(r"^https?://(?:www\.)?", "", href).split("/")[0].lower()
            if not any(s in domain for s in _YELU_SKIP_DOMAINS):
                stub["website"] = href.split("?")[0].split("#")[0]
                return stub
        return stub

    with ThreadPoolExecutor(max_workers=5) as ex:
        stubs = list(ex.map(get_company_website, stubs))

    results = []
    for stub in stubs:
        website = stub.get("website", "")
        results.append({
            "url": website or "",
            "title": stub["name"],
            "content": f"Phone: {stub['phone']}. Address: {stub['address']}",
            "engine": "yelu-sg",
            "phone": stub["phone"],
            "address": stub["address"],
        })
    return {"results": results}


def _yellowpages_sg_search(keyword, limit=15):
    """Yellow Pages SG — kept as alias, now delegates to yelu.sg."""
    return _yelu_sg_search(keyword, limit=limit)


def _duckduckgo_search(query, limit=15):
    """DuckDuckGo HTML search — primary fallback when SearXNG unavailable."""
    import html as htmllib
    encoded = urllib.parse.quote(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-SG,en;q=0.9",
    })
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=15.0, context=ssl_ctx) as resp:
            raw = resp.read(500_000).decode("utf-8", errors="ignore")
    except Exception as e:
        return {"error": str(e), "results": []}

    results = []
    link_pat = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
    snippet_pat = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.S)
    links = link_pat.findall(raw)
    snippets = [htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
                for m in snippet_pat.finditer(raw)]
    for i, (href, title_html) in enumerate(links[:limit]):
        title = htmllib.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
        # DDG wraps real URLs: //duckduckgo.com/l/?uddg=ENCODED_URL&...
        uddg_m = re.search(r"uddg=([^&]+)", href)
        if uddg_m:
            real_url = urllib.parse.unquote(uddg_m.group(1))
        elif href.startswith("http"):
            real_url = href
        else:
            continue
        snippet = snippets[i] if i < len(snippets) else ""
        results.append({"url": real_url, "title": title, "content": snippet, "engine": "duckduckgo"})
    return {"results": results}


def _startpage_search(query, limit=10):
    """Startpage.com HTML search — secondary fallback."""
    import html as htmllib
    encoded = urllib.parse.quote(query)
    url = f"https://www.startpage.com/sp/search?query={encoded}&language=en"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-SG,en;q=0.9",
    })
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=15.0, context=ssl_ctx) as resp:
            raw = resp.read(500_000).decode("utf-8", errors="ignore")
    except Exception as e:
        return {"error": str(e), "results": []}

    # Detect captcha page
    if "captcha" in raw.lower() or len(raw) < 5000:
        return {"results": [], "error": "startpage captcha"}

    results = []
    link_pat = re.compile(r'<a[^>]+class="[^"]*result-title[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
    snippet_pat = re.compile(r'<p[^>]+class="[^"]*description[^"]*"[^>]*>(.*?)</p>', re.S)
    links = link_pat.findall(raw)
    snippets = [htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
                for m in snippet_pat.finditer(raw)]
    for i, (href, title_html) in enumerate(links[:limit]):
        title = htmllib.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
        snippet = snippets[i] if i < len(snippets) else ""
        if href.startswith("http"):
            results.append({"url": href, "title": title, "content": snippet, "engine": "startpage"})
    return {"results": results}


def _mojeek_search(query, limit=10):
    """Mojeek.com HTML search — reliable fallback with no CAPTCHA."""
    import html as htmllib
    encoded = urllib.parse.quote(query)
    url = f"https://www.mojeek.com/search?q={encoded}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-SG,en;q=0.9",
    })
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=15.0, context=ssl_ctx) as resp:
            raw = resp.read(500_000).decode("utf-8", errors="ignore")
    except Exception as e:
        return {"error": str(e), "results": []}

    if "captcha" in raw.lower() or len(raw) < 5000:
        return {"results": [], "error": "mojeek captcha"}

    results = []
    for m in re.finditer(r'<h2><a class="title" title="([^"]+)" href="([^"]+)">(.*?)</a></h2>\s*<p class="s">(.*?)</p>', raw, re.S):
        href = m.group(2)
        title = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        snippet = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(4))).strip()
        if href.startswith("http"):
            results.append({"url": href, "title": title, "content": snippet, "engine": "mojeek"})
    for m in re.finditer(r'<li class="r\d+"[^>]*>.*?<a[^>]+href="(https?://[^"]+)"[^>]*>(?:<p class="i".*?</p>)?\s*<h2>(.*?)</h2>.*?<p class="s">(.*?)</p>.*?</li>', raw, re.S):
        href = m.group(1)
        title = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        snippet = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        if title and href.startswith("http"):
            results.append({"url": href, "title": title, "content": snippet, "engine": "mojeek"})
    return {"results": results[:limit]}






# ── Production engine configuration ──────────────────────────────────────────
# Verified working on this VPS (2026-04-24 stress-tests, 15 SG B2B queries each):
#   ecosia(21.8/q)   — Bing-backed but 2.3× Bing's yield (35 results/query peak)
#   yandex(12.5/q)   — 1hr CAPTCHA suspension after heavy batch
#   ask(11/q)        — Bing-backed, different ranking
#   google(9.8/q)    — 3min suspension; ~20 queries before 403
#   startpage(10/q)  — 1hr CAPTCHA suspension after heavy batch
#   bing(9.6/q)      — NEVER rate-limited (most resilient)
#   mojeek(10/q)     — 3min suspension
#   aol(9.3/q)       — Bing-backed, different ranking
#   yahoo(7/q)       — NEVER rate-limited
#   seznam(6.7/q)    — Czech engine, independent infra
#   yacy(6.6/q)      — P2P, independent infra
# Disabled/unreliable: duckduckgo (disabled in config), brave (flaky),
#   qwant/yep/presearch/mwmbl/karmasearch (0 results),
#   baidu/sogou/quark/naver (inconsistent for SG queries).
#
# Priority order: high-yield first (google/startpage/bing/ecosia/yandex), then
# 3-min-recovery (mojeek/yahoo), then Bing-backed diversity (aol/ask), then
# independent-infrastructure fallback (seznam/yacy).
SEARXNG_ENGINES = [
    "google", "startpage", "bing", "duckduckgo",  # tier 1: highest yield
    "yandex", "mojeek", "yahoo", "brave",          # tier 2: solid backup
    "aol", "karmasearch",                           # tier 3: proven producers
]
SEARXNG_HEALTHY_ENGINES = set()  # populated at runtime by check_searxng_health()


def check_searxng_health():
    """Pre-flight check: test each SearXNG engine with a ping query.
    Returns a set of working engine names. Updates the global cache."""
    global SEARXNG_HEALTHY_ENGINES
    healthy = set()
    ping_query = "construction Singapore"
    for engine in SEARXNG_ENGINES:
        try:
            encoded = urllib.parse.quote(ping_query)
            url = f"http://localhost:8080/search?q={encoded}&format=json&engines={engine}&language=en&safesearch=0&limit=3"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if len(data.get("results", [])) >= 1:
                    healthy.add(engine)
        except Exception:
            pass
    SEARXNG_HEALTHY_ENGINES = healthy
    return healthy


def searxng_search(query, limit=10, preferred_engines=None):
    """Production search with SearXNG (Google → Yahoo → Mojeek → Yandex)
    → direct Mojeek → Yellow Pages SG fallback chain.

    Returns a dict with:
        - results: list of search result dicts
        - _engine: which engine produced the results (for logging)
        - _source: "searxng" or "direct"
    """
    if preferred_engines is None:
        preferred_engines = [e for e in SEARXNG_ENGINES if e in SEARXNG_HEALTHY_ENGINES]
        if not preferred_engines:
            preferred_engines = SEARXNG_ENGINES

    encoded = urllib.parse.quote(query)

    # 1. Try SearXNG engines in priority order
    for engine in preferred_engines:
        url = f"http://localhost:8080/search?q={encoded}&format=json&engines={engine}&language=en&safesearch=0&limit=20"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "sg-leadgen/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("results", [])
                if len(results) >= 3:
                    data["_engine"] = engine
                    data["_source"] = "searxng"
                    return data
                elif len(results) >= 1:
                    # Accept marginal results for Yahoo/Mojeek/Yandex
                    data["_engine"] = engine
                    data["_source"] = "searxng"
                    return data
        except Exception:
            continue

    # 2. Try direct Mojeek scrape if ALL SearXNG engines failed
    mj = _mojeek_search(query, limit=limit)
    if mj.get("results"):
        mj["_engine"] = "mojeek_direct"
        mj["_source"] = "direct"
        return mj

    # 3. Yellow Pages SG (best for SG business leads)
    yp = _yelu_sg_search(query.replace("site:.sg ", "").replace("intitle:", "").replace("inurl:", ""), limit=limit)
    if yp.get("results"):
        yp["_engine"] = "yelu-sg"
        yp["_source"] = "direct"
        return yp

    return {"results": [], "_engine": "none", "_source": "none", "error": "all search backends failed"}

# ── SSL context for broken SG certs ──────────────────────────────────────────
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch(url, timeout=8):
    if not url.startswith("http"):
        return None
    req = urllib.request.Request(url, headers=HEADERS)
    for _url in (url, url.replace("https://", "http://", 1)):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                return resp.read(MAX_HTML_BYTES).decode("utf-8", errors="ignore")
        except Exception:
            if _url == url:
                req = urllib.request.Request(_url.replace("https://", "http://", 1), headers=HEADERS)
            continue
    return None


# ── Cloudflare email decode ──────────────────────────────────────────────────
def decode_cf_email(encoded):
    if len(encoded) < 4:
        return ""
    try:
        key = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
    except Exception:
        return ""


# ── JSON-LD recursive scan ───────────────────────────────────────────────────
def _jsonld_scan(obj, out):
    if isinstance(obj, dict):
        if obj.get("@type") == "Person" or obj.get("@type") == "ContactPoint":
            name = obj.get("name", "")
            job = obj.get("jobTitle", "")
            email = obj.get("email", "")
            if name and job:
                out["people"].append((name, job))
            if email:
                out["emails"].append(email)
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


# ── Email extraction with validation ─────────────────────────────────────────
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
    # Reject hex-hash local parts
    if re.fullmatch(r"[0-9a-f]{12,}", user, re.I):
        return False
    # Reject timestamp patterns
    if re.search(r"20\d{2}[-_]?\d{2}[-_]?\d{2}", user):
        return False
    # Reject image-filename patterns
    if "-@-" in email or "_at_" in email.lower():
        return False
    # Reject blocked domains
    if domain.lower() in BLOCKED_DOMAINS:
        return False
    return True


def extract_emails(html):
    found = list(set(e for e in EMAIL_RE.findall(html) if is_valid_email(e)))
    # Cloudflare encoded emails
    for encoded in CF_EMAIL_RE.findall(html):
        dec = decode_cf_email(encoded)
        if dec and is_valid_email(dec) and dec not in found:
            found.append(dec)
    # JSON-LD
    jld = extract_jsonld(html)
    for e in jld["emails"]:
        if is_valid_email(e) and e not in found:
            found.append(e)
    return found


# ── Phone extraction ─────────────────────────────────────────────────────────
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


def pick_best_email(emails):
    if not emails:
        return ""
    direct = [e for e in emails if not any(e.lower().startswith(g) for g in GENERIC_PREFIXES)]
    chosen = direct if direct else emails
    sg_emails = [e for e in chosen if e.lower().endswith((".com.sg", ".sg"))]
    return sg_emails[0] if sg_emails else chosen[0]


def pick_best_phone(phones):
    cleaned = [clean_phone(p) for p in phones if clean_phone(p)]
    if not cleaned:
        return ""
    sg = [p for p in cleaned if p.startswith("+65")]
    return sg[0] if sg else cleaned[0]


# ── Contact page discovery ───────────────────────────────────────────────────
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


# ── Pattern email fallback ───────────────────────────────────────────────────
def pattern_email_fallback(domain):
    if not domain:
        return ""
    domain = re.sub(r"^www\.", "", domain.lower())
    return f"enquiry@{domain}"


def detect_industry_from_html(html, claimed_industry):
    """Scan homepage HTML for industry keyword confirmation.
    Returns (confidence, detected_industry) where confidence is high/medium/low.
    """
    if not html or not claimed_industry:
        return "low", claimed_industry
    text = re.sub(r"<[^>]+>", " ", html).lower()
    claimed = claimed_industry.lower().strip()

    # Count claimed keyword occurrences
    count = text.count(claimed)
    if count >= 3:
        return "high", claimed_industry
    if count >= 1:
        return "medium", claimed_industry

    # Check alternative industry mappings
    for industry, keywords in INDUSTRY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return "medium", industry

    return "low", claimed_industry


def has_sg_signals(html):
    """Return True if homepage HTML contains strong Singapore signals:
    +65 phone, Singapore postal code, UEN/ACRA mention.
    """
    if not html:
        return False
    if SG_PHONE_SIGNAL.search(html):
        return True
    if SG_POSTAL_SIGNAL.search(html):
        return True
    if SG_UEN_SIGNAL.search(html):
        return True
    return False


# ── Decision maker extraction ────────────────────────────────────────────────
def extract_decision_makers(html):
    found = []
    seen = set()
    text = re.sub(r"<[^>]+>", " ", html)
    # Pattern: "Name — Title" or "Name, Title" near title words
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        has_title = bool(_TITLE_WORDS_RE.search(line))
        if not has_title:
            continue
        for sep in (" — ", " – ", " - ", " | ", ", ", "  ", "\t"):
            if sep in line:
                parts = line.split(sep, 1)
                name_part = parts[0].strip()
                title_part = parts[1].strip()
                if 3 <= len(name_part) <= 40:
                    words = name_part.split()
                    # Require at least 2 words — single word "names" are almost always not people
                    if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
                        # Reject if name contains reject words
                        if any(w.lower() in DM_REJECT_WORDS for w in words):
                            continue
                        # Strip trailing title words from name
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
    # HTML pattern: h3/h4 + nearby p/div with title
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
                if any(w.lower() in DM_REJECT_WORDS for w in words):
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
    # JSON-LD people
    jld = extract_jsonld(html)
    for name, title in jld["people"]:
        words = name.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
            if any(w.lower() in DM_REJECT_WORDS for w in words):
                continue
            key = (name.lower(), title.lower())
            if key not in seen:
                seen.add(key)
                found.append((name, title))
    return found


def pick_best_dm(dms):
    if not dms:
        return None
    priority = {
        "ceo": 1, "founder": 2, "co-founder": 2, "cofounder": 2,
        "managing director": 3, "director": 4, "country manager": 5,
        "head of": 6, "partner": 7, "vp": 8, "vice president": 8,
        "coo": 9, "cto": 9, "cfo": 9, "cmo": 9,
    }
    scored = []
    for name, title in dms:
        tlower = title.lower()
        score = 99
        for k, v in priority.items():
            if k in tlower:
                score = v
                break
        scored.append((score, name, title))
    scored.sort()
    return scored[0]


# ── Existing functions ───────────────────────────────────────────────────────
def is_likely_sg_company(name, url):
    """Heuristic to keep Singapore-based companies. Applied to both direct results and listicles."""
    domain = normalize_domain(url)
    nlower = name.lower()
    # Always allow .sg domains
    if domain.endswith(".sg") or domain.endswith(".com.sg"):
        return True
    # Allow if name explicitly mentions Singapore or Pte Ltd
    if "singapore" in nlower or "pte ltd" in nlower or "pte. ltd." in nlower:
        return True
    # Block known global brands and platforms that aren't SG-based
    if domain in GLOBAL_BRAND_DOMAINS or any(domain.endswith("." + d) for d in GLOBAL_BRAND_DOMAINS):
        return False
    # Block app store pages
    if "apps.apple.com" in domain or "play.google.com" in domain:
        return False
    # Block obvious article/tutorial sites
    article_domains = {"mordorintelligence.com", "fortunebusinessinsights.com", "brookings.edu",
                       "thomsonreuters.com", "cnbc.com", "time.com", "weforum.org",
                       "keiseruniversity.edu", "mit.edu", "consumerfinance.gov",
                       "globallegalinsights.com", "jotform.com"}
    if domain in article_domains or any(domain.endswith("." + d) for d in article_domains):
        return False
    # Block explicit non-SG country-code TLDs — these are foreign companies
    non_sg_cctlds = (
        ".in", ".my", ".ph", ".id", ".vn", ".th", ".au", ".nz",
        ".uk", ".co.uk", ".cn", ".hk", ".tw", ".jp", ".kr",
        ".ca", ".de", ".fr", ".nl", ".se", ".no", ".dk",
    )
    if any(domain.endswith(t) for t in non_sg_cctlds):
        return False
    # Many legitimate SG companies use .com, .net, .io, .co, .biz etc.
    # Allow these — LOW_QUALITY_DOMAIN_PATTERNS + GLOBAL_BRAND_DOMAINS handle junk.
    return True


def is_low_quality_result(title, url):
    t = title.lower()
    d = normalize_domain(url)
    for pat in LOW_QUALITY_TITLE_PATTERNS:
        if re.search(pat, t):
            return True
    for pat in LOW_QUALITY_DOMAIN_PATTERNS:
        if re.search(pat, d):
            return True
    return False


def sanitize_url(url):
    if not url:
        return url
    url = url.strip()
    # Fix double-protocol URLs like https://https://example.com (including zero-width chars)
    url = re.sub(r"^(https?://)[\s\u200b\u200c\u200d\ufeff]*https?://", r"\1", url)
    return url


def normalize_domain(url):
    if not url:
        return ""
    url = str(url).lower().strip()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    url = re.sub(r"/.*$", "", url)
    return url


def is_valid_company_url(url):
    u = url.lower()
    if u.endswith(".pdf"):
        return False
    if any(x in u for x in ["/blog/", "/news", "/insights/", "/events/", "/careers/", "/jobs/", "/login", "/prulinkfund/", "/viewConversionRate", "/yourpolicydoc", "/feedback/"]):
        return False
    # Reject article/blog URLs with very long slug paths (>55 chars after last /)
    path = u.split("?")[0]
    last_segment = path.rstrip("/").split("/")[-1]
    if len(last_segment) > 55 and "-" in last_segment:
        return False
    # Reject government and academic domains
    if any(u.endswith(d) for d in ['.gov.sg', '.edu.sg', '.ac.sg', '.nus.edu', '.ntu.edu', '.smu.edu', '.suss.edu']):
        return False
    # Reject job boards and industry directories — profile URLs are not company websites
    bad_domains = [
        "foundit.sg", "foundit.in", "jobstreet.com", "jobscentral.com.sg",
        "indeed.com", "linkedin.com", "glassdoor.com", "seek.com.au",
        "monster.com", "careerjet.sg", "asiabuilders.com.sg",
        "sgprocessindustries.com", "yellowpages.com.sg", "kompass.com",
        "dnb.com", "scal.com.sg",
    ]
    if any(bd in u for bd in bad_domains):
        return False
    return True


def extract_companies_from_listicle(html, source_url, industry_terms=()):
    leads = []
    seen = set()
    source_domain = normalize_domain(source_url)
    tagline_starts = ("almost ", "more than ", "over ", "registered with ", "modern and unique",
                      "tailored services", "competitive rates", "years of experience", "year of experience",
                      "make your ", "get in touch", "welcome", "contact us", "our services",
                      "turn your ", "let us ", "we are ", "we help ", "trusted ", "award-winning",
                      "discover ", "explore ", "find out ", "learn more", "read more")
    link_pattern = re.compile(r'<a[^>]+href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
    for match in link_pattern.finditer(html):
        href = sanitize_url(match.group(1).strip())
        text = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        # Collapse whitespace — catches "Tweet\n\t\t\t0" style garbage
        text = re.sub(r'\s+', ' ', text).strip()
        domain = normalize_domain(href)
        if not domain or domain == source_domain:
            continue
        if any(sd in domain for sd in SOCIAL_DOMAINS):
            continue
        # Reject when link text is a URL (bare href as anchor text)
        if text.startswith("http://") or text.startswith("https://"):
            continue
        if any(text.lower().startswith(t) for t in tagline_starts):
            continue
        if "experience" in text.lower() and len(text.split()) <= 6:
            continue
        if is_low_quality_result(text, href):
            continue
        if not is_valid_company_url(href):
            continue
        if len(text) < 3 or len(text) > 80:
            continue
        # Reject generic nav/platform text
        # Strip bracket-style URL-in-name: "welcome [www.ezid.sg]" → "welcome"
        text = re.sub(r'\s*\[[a-z0-9][\w.-]*\.[a-z]{2,}\]', '', text, flags=re.IGNORECASE).strip()
        if not text:
            continue
        if text.lower() in {"here", "click here", "read more", "learn more", "website", "contact",
                             "b2b tools", "discover companies", "find suppliers", "compare companies",
                             "sales prospecting", "send proposals", "company insights",
                             "for buyers", "for sellers", "matchmaking services", "try for free",
                             "sign up", "register", "get started", "business services",
                             "get in touch", "interior fit out", "interior designer", "interior design",
                             "welcome", "our company", "design & build", "office interior",
                             "renovation works", "fit out works", "construction works"}:
            continue
        # Reject tagline-style anchor text (not company names)
        if any(text.lower().startswith(t) for t in tagline_starts):
            continue
        if "experience" in text.lower() and len(text.split()) <= 6:
            continue
        # Reject phone numbers used as link text (WhatsApp/wa.link/wa.me etc.)
        if re.match(r'^[\+\(]?\d', text) and re.sub(r'[\d\s\+\-\(\)]', '', text) == '':
            continue
        if text.count(" ") > 8:
            continue
        if len(text.split()) <= 1 and len(text) < 20:
            continue
        # Strip domain-in-parentheses e.g. "Holden (holden.com.sg)"
        text = re.sub(r'\s*\([a-z0-9][\w.-]*\.[a-z]{2,}\)', '', text, flags=re.IGNORECASE).strip()
        # Reject names with semicolons — always a description/tagline
        if ";" in text:
            continue
        # Apply same article-title heuristics as direct results
        t = text
        if t.startswith("[") or t.startswith("How ") or t.startswith("What ") or t.startswith("Why ") or t.startswith("The ") and len(t) > 40:
            continue
        if "overview" in t.lower() or "guide" in t.lower() or "report" in t.lower():
            continue
        if "in Singapore" in t and len(t) > 40:
            continue
        if "Company in Singapore" in t or "Start-up" in t or "Startup" in t:
            continue
        if "Registry of" in t or "Committee" in t or "Legal Rankings" in t:
            continue
        if "Sandbox" in t and "Incentives" in t:
            continue
        if "Definition" in t or "Statistics" in t or "Meaning" in t:
            continue
        if "Strategies" in t or "Proven" in t or "Tips" in t or "Ways to" in t:
            continue
        if re.match(r'^\d+\s', t):
            continue
        if re.match(r'^Almost\s+\d+', t) or t.startswith("Most ") or t.startswith("All "):
            continue
        if "Feedback" in t or "e-learning" in t.lower():
            continue
        # Reject known non-company landmarks/projects
        landmark_names = {"marina bay sands", "resorts world sentosa", "tampines mrt station",
                          "changi business park", "sentosa boardwalk", "raffles marina harbour",
                          "singapore cruise centre", "prudential tower", "jurong island"}
        if text.lower() in landmark_names:
            continue
        if len(text.split()) >= 2 and not has_brand_token(text, industry_terms):
            continue
        if not is_likely_sg_company(text, href):
            continue
        key = (text.lower(), domain)
        if key in seen:
            continue
        seen.add(key)
        leads.append({"company_name": text, "website": href})
    list_item_pattern = re.compile(
        r'(?:<li[^>]*>|\n\s*\d+[.\)]\s+)(?:<strong>|<b>)?([^<\n]{3,50})(?:</strong>|</b>)?'
        r'.*?<a[^>]+href=["\'](https?://[^"\']+)["\']',
        re.IGNORECASE | re.DOTALL
    )
    for match in list_item_pattern.finditer(html):
        text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        text = re.sub(r'\s+', ' ', text).strip()
        href = sanitize_url(match.group(2).strip())
        domain = normalize_domain(href)
        if not domain or domain == source_domain:
            continue
        if any(sd in domain for sd in SOCIAL_DOMAINS):
            continue
        if text.startswith("http://") or text.startswith("https://"):
            continue
        if any(text.lower().startswith(t) for t in tagline_starts):
            continue
        if "experience" in text.lower() and len(text.split()) <= 6:
            continue
        if is_low_quality_result(text, href):
            continue
        if not is_valid_company_url(href):
            continue
        if len(text) < 3 or len(text) > 80:
            continue
        if len(text.split()) <= 1 and len(text) < 20:
            continue
        # Strip domain-in-parentheses and reject description phrases
        text = re.sub(r'\s*\([a-z0-9][\w.-]*\.[a-z]{2,}\)', '', text, flags=re.IGNORECASE).strip()
        if ";" in text or not text:
            continue
        # Reject known non-company landmarks/projects
        landmark_names = {"marina bay sands", "resorts world sentosa", "tampines mrt station",
                          "changi business park", "sentosa boardwalk", "raffles marina harbour",
                          "singapore cruise centre", "prudential tower", "jurong island"}
        if text.lower() in landmark_names:
            continue
        if len(text.split()) >= 2 and not has_brand_token(text, industry_terms):
            continue
        if not is_likely_sg_company(text, href):
            continue
        key = (text.lower(), domain)
        if key in seen:
            continue
        seen.add(key)
        leads.append({"company_name": text, "website": href})
    return leads


# ── Main enrichment function ─────────────────────────────────────────────────
def enrich_website(lead):
    url = lead.get("website", "").strip()
    if not url or not url.startswith("http"):
        return lead

    html = fetch(url, timeout=6)
    if not html:
        return lead

    emails = extract_emails(html)
    phones = extract_phones(html)
    dms = extract_decision_makers(html)

    # Discover and fetch contact pages from homepage links
    contact_urls = discover_contact_pages(html, url)
    # Also add hardcoded fallbacks
    parsed = urllib.parse.urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    for path in ("/contact", "/contact-us", "/about", "/about-us", "/team", "/people", "/leadership", "/management"):
        contact_urls.append(base + path)
    # Deduplicate while preserving order
    seen_urls = set()
    unique_contact_urls = []
    for u in contact_urls:
        if u not in seen_urls:
            seen_urls.add(u)
            unique_contact_urls.append(u)

    for page_url in unique_contact_urls[:6]:
        page_html = fetch(page_url, timeout=4)
        if page_html:
            emails = list(dict.fromkeys(emails + extract_emails(page_html)))
            phones = list(dict.fromkeys(phones + extract_phones(page_html)))
            dms = list(dict.fromkeys(dms + extract_decision_makers(page_html)))

    # Pick best email
    if emails and not lead.get("email"):
        lead["email"] = pick_best_email(emails)
    # Pick best phone
    if phones and not lead.get("phone"):
        lead["phone"] = pick_best_phone(phones)
    # Pick best DM
    if dms and not lead.get("decision_maker_name"):
        best = pick_best_dm(dms)
        if best:
            lead["decision_maker_name"] = best[1][:60]
            lead["decision_maker_title"] = best[2][:80]

    # Industry verification from homepage content
    industry_confidence, detected_industry = detect_industry_from_html(html, lead.get("industry", ""))
    lead["industry_confidence"] = industry_confidence
    lead["detected_industry"] = detected_industry

    # Singapore signals detection for .com/.io domain verification
    sg_signals = has_sg_signals(html)
    lead["sg_signals"] = "yes" if sg_signals else "no"

    # Pattern email fallback if still empty — skip for directory/profile domains
    # AND skip if no SG signals on non-.sg domains (reduces foreign bounce risk)
    if not lead.get("email"):
        domain = normalize_domain(url)
        directory_domains = {"yelu.sg", "yellowpages.com.sg", "yellowpages.sg", "kompass.com", "dnb.com"}
        is_dir = any(domain == d or domain.endswith('.' + d) for d in directory_domains)
        is_sg_domain = domain.endswith(".sg") or domain.endswith(".com.sg")
        if domain and not is_dir and (is_sg_domain or sg_signals):
            for prefix in ("enquiry", "info", "sales", "hello", "contact", "admin"):
                guess = f"{prefix}@{domain}"
                lead["email"] = guess
                break

    return lead


def results_to_leads(search_data, industry, industry_terms=()):
    seen = set()
    leads = []
    listicles_to_expand = []
    for entry in search_data:
        for r in entry.get("results", []):
            title = r.get("title", "").strip()
            url = sanitize_url(r.get("url", "").strip())
            engine = r.get("engine", "")
            # Allow directory-sourced leads with no website (they carry phone/address already)
            if not title:
                continue
            if not url and engine not in ("yelu-sg",):
                continue
            domain = normalize_domain(url) if url else ""
            if domain and any(sd in domain for sd in SOCIAL_DOMAINS):
                continue
            # Reject government and academic domains
            if domain and any(domain.endswith(d) for d in ['.gov.sg', '.edu.sg', '.ac.sg', '.nus.edu', '.ntu.edu', '.smu.edu', '.suss.edu']):
                continue
            if url and is_low_quality_result(title, url):
                listicles_to_expand.append({"title": title, "url": url})
                continue
            key = (title.lower(), domain)
            if key in seen:
                continue
            seen.add(key)
            # Strip CSS/JS noise that Startpage sometimes embeds in titles
            clean_title = re.sub(r'@media[^{]*\{[^}]*\}', '', title)
            clean_title = re.sub(r'\.[a-z][\w-]*\{[^}]*\}', '', clean_title)
            clean_title = re.sub(r'^\s*[}\s]+', '', clean_title).strip()  # strip leading } from CSS leaks
            name = clean_title.split(" – ")[0].split(" — ")[0].split(" - ")[0].split(" | ")[0].split(":")[0].strip()
            # Collapse whitespace (catches tab/newline garbage from HTML)
            name = re.sub(r'\s+', ' ', name).strip()
            # Reject bare URLs used as name
            if name.startswith("http://") or name.startswith("https://"):
                continue
            # Strip domain-in-parentheses e.g. "Holden (holden.com.sg)" → "Holden"
            name = re.sub(r'\s*\([a-z0-9][\w.-]*\.[a-z]{2,}\)', '', name, flags=re.IGNORECASE).strip()
            # Strip domain-in-brackets e.g. "welcome [www.ezid.sg]" → "welcome"
            name = re.sub(r'\s*\[[a-z0-9][\w.-]*\.[a-z]{2,}\]', '', name, flags=re.IGNORECASE).strip()
            # Reject names with semicolons — always a description/tagline, never a company name
            if ";" in name:
                continue
            # Reject all-caps promotional titles (e.g. "VENUE SALES KIT")
            words = name.split()
            if len(words) >= 3 and sum(1 for w in words if w.isupper()) >= len(words) - 1:
                continue
            if not name or len(name) < 3:
                continue
            # Reject article titles that aren't company names
            if name.startswith(("[", "@", ".", "#")):
                continue
            article_starts = ("How ", "What ", "Why ", "When ", "Where ", "Best ", "Top ",
                              "The Best", "List of", "Almost ", "Most ", "All ", "Your ")
            if any(name.startswith(p) for p in article_starts):
                continue
            if name.startswith("The ") and len(name) > 40:
                continue
            article_keywords = (
                "overview", "guide", "report", "strategies", "proven", "tips", "ways to",
                "definition", "statistics", "meaning", "services in singapore",
                "companies in singapore", "hub in singapore", "launches singapore",
                "archives", "franchise opportunities", "evolution", "business services",
                "establishment of", "survey", "whitepaper", "case study", "webinar",
                "law firm", "feels the", "seen facing", "ripple effects",
                "construction sector", "small construction firms",
                # Yandex-specific low-quality patterns
                "driving directions", "under construction", "temporary noise",
                "experienced tilers", "construction labor", "construction page",
                "you want good", "check the location", "floor & wall",
                "every e-commerce", "set up your", "quality facade",
            )
            if any(kw in name.lower() for kw in article_keywords):
                continue
            if re.match(r'^\d+\s', name):
                continue
            # Reject names STARTING with a 4-digit year (article/report titles)
            # Keep names like "ABC Construction — Established 2015" (year is not the title)
            if re.match(r'^20\d{2}\b', name):
                continue
            # Navigation page titles and social actions (never a company name)
            nav_titles = ("About Us", "Contact Us", "Our Services", "Our Warehousing",
                          "Our Logistics", "Home", "Privacy Policy", "Terms of",
                          "Cookie Policy", "Sitemap", "FAQ", "Blog",
                          "Board of Directors", "Board Of Directors", "Management Team",
                          "Tweet", "Share", "Follow", "Like", "Subscribe",
                          "Login", "Sign In", "Sign Up", "Register",
                          "Sign in", "Cookies Policy", "Partnerships & sponsoring",
                          "Get In Touch", "Welcome",
                          "Make Your Dream", "Our Portfolio", "View Projects",
                          "Contact Page", "Contact", "Page Not Found", "404", "Error")
            _name_lc = name.lower()
            if _name_lc in {n.lower() for n in nav_titles} or any(_name_lc.startswith(n.lower()) for n in nav_titles):
                continue
            # Generic descriptive phrases (not real company names)
            generic_phrases = (
                "in Singapore", "Company in Singapore", "Start-up", "Startup",
                "Registry of", "Committee", "Legal Rankings", "Sandbox",
                "Registered with the", "More than", "years of experience",
                "Modern and unique designs", "Tailored services", "Competitive rates",
            )
            if any(p in name for p in generic_phrases) and len(name) > 35:
                continue
            # SEO keyword phrase detection — only drop if ENTIRE name is generic + location
            # e.g. "IT Support Services Singapore" (all generic words + location)
            # Real companies like "ABC Construction Singapore" are kept (ABC is a brand)
            seo_only_words = {"it", "support", "services", "service", "solutions", "solution",
                              "company", "companies", "firm", "firms", "consulting", "consultancy",
                              "agency", "agencies", "professional", "specialist", "expert",
                              "provider", "providers", "contractor", "contractors",
                              "management", "marketing", "digital", "technology", "technologies",
                              "construction", "renovation", "interior", "design", "build",
                              "engineering", "logistics", "accounting", "legal", "financial",
                              "insurance", "broker", "brokerage", "hr", "recruitment", "staffing",
                              "real", "estate", "property", "facilities", "supplier", "distributor",
                              "manufacturer", "manufacturing", "trading", "import", "export",
                              "wholesale", "retail", "food", "beverage", "restaurant", "catering",
                              "hotel", "clinic", "hospital", "school", "education",
                              "singapore", "sg"}
            stripped_name = re.sub(r'[^a-zA-Z0-9\s]', '', name.lower())
            name_words = [w for w in stripped_name.split() if len(w) >= 2]
            # Only reject if EVERY word is in the SEO-only set AND name is 3+ words
            if len(name_words) >= 3 and all(w in seo_only_words for w in name_words):
                continue
            # Brand-token rule: 3+ word names must contain at least one non-generic,
            # non-industry word. Handles all industries via industry_terms from expand_industry().
            # 2-word names are kept — they can be valid brand names ("Cloud Telecom", "Synergy ID").
            if len(name.split()) >= 2 and not has_brand_token(name, industry_terms):
                continue
            if len(name.split()) <= 1 and len(name) < 20:
                continue
            # Reject blog post, news article, tag-page, and product/solution URLs
            # These are never company homepages
            if url and re.search(r'/(archives|tags?|categories|blog|news|articles?|maps|directions|products?|services?)/', url, re.I):
                continue
            # Reject URLs that are clearly subpages of large corporate sites
            # e.g. sembcorp.com/sg/our-solutions-in-... (not a separate company)
            path_segments = [s for s in url.split('?')[0].split('/') if s and not s.startswith('http')]
            if len(path_segments) > 3 and not url.rstrip('/').endswith('.sg') and not url.rstrip('/').endswith('.com.sg'):
                # Deep path on non-SG domain = likely a subpage, not a company homepage
                # But allow if the title contains a clear company identifier
                if not re.search(r'(Pte Ltd|Pte\. Ltd\.|Ltd\.|Limited|LLP|Corp|Inc)', name):
                    continue
            if not is_likely_sg_company(name, url):
                continue
            leads.append({
                "company_name": name,
                "phone": r.get("phone", ""),
                "email": r.get("email", ""),
                "website": url,
                "address": r.get("address", ""),
                "area": "Singapore",
                "industry": industry,
                "industry_confidence": "",
                "detected_industry": "",
                "sg_signals": "",
                "decision_maker_name": "",
                "decision_maker_title": "",
                "lead_score": "",
                "lead_tier": "",
                "source": r.get("engine", "searxng"),
            })
    # Only expand listicles from domains known to contain real company lists
    TRUSTED_LISTICLE_DOMAINS = [
        # Singapore-specific list sites — high company link density
        "bestinsingapore.co", "bestinsingapore.com", "thebestsingapore.com",
        "morebetter.sg", "topsingapore.online", "singaporeyou.com",
        "sgmagazine.com", "streetdirectory.com", "reviewranger.co",
        # International construction/industry list sites with SG coverage
        "civilgyan.com", "constructionplacements.com", "blackridgeresearch.com",
    ]
    listicles_to_expand = [item for item in listicles_to_expand
                           if any(d in item["url"].lower() for d in TRUSTED_LISTICLE_DOMAINS)]
    if listicles_to_expand:
        print_progress("2/5", f"Expanding {len(listicles_to_expand)} listicles for actual companies")
        for item in listicles_to_expand:
            html = fetch(item["url"], timeout=8)
            if html:
                extracted = extract_companies_from_listicle(html, item["url"], industry_terms=industry_terms)
                for ex in extracted:
                    domain = normalize_domain(ex["website"])
                    key = (ex["company_name"].lower(), domain)
                    if key in seen:
                        continue
                    seen.add(key)
                    leads.append({
                        "company_name": ex["company_name"],
                        "phone": "",
                        "email": "",
                        "website": ex["website"],
                        "address": "",
                        "area": "Singapore",
                        "industry": industry,
                        "industry_confidence": "",
                        "detected_industry": "",
                        "sg_signals": "",
                        "decision_maker_name": "",
                        "decision_maker_title": "",
                        "lead_score": "",
                        "lead_tier": "",
                        "source": "listicle_extract",
                    })
    return leads


def leads_to_csv(leads, path):
    if not leads:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            f.write("company_name,phone,email,website,address,area,industry,industry_confidence,detected_industry,sg_signals,decision_maker_name,decision_maker_title,lead_score,lead_tier,source\n")
        return
    fieldnames = ["company_name", "phone", "email", "website", "address", "area", "industry",
                  "industry_confidence", "detected_industry", "sg_signals",
                  "decision_maker_name", "decision_maker_title", "lead_score", "lead_tier", "source"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(leads)


def run_dedup(input_csv, output_csv, min_score=0):
    cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, "dedup_score.py"),
        input_csv,
        "--output", output_csv,
        "--min-score", str(min_score),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stdout, result.stderr


def main():
    parser = argparse.ArgumentParser(description="One-shot sg-leadgen pipeline")
    parser.add_argument("industry", help="Industry/category keyword")
    parser.add_argument("--target", type=int, default=50, help="Target lead count")
    parser.add_argument("--output", required=True, help="Final output CSV path")
    parser.add_argument("--workers", type=int, default=5, help="Website enrichment workers")
    parser.add_argument("--max-leads", type=int, default=None, help="Max leads to process (defaults to --target)")
    parser.add_argument("--min-score", type=int, default=0, help="Minimum dedup score")
    parser.add_argument("--history-file", default=None,
                        help="Path to .seen_companies.jsonl registry. Pass to skip previously seen companies.")
    parser.add_argument("--allow-repeats", action="store_true",
                        help="Ignore seen-companies registry — allow re-surfacing known companies.")
    parser.add_argument("--qc", action="store_true",
                        help="Final QC pass: send names to DeepSeek v4, drop page-title/tagline/non-SG junk.")
    parser.add_argument("--qc-model", default="deepseek-web/deepseek-v4",
                        help="Model to use for QC (default deepseek-web/deepseek-v4)")
    parser.add_argument("--min-confidence", choices=["low", "medium", "high"], default=None,
                        help="Filter out leads below this industry confidence level (low/medium/high)")
    args = parser.parse_args()
    if args.max_leads is None:
        args.max_leads = args.target

    os.makedirs(LEADS_DIR, exist_ok=True)
    industry_slug = re.sub(r"[^a-z0-9]+", "_", args.industry.lower()).strip("_")
    # Unique per-run timestamp (HHMMSS + PID) to avoid collisions between
    # concurrent campaigns from different users running same industry same day.
    timestamp = time.strftime("%d%m%Y_%H%M%S") + f"_{os.getpid()}"
    # Write intermediates into the OUTPUT's directory when possible, so each
    # wrapper's isolated run dir keeps all temp files isolated.
    _out_dir = os.path.dirname(os.path.abspath(args.output)) or LEADS_DIR
    if os.path.isdir(_out_dir) and os.access(_out_dir, os.W_OK):
        temp_prefix = os.path.join(_out_dir, f"_pipeline_{industry_slug}_{timestamp}")
    else:
        temp_prefix = os.path.join(LEADS_DIR, f"_pipeline_{industry_slug}_{timestamp}")

    # Stage 1: Search
    # Resolve synonyms — maps "F&B SME" → ["food and beverage", "restaurant", "cafe", ...]
    synonyms = expand_industry(args.industry) if _SYNONYMS_OK else [args.industry]
    if synonyms and synonyms != [args.industry]:
        print_progress("1/5", f"Industry '{args.industry}' expanded to {len(synonyms)} search terms: {', '.join(synonyms[:4])}")
        primary = synonyms[0]
    else:
        primary = args.industry
        synonyms = [args.industry]

    # Determine run count for this industry — used to rotate Yelu pages and area queries.
    # run_count=0 on first-ever run; increments each committed run.
    run_count = get_run_count(args.industry) if _SEEN_OK else 0

    print_progress("1/5", f"Searching for '{primary}' (run #{run_count + 1}, SearXNG→Yelu.sg)")

    # Pre-flight health check
    healthy = check_searxng_health()
    if healthy:
        print_progress("1/5", f"SearXNG healthy engines: {', '.join(sorted(healthy))}")
    else:
        print_progress("1/5", "WARNING: No SearXNG engines responding — falling back to Yelu.sg + direct Mojeek")

    # SG districts for area-based query rotation.
    # Each run picks a fresh batch of 3 areas → surfaces location-specific companies
    # that don't appear in generic "interior design Singapore" queries.
    _SG_AREAS = [
        "Jurong", "Woodlands", "Tampines", "Bedok", "Hougang",
        "Sengkang", "Punggol", "Yishun", "Ang Mo Kio", "Bishan",
        "Toa Payoh", "Serangoon", "Queenstown", "Clementi", "Buona Vista",
        "Tiong Bahru", "CBD", "Bugis", "Kallang", "Geylang",
        "Pasir Ris", "Katong", "Marine Parade", "Paya Lebar", "Novena",
        "Orchard", "River Valley", "Alexandra", "Bukit Timah", "Holland Village",
        "Balestier", "Bukit Batok", "Choa Chu Kang", "Sembawang", "Jurong West",
    ]
    area_batch_start = (run_count * 3) % len(_SG_AREAS)
    area_batch = [_SG_AREAS[(area_batch_start + i) % len(_SG_AREAS)] for i in range(3)]

    # Production query set — optimized for high company-homepage yield.
    # Per-query preferred engine lists spread load across engines to avoid rate limits.
    # Rotate primary engine by run_count: google-first on even runs, startpage-first on odd.
    # This diversifies results further across repeated runs of the same industry.
    # Engine preference lists — each includes full fallback cascade so if tier-1 engines
    # are rate-limited, tiers 2-4 keep the query alive. Order tuned for SG B2B yield.
    e_primary = ["google", "startpage", "bing", "duckduckgo", "yandex", "mojeek", "yahoo", "brave", "aol", "karmasearch"]
    e_alt     = ["startpage", "google", "bing", "duckduckgo", "mojeek", "yandex", "yahoo", "brave", "aol", "karmasearch"]
    e_site    = ["bing", "google", "duckduckgo", "yandex", "startpage", "mojeek", "yahoo", "brave", "aol", "karmasearch"]  # site: ops work best on bing/google
    rotate = run_count % 2
    e_main = e_alt if rotate else e_primary
    e_list = ["startpage", "google", "mojeek", "bing", "yahoo", "brave", "aol", "karmasearch"]  # listicles — high-yield engines

    queries = [
        # ── Tier 1: Direct company homepage hits (highest precision) ──────────
        (f'{primary} "Pte Ltd" Singapore',              e_main),
        (f'{primary} pte ltd singapore phone email',    e_alt),
        # site: operators — bing/google handle these best
        (f'site:com.sg {primary}',                      e_site),
        (f'site:com.sg {primary} pte ltd',              e_site),
        (f'"{primary}" "Pte Ltd" Singapore site:.sg',   e_site),
        # ── Tier 2: Mixed direct + listicles (feed listicle expander) ─────────
        (f'site:.sg {primary} contractor',              e_site),
        (f'{primary} company Singapore -directory -jobs -blog', e_main),
        # ── Tier 3: Listicle expansion queries ───────────────────────────────
        (f'top {primary} companies Singapore 2024',     e_list),
        (f'best {primary} Singapore list',              e_list),
    ]
    # Add 4 diversity queries for each additional synonym (up to 3 more)
    for syn in synonyms[1:4]:
        if syn.lower() == primary.lower():
            continue
        queries.extend([
            (f'{syn} "Pte Ltd" Singapore',                      e_main),
            (f'site:com.sg {syn}',                              e_site),
            (f'{syn} pte ltd singapore phone email',            e_alt),
            (f'{syn} company Singapore -directory -jobs -blog', e_main),
        ])

    # Area-rotation queries: 3 areas × 2 queries = 6 queries, rotating batch each run.
    # Surfaces location-specific companies not visible in generic Singapore-wide queries.
    for area in area_batch:
        queries.extend([
            (f'"{primary}" Singapore {area}',                   e_alt),
            (f'site:com.sg {primary} {area}',                   e_site),
        ])

    search_data = []
    query_metrics = []
    failed_engines = {}  # engine -> consecutive failure count (don't permanently blacklist)

    for i, (q, preferred) in enumerate(queries, 1):
        # Skip engines with 3+ consecutive failures (don't permanently blacklist after 1)
        viable = [e for e in preferred if failed_engines.get(e, 0) < 3]
        if not viable:
            viable = preferred  # if all preferred failed, try anyway as last resort

        start_ts = time.time()
        result = searxng_search(q, limit=20, preferred_engines=viable)
        elapsed = time.time() - start_ts
        raw_count = len(result.get("results", []))
        engine_used = result.get("_engine", "unknown")
        source_used = result.get("_source", "unknown")
        search_data.append(result)
        query_metrics.append({
            "query": q,
            "preferred": preferred,
            "engine": engine_used,
            "source": source_used,
            "raw": raw_count,
            "time_ms": round(elapsed * 1000),
        })

        # Track engine failures for smart skipping (reset on success)
        if raw_count == 0 and engine_used in viable:
            failed_engines[engine_used] = failed_engines.get(engine_used, 0) + 1
        elif raw_count > 0 and engine_used in failed_engines:
            failed_engines[engine_used] = 0

        if raw_count > 0:
            print_progress("1/5", f"Query {i}/{len(queries)}: {raw_count} results via {engine_used} ({elapsed:.1f}s)")
        else:
            print_progress("1/5", f"Query {i}/{len(queries)}: NO results via {engine_used} ({elapsed:.1f}s)")

        # Short delay between queries to avoid rate-limiting
        time.sleep(1.0)

    # Yelu.sg directory: paginate based on run_count so each run gets a different batch.
    # run 0 → pages 1-3, run 1 → pages 4-6, run 2 → pages 7-9, etc.
    # Yelu.sg has 11+ pages per major category (220+ companies).
    yelu_start_page = (run_count * 3) + 1
    yelu_start_ts = time.time()
    yelu = _yelu_sg_search(args.industry, limit=30, start_page=yelu_start_page)
    yelu_time = time.time() - yelu_start_ts
    if yelu.get("results"):
        search_data.append(yelu)
        print_progress("1/5", f"Yelu.sg pages {yelu_start_page}-{yelu_start_page+2}: {len(yelu['results'])} results ({yelu_time:.1f}s)")
    else:
        # Pages exhausted — fall back to pages 1-3
        yelu = _yelu_sg_search(args.industry, limit=30, start_page=1)
        if yelu.get("results"):
            search_data.append(yelu)
            print_progress("1/5", f"Yelu.sg pages 1-3 (wrapped): {len(yelu['results'])} results ({yelu_time:.1f}s)")
        else:
            print_progress("1/5", f"Yelu.sg: NO results ({yelu_time:.1f}s)")

    total_raw = sum(len(e.get("results", [])) for e in search_data)
    print_progress("1/5", f"Search returned {total_raw} results total")

    # Log query metrics for troubleshooting
    print(f"QUERY_METRICS: {json.dumps(query_metrics)}", flush=True)

    # Stage 2: Build leads
    print_progress("2/5", "Building lead list from search results")
    leads = results_to_leads(search_data, args.industry, industry_terms=synonyms)
    print_progress("2/5", f"Built {len(leads)} unique leads")

    # Cross-run history filter (skip companies seen in previous runs)
    if _SEEN_OK and not args.allow_repeats:
        history_path = args.history_file  # may be None — seen_companies uses default path
        try:
            new_leads, repeat_leads = filter_new(leads, industry=args.industry)
            if repeat_leads:
                print_progress("2/5", f"History filter: {len(repeat_leads)} already-seen companies skipped, {len(new_leads)} new")
            leads = new_leads
        except Exception as e:
            print_progress("2/5", f"Warning: history filter failed ({e}) — using all leads")

    if args.max_leads > 0:
        leads = leads[:args.max_leads]
        print_progress("2/5", f"Limited to {len(leads)} leads for pipeline")

    # Stage 3: Website enrichment (emails, phones, DMs)
    print_progress("3/5", "Enriching websites for emails, phones, decision makers")
    total = len(leads)
    completed = 0
    enriched = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(enrich_website, lead): lead for lead in leads}
        for future in as_completed(futures):
            enriched.append(future.result())
            completed += 1
            if completed % 5 == 0 or completed == total:
                print_progress("3/5", f"Enriched {completed}/{total} websites ({round(completed/total*100)}%)")

    # Sort: leads with email first, then website-only, then phone-only
    enriched.sort(key=lambda r: (
        0 if r.get("email", "").strip() else 1,
        0 if r.get("website", "").strip() else 1,
        0 if r.get("phone", "").strip() else 1,
    ))

    raw_csv = temp_prefix + "_raw.csv"
    leads_to_csv(enriched, raw_csv)
    print_progress("3/5", f"Saved raw leads to {raw_csv}")

    # Stage 4: Deduplication + scoring
    print_progress("4/5", "Running deduplication and scoring")
    dedup_csv = temp_prefix + "_deduped.csv"
    ok, stdout, stderr = run_dedup(raw_csv, dedup_csv, args.min_score)
    if not ok:
        print(json.dumps({"error": "dedup failed", "stdout": stdout, "stderr": stderr}))
        sys.exit(1)

    with open(dedup_csv, "r", encoding="utf-8-sig") as f:
        row_count = sum(1 for _ in f) - 1
    print_progress("4/5", f"Deduplication complete: {row_count} scored leads")

    # Stage 5: Copy to final output
    print_progress("5/5", f"Writing final CSV to {args.output}")
    import shutil
    shutil.copy(dedup_csv, args.output)

    if args.min_confidence:
        CONF_RANK = {"low": 0, "medium": 1, "high": 2}
        min_rank = CONF_RANK[args.min_confidence]
        import csv as _csv_mod
        with open(args.output, "r", encoding="utf-8-sig") as f:
            _reader = _csv_mod.DictReader(f)
            _fieldnames = _reader.fieldnames or []
            rows = list(_reader)
        before = len(rows)
        rows = [r for r in rows if CONF_RANK.get((r.get("industry_confidence") or "low").lower(), 0) >= min_rank]
        dropped = before - len(rows)
        if dropped:
            print(f"PROGRESS: Confidence filter ({args.min_confidence}+): dropped {dropped} low-confidence leads")
        with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
            _writer = _csv_mod.DictWriter(f, fieldnames=_fieldnames)
            _writer.writeheader()
            _writer.writerows(rows)
        row_count = len(rows)

    # Optional Stage 6: LLM-based QC pass (drops page-title / tagline / non-SG junk)
    if args.qc:
        print_progress("6/6", "QC pass — DeepSeek v4 reviewing company names")
        qc_script = os.path.join(SCRIPT_DIR, "qc_leads.py")
        rejected_path = args.output.replace(".csv", "_rejected.csv")
        qc_tmp = args.output + ".qc.csv"
        qc_cmd = [
            sys.executable, qc_script, args.output,
            "-o", qc_tmp,
            "--rejected-log", rejected_path,
            "--model", args.qc_model,
            "--batch-size", "30",
            "--no-codeblock",
        ]
        qc_result = subprocess.run(qc_cmd, capture_output=True, text=True)
        if qc_result.returncode == 0 and os.path.exists(qc_tmp):
            # Replace main output with QC'd version
            shutil.move(qc_tmp, args.output)
            # Count kept vs rejected
            import csv as _csv
            with open(args.output, encoding="utf-8-sig") as f:
                kept_count = sum(1 for _ in _csv.DictReader(f))
            rejected_count = 0
            if os.path.exists(rejected_path):
                with open(rejected_path, encoding="utf-8-sig") as f:
                    rejected_count = sum(1 for _ in _csv.DictReader(f))
            print_progress("6/6", f"QC complete: {kept_count} kept, {rejected_count} junk removed")
        else:
            print_progress("6/6", f"QC FAILED (exit {qc_result.returncode}) — keeping unfiltered output")
            print(qc_result.stderr, file=sys.stderr)

    # Commit surfaced companies to cross-run registry
    if _SEEN_OK and not args.allow_repeats:
        try:
            import csv as _csv
            from seen_companies import record_run as _record_run
            _dir_name = os.path.basename(os.path.dirname(args.output) or "")
            # Use timestamp when dir name is non-unique (tmp, leads, standalone)
            # so each run gets a distinct run_id for pagination tracking.
            _NON_UNIQUE_DIRS = {"tmp", "standalone", "leads", "", "run"}
            run_id = _dir_name if _dir_name not in _NON_UNIQUE_DIRS else f"run_{time.strftime('%Y%m%d_%H%M%S')}"
            with open(args.output, encoding="utf-8-sig") as f:
                output_rows = list(_csv.DictReader(f))
            commit_seen(output_rows, run_id=run_id, industry=args.industry, status="surfaced")
            # Always record the run even when no domains were committed (e.g. Yelu-only runs)
            _record_run(industry=args.industry, run_id=run_id)
        except Exception:
            pass

    # Summary
    summary = {
        "status": "success",
        "industry": args.industry,
        "searched_results": total_raw,
        "unique_leads": len(leads),
        "enriched_leads": len(enriched),
        "final_leads": row_count,
        "output": args.output,
        "searxng_engines": sorted(SEARXNG_HEALTHY_ENGINES) if SEARXNG_HEALTHY_ENGINES else ["none"],
    }
    print(f"PIPELINE_SUMMARY: {json.dumps(summary)}", flush=True)


if __name__ == "__main__":
    main()
