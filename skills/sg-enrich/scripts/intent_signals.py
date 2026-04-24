"""Intent signal discovery via Google search.

Checks GeBIZ tenders, job postings on MyCareersFuture, and recent news
for Singapore companies. Uses Google search with rate limiting.
"""

import random
import re
import time
from datetime import datetime

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)

HIRING_TITLES = [
    "Sales", "Business Development", "Account Manager", "Marketing",
    "IT", "Software", "Developer", "Operations", "Manager", "Director",
    "Admin", "Finance", "HR", "Customer Service", "Logistics"
]

_google_request_count = 0
_google_session = None
_current_year = str(datetime.now().year)


def _get_session():
    global _google_session
    if _google_session is None:
        _google_session = requests.Session()
        _google_session.headers.update({"User-Agent": USER_AGENT})
    return _google_session


def _google_rate_limit():
    """Apply rate limiting for Google searches."""
    global _google_request_count
    _google_request_count += 1

    # Random delay 3-6 seconds between all Google requests
    time.sleep(random.uniform(3, 6))

    # After every 20 Google requests, sleep 30 seconds
    if _google_request_count % 20 == 0:
        time.sleep(30)


def _google_search(query: str) -> str:
    """Execute a Google search and return the HTML."""
    _google_rate_limit()
    session = _get_session()
    try:
        resp = session.get(
            f"https://www.google.com/search?q={requests.utils.quote(query)}",
            timeout=8,
            verify=False,
        )
        if resp.status_code == 429:
            time.sleep(60)
            resp = session.get(
                f"https://www.google.com/search?q={requests.utils.quote(query)}",
                timeout=8,
                verify=False,
            )
        return resp.text
    except Exception:
        return ""


def _extract_snippets(html: str) -> list:
    """Extract text snippets from Google search results HTML."""
    snippets = []
    if not html:
        return snippets
    # Try to find result snippets
    pattern = re.compile(r'<div[^>]*class=["\'](?:[a-zA-Z-]*result|snippet|st)[^"\']*["\']>(.*?)</div>', re.DOTALL | re.IGNORECASE)
    for match in pattern.finditer(html):
        text = re.sub(r'<[^>]+>', ' ', match.group(1))
        text = re.sub(r'\s+', ' ', text).strip()
        if text:
            snippets.append(text)

    # Fallback: broader extraction
    if not snippets:
        pattern2 = re.compile(r'class=["\'][^"\']*snippet[^"\']*["\'][^>]*>(.*?)</', re.DOTALL)
        for match in pattern2.finditer(html):
            text = re.sub(r'<[^>]+>', ' ', match.group(1))
            text = re.sub(r'\s+', ' ', text).strip()
            if text:
                snippets.append(text)

    return snippets


def _check_gebiz(company_name: str) -> dict:
    """Check for GeBIZ tender activity."""
    query = f'site:gebiz.gov.sg "{company_name}"'
    html = _google_search(query)
    snippets = _extract_snippets(html)

    result = {"recent_tender": False, "tender_value": ""}

    # Look for dollar amounts in snippets
    dollar_pattern = re.compile(r'(?:SGD\s*[\d,]+|S\$\s*[\d,]+|\$[\d,]+)')
    for snippet in snippets:
        match = dollar_pattern.search(snippet)
        if match and any(yr in snippet for yr in (str(datetime.now().year), str(datetime.now().year - 1))):
            result["recent_tender"] = True
            result["tender_value"] = match.group(0)
            return result

    return result


def _check_jobs(company_name: str) -> list:
    """Check for job postings on MyCareersFuture."""
    query = f'site:mycareersfuture.gov.sg "{company_name}"'
    html = _google_search(query)
    snippets = _extract_snippets(html)

    hiring = []
    for snippet in snippets:
        snippet_lower = snippet.lower()
        for title in HIRING_TITLES:
            if title.lower() in snippet_lower and title not in hiring:
                hiring.append(title)

    return hiring


def _check_news(company_name: str) -> str:
    """Check for recent news about the company."""
    query = f'"{company_name}" Singapore (expansion OR funding OR launch OR award OR partnership)'
    html = _google_search(query)
    snippets = _extract_snippets(html)

    for snippet in snippets:
        if _current_year in snippet or str(int(_current_year) - 1) in snippet:
            return snippet[:120]

    return ""


def get_intent_signals(company_name: str, domain: str = None,
                     industry: str = None, session: requests.Session = None) -> dict:
    """Get intent signals for a company.

    Returns dict with keys:
    - recent_tender: bool or None
    - tender_value: str
    - hiring_signals: list[str]
    - news_signal: str
    - raw_intent_list: list[str]
    """
    result = {
        "recent_tender": None,
        "tender_value": "",
        "hiring_signals": [],
        "news_signal": "",
        "raw_intent_list": []
    }

    if not company_name:
        return result

    # GeBIZ tender check
    try:
        gebiz = _check_gebiz(company_name)
        result["recent_tender"] = gebiz["recent_tender"]
        result["tender_value"] = gebiz["tender_value"]
        if gebiz["recent_tender"]:
            result["raw_intent_list"].append("gebiz_tender")
    except Exception:
        pass

    # Job postings check
    try:
        hiring = _check_jobs(company_name)
        result["hiring_signals"] = hiring
        if hiring:
            result["raw_intent_list"].append("hiring_" + "_".join(hiring[:2]).lower().replace(" ", "_"))
    except Exception:
        pass

    # News check
    try:
        news = _check_news(company_name)
        result["news_signal"] = news
        if news:
            result["raw_intent_list"].append("news_activity")
    except Exception:
        pass

    return result
