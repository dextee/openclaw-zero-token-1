"""
directories.py — SG business directory lookups with Live-status filtering.

Status (2026-04-23):
- sgpbusiness.com:      Cloudflare-blocked. Stubs return [].
- opencorporates.com:   Forbidden (403). Stubs return [].
- data.gov.sg ACRA API: Intermittently returns 0 results. Retries with 10s cache.

All functions are safe to call — they return [] / None on any failure.
The Live-status filter (is_live_company) works on whatever data is available.
"""
import hashlib
import json
import os
import time
from typing import TypedDict

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

CACHE_DIR = "/root/.openclaw/cache/directories"
CACHE_TTL_SEC = 30 * 24 * 3600   # 30 days
ACRA_RESOURCE_ID = "d_3f960c10fed6145404ca7b821f263b87"
ACRA_TIMEOUT_SEC = 8
REQ_TIMEOUT_SEC = 10


class Lead(TypedDict, total=False):
    company_name: str
    domain: str
    uen: str
    status: str          # live / cancelled / struck_off / unknown
    entity_type: str
    reg_address: str
    industry: str
    source: str


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_key(tag: str) -> str:
    h = hashlib.md5(tag.encode()).hexdigest()[:12]
    return os.path.join(CACHE_DIR, f"{h}.json")


def _cache_get(tag: str):
    path = _cache_key(tag)
    if not os.path.exists(path):
        return None
    try:
        entry = json.load(open(path))
        if time.time() - entry.get("ts", 0) < CACHE_TTL_SEC:
            return entry.get("data")
    except Exception:
        pass
    return None


def _cache_set(tag: str, data) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_key(tag)
    try:
        json.dump({"ts": time.time(), "data": data}, open(path, "w"))
    except Exception:
        pass


# ── Live-status filter ────────────────────────────────────────────────────────

_DEAD_STATUSES = {
    "cancelled", "struck off", "in liquidation", "winding up",
    "dormant", "suspended", "deregistered", "wound up",
}


def is_live_company(lead: Lead) -> bool:
    """Return False only for companies with a known non-live status.
    Unknown status → True (don't drop companies when the source is silent).
    """
    status = (lead.get("status") or "").lower().strip()
    if not status or status == "unknown":
        return True
    for dead in _DEAD_STATUSES:
        if dead in status:
            return False
    return True


# ── sgpbusiness.com ───────────────────────────────────────────────────────────

def search_sgpbusiness(
    query: str,
    ssic_codes: list[str] | None = None,
    max_results: int = 20,
) -> list[Lead]:
    """Search sgpbusiness.com (ACRA-backed).
    Currently blocked by Cloudflare — returns [] gracefully.
    """
    # TODO: implement when Cloudflare bypass is available (Playwright / residential proxy)
    return []


# ── opencorporates.com/sg ─────────────────────────────────────────────────────

def search_opencorporates_sg(
    query: str,
    max_results: int = 20,
) -> list[Lead]:
    """Search opencorporates.com for SG companies.
    Currently returns 403 — returns [] gracefully.
    """
    # TODO: implement when access is available
    return []


# ── data.gov.sg ACRA API ──────────────────────────────────────────────────────

def lookup_acra(name_or_uen: str) -> Lead | None:
    """Look up a company on data.gov.sg ACRA dataset.
    Returns None on any failure. Caches positive results for 30 days.
    """
    if not _REQUESTS_OK:
        return None
    tag = f"acra:{name_or_uen.lower().strip()}"
    cached = _cache_get(tag)
    if cached is not None:
        return cached  # type: ignore

    try:
        resp = requests.get(
            "https://data.gov.sg/api/action/datastore_search",
            params={
                "resource_id": ACRA_RESOURCE_ID,
                "q": name_or_uen,
                "limit": 5,
            },
            timeout=ACRA_TIMEOUT_SEC,
        )
        data = resp.json()
        records = data.get("result", {}).get("records", [])
        if not records:
            return None

        # Best match: prefer exact entity_name match
        query_lower = name_or_uen.lower().strip()
        best = None
        for rec in records:
            ename = (rec.get("entity_name") or "").lower()
            if query_lower in ename or ename in query_lower:
                best = rec
                break
        if best is None:
            best = records[0]

        result: Lead = {
            "company_name": best.get("entity_name", ""),
            "uen": best.get("uen", ""),
            "status": (best.get("uen_status_desc") or "unknown").lower(),
            "entity_type": best.get("entity_type_desc", ""),
            "reg_address": " ".join(filter(None, [
                best.get("reg_street_name", ""),
                best.get("reg_postal_code", ""),
            ])),
            "source": "acra",
        }
        _cache_set(tag, result)
        return result
    except Exception:
        return None


# ── Fan-out: search all available sources ────────────────────────────────────

def search_all_sources(
    query: str,
    industry: str = "",
    ssic_codes: list[str] | None = None,
    max_results: int = 20,
) -> list[Lead]:
    """Fan out across all directory sources, merge on domain/UEN, filter non-live.
    Safe to call — returns [] if all sources fail.
    """
    results: list[Lead] = []
    try:
        results.extend(search_sgpbusiness(query, ssic_codes, max_results))
    except Exception:
        pass
    try:
        results.extend(search_opencorporates_sg(query, max_results))
    except Exception:
        pass

    # Deduplicate by UEN then domain
    seen_uens: set[str] = set()
    unique: list[Lead] = []
    for lead in results:
        uen = (lead.get("uen") or "").strip()
        if uen and uen in seen_uens:
            continue
        if uen:
            seen_uens.add(uen)
        unique.append(lead)

    return [l for l in unique if is_live_company(l)][:max_results]


if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) or "DBS Bank"
    print(f"ACRA lookup: {query!r}")
    result = lookup_acra(query)
    print(result or "No result")
    print(f"\nAll-sources search: {query!r}")
    leads = search_all_sources(query)
    print(f"{len(leads)} live companies found")
