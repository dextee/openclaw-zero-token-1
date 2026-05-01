"""CSV reading, caching, and lead management for the portal."""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import csv
import json
import hashlib
import re
from datetime import datetime, timezone

SKILL_BASE = Path("/root/openclaw-zero-token/skills")
LEADS_SEARCH_DIRS = [
    SKILL_BASE / "sg-leadgen" / "leads",
    SKILL_BASE / "sg-enrich" / "leads",
    SKILL_BASE / "sg-verify" / "leads",
    SKILL_BASE / "sg-outreach" / "leads",
    Path("/root/.openclaw/workspace/leads"),
]
CAMPAIGN_BASES = [
    Path("/root/.openclaw/workspace/campaigns"),
    Path("/root/.openclaw/workspace/leads"),
]

@dataclass
class LeadFile:
    path: Path
    filename: str
    stage: str
    mtime: datetime
    row_count: int = 0

@dataclass
class PageData:
    rows: list[dict]
    columns: list[str]
    page: int
    page_size: int
    total: int
    total_pages: int

@dataclass
class Campaign:
    path: Path
    name: str
    status: str
    created: datetime
    file_id: str = ""

@dataclass
class MasterStat:
    industry: str
    file_count: int
    total_leads: int
    last_updated: Optional[datetime] = None

_csv_cache: dict[str, tuple[list[dict], list[str], datetime]] = {}


def _file_id(path: Path) -> str:
    return hashlib.sha256(str(path).encode()).hexdigest()[:16]


def _read_csv(path: Path) -> tuple[list[dict], list[str]]:
    """Read a CSV file, returning rows and headers."""
    if not path.exists():
        return [], []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = list(reader)
        return rows, headers
    except Exception:
        return [], []


def _get_cached_csv(path: Path) -> tuple[list[dict], list[str]]:
    """Get CSV with caching based on mtime."""
    key = str(path)
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    if key in _csv_cache:
        cached_rows, cached_headers, cached_mtime = _csv_cache[key]
        if cached_mtime == mtime:
            return cached_rows, cached_headers
    rows, headers = _read_csv(path)
    _csv_cache[key] = (rows, headers, mtime)
    return rows, headers


def _count_rows(path: Path) -> int:
    """Fast row count without full parse."""
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return sum(1 for _ in f) - 1  # minus header
    except Exception:
        return 0


def _stage_from_path(path: Path) -> str:
    """Determine stage from directory name."""
    parts = [p.lower() for p in path.parts]
    if "sg-leadgen" in parts or "leadgen" in parts:
        return "leadgen"
    if "sg-enrich" in parts or "enrich" in parts:
        return "enriched"
    if "sg-verify" in parts or "verify" in parts:
        return "verified"
    if "sg-outreach" in parts or "outreach" in parts:
        return "outreach"
    return "other"


def _compute_row_hash(row: dict) -> str:
    """Compute a stable hash for a row."""
    vals = "|".join(str(v) for v in row.values())
    return hashlib.sha256(vals.encode()).hexdigest()[:16]


def _compute_lead_score(row: dict) -> int:
    """Compute a lead score from row data."""
    score = 0
    email = (row.get("email") or row.get("Email") or "").strip()
    if email and "@" in email:
        score += 30
    dm = (row.get("decision_maker_name") or row.get("contact_name") or row.get("dm_name") or "").strip()
    if dm:
        score += 25
    phone = (row.get("phone") or row.get("Phone") or "").strip()
    if phone:
        score += 15
    industry = (row.get("industry") or row.get("Industry") or "").strip()
    if industry:
        score += 10
    website = (row.get("website") or row.get("Website") or "").strip()
    if website:
        score += 10
    if row.get("email_verified") == "true":
        score += 10
    elif row.get("email_verified") == "catch_all":
        score += 5
    return min(score, 100)


def _lead_tier(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 60:
        return "B"
    if score >= 35:
        return "C"
    return "D"


def _sendability(row: dict) -> str:
    verify = (row.get("email_verified") or row.get("verify_status") or "").strip().lower()
    if verify in ("true", "valid"):
        return "verified"
    if verify in ("catch_all", "unknown", "unverifiable"):
        return "risky"
    if verify in ("false", "invalid", "bounce", "no_mx"):
        return "bad"
    email = (row.get("email") or row.get("Email") or "").strip()
    if not email or "@" not in email:
        return "bad"
    return "risky"


def _has_email(row: dict) -> bool:
    email = (row.get("email") or row.get("Email") or "").strip()
    return bool(email and "@" in email)


def _enrich_row(row: dict) -> dict:
    """Add computed columns to a row."""
    score = _compute_lead_score(row)
    row = dict(row)
    row["_lead_score"] = score
    row["_lead_tier"] = _lead_tier(score)
    row["_sendability"] = _sendability(row)
    row["_has_email"] = _has_email(row)
    row["_row_hash"] = _compute_row_hash(row)
    return row


# ── Public API ───────────────────────────────────────────────────────────────


def list_lead_files() -> list[LeadFile]:
    """Scan all LEADS_SEARCH_DIRS for .csv files, return sorted by mtime desc."""
    files = []
    for d in LEADS_SEARCH_DIRS:
        if not d.exists():
            continue
        for path in d.glob("*.csv"):
            if path.name.startswith("."):
                continue
            stat = path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            stage = _stage_from_path(path)
            row_count = _count_rows(path)
            files.append(LeadFile(
                path=path,
                filename=path.name,
                stage=stage,
                mtime=mtime,
                row_count=row_count,
            ))
    files.sort(key=lambda f: f.mtime, reverse=True)
    return files


def get_file_by_id(file_id: str) -> Optional[LeadFile]:
    """Find a LeadFile by its file_id hash."""
    for lf in list_lead_files():
        if _file_id(lf.path) == file_id:
            return lf
    return None


def get_leads_page(
    lead_file: LeadFile,
    q: str = "",
    sendability: str = "",
    tier: str = "",
    min_score: int = 0,
    has_email: Optional[bool] = None,
    sort_col: str = "",
    sort_dir: str = "asc",
    page: int = 1,
    page_size: int = 50,
) -> PageData:
    """Read CSV, filter, sort, paginate."""
    rows, headers = _get_cached_csv(lead_file.path)
    if not rows:
        return PageData(rows=[], columns=headers, page=1, page_size=page_size, total=0, total_pages=0)

    # Enrich rows
    rows = [_enrich_row(r) for r in rows]

    # Filter by query string
    if q:
        q_lower = q.lower()
        rows = [r for r in rows if any(q_lower in str(v).lower() for v in r.values())]

    # Filter by sendability
    if sendability:
        rows = [r for r in rows if r.get("_sendability") == sendability]

    # Filter by tier
    if tier:
        rows = [r for r in rows if r.get("_lead_tier") == tier]

    # Filter by min score
    if min_score > 0:
        rows = [r for r in rows if (r.get("_lead_score") or 0) >= min_score]

    # Filter by has_email
    if has_email is not None:
        rows = [r for r in rows if r.get("_has_email") == has_email]

    # Sort
    if sort_col:
        def sort_key(r):
            val = r.get(sort_col, "")
            try:
                return float(val)
            except (ValueError, TypeError):
                return str(val).lower()
        rows.sort(key=sort_key, reverse=(sort_dir == "desc"))
    else:
        # Default sort by mtime order (preserve file order)
        pass

    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = rows[start:end]

    return PageData(
        rows=page_rows,
        columns=headers,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


def get_lead_summary(lead_file: LeadFile) -> dict:
    """Return summary stats for a lead file."""
    rows, _ = _get_cached_csv(lead_file.path)
    if not rows:
        return {"total": 0, "with_email": 0, "by_tier": {}, "by_sendability": {}}

    rows = [_enrich_row(r) for r in rows]
    total = len(rows)
    with_email = sum(1 for r in rows if r.get("_has_email"))
    by_tier = {"A": 0, "B": 0, "C": 0, "D": 0}
    by_sendability = {"verified": 0, "risky": 0, "bad": 0}
    for r in rows:
        t = r.get("_lead_tier", "D")
        by_tier[t] = by_tier.get(t, 0) + 1
        s = r.get("_sendability", "risky")
        by_sendability[s] = by_sendability.get(s, 0) + 1

    return {
        "total": total,
        "with_email": with_email,
        "by_tier": by_tier,
        "by_sendability": by_sendability,
    }


def write_row_edit(lead_file: LeadFile, row_hash: str, col: str, value: str) -> tuple[bool, Optional[str]]:
    """Find row by _row_hash, update col to value, rewrite CSV."""
    rows, headers = _get_cached_csv(lead_file.path)
    if not rows:
        return False, "File is empty or unreadable"

    found = False
    for i, r in enumerate(rows):
        if _compute_row_hash(r) == row_hash:
            rows[i][col] = value
            found = True
            break

    if not found:
        return False, "Row not found"

    try:
        with open(lead_file.path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        # Invalidate cache
        _csv_cache.pop(str(lead_file.path), None)
        return True, None
    except Exception as e:
        return False, str(e)


def delete_rows(lead_file: LeadFile, row_hashes: list[str]) -> tuple[int, Optional[str]]:
    """Remove rows matching hashes, rewrite CSV."""
    rows, headers = _get_cached_csv(lead_file.path)
    if not rows:
        return 0, "File is empty or unreadable"

    before = len(rows)
    rows = [r for r in rows if _compute_row_hash(r) not in set(row_hashes)]
    deleted = before - len(rows)

    try:
        with open(lead_file.path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        _csv_cache.pop(str(lead_file.path), None)
        return deleted, None
    except Exception as e:
        return 0, str(e)


def list_campaigns() -> list[Campaign]:
    """Scan CAMPAIGN_BASES for dirs containing campaign_state.json."""
    campaigns = []
    for base in CAMPAIGN_BASES:
        if not base.exists():
            continue
        for path in base.rglob("campaign_state.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except Exception:
                continue
            parent = path.parent
            name = state.get("name", parent.name)
            status = state.get("status", "unknown")
            created_str = state.get("created", "")
            try:
                created = datetime.fromisoformat(created_str) if created_str else datetime.fromtimestamp(parent.stat().st_mtime, tz=timezone.utc)
            except Exception:
                created = datetime.fromtimestamp(parent.stat().st_mtime, tz=timezone.utc)
            campaigns.append(Campaign(
                path=parent,
                name=name,
                status=status,
                created=created,
                file_id=_file_id(parent),
            ))
    campaigns.sort(key=lambda c: c.created, reverse=True)
    return campaigns


def get_campaign_by_id(file_id: str) -> Optional[Campaign]:
    for c in list_campaigns():
        if c.file_id == file_id:
            return c
    return None


def get_campaign_rows(campaign: Campaign) -> list[dict]:
    """Read campaign's lead CSV files."""
    candidates = [
        campaign.path / "sg_leads_verified.csv",
        campaign.path / "leads.csv",
        campaign.path / "sequences.csv",
    ]
    for p in candidates:
        if p.exists():
            rows, _ = _read_csv(p)
            return [_enrich_row(r) for r in rows]
    # Fallback: any CSV in campaign dir
    for p in campaign.path.glob("*.csv"):
        rows, _ = _read_csv(p)
        return [_enrich_row(r) for r in rows]
    return []


def get_dashboard_data() -> dict:
    """Aggregate dashboard KPIs."""
    files = list_lead_files()
    total_files = len(files)
    total_leads = sum(f.row_count for f in files)

    by_stage = {}
    for f in files:
        by_stage[f.stage] = by_stage.get(f.stage, 0) + f.row_count

    recent_uploads = [
        {"filename": f.filename, "stage": f.stage, "mtime": f.mtime.isoformat(), "rows": f.row_count}
        for f in files[:5]
    ]

    # Pipeline health
    if not files:
        health = {"status": "empty", "color": "red", "message": "No lead files found"}
    else:
        newest = files[0].mtime
        age_days = (datetime.now(timezone.utc) - newest).total_seconds() / 86400
        if age_days < 1:
            health = {"status": "healthy", "color": "green", "message": "Recent activity detected"}
        elif age_days < 7:
            health = {"status": "stale", "color": "yellow", "message": f"Last activity {age_days:.1f} days ago"}
        else:
            health = {"status": "stale", "color": "red", "message": f"Last activity {age_days:.1f} days ago"}

    return {
        "total_files": total_files,
        "total_leads": total_leads,
        "by_stage": by_stage,
        "recent_uploads": recent_uploads,
        "health": health,
    }


def get_deliverability_report() -> dict:
    """Read SPF/DKIM/DMARC/MX results if available."""
    report_path = Path("/root/.openclaw/workspace/deliverability.json")
    if report_path.exists():
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "spf": {"status": "unknown", "detail": "No deliverability data"},
        "dkim": {"status": "unknown", "detail": "No deliverability data"},
        "dmarc": {"status": "unknown", "detail": "No deliverability data"},
        "mx": {"status": "unknown", "detail": "No deliverability data"},
    }


def get_outreach_stats() -> dict:
    """Read outreach history for stats."""
    history_path = Path("/root/.openclaw/workspace/outreach/.outreach_history.json")
    if not history_path.exists():
        # Try alternate locations
        alts = [
            Path("/root/openclaw-zero-token/skills/sg-outreach/.outreach_history.json"),
            Path("/root/.openclaw/workspace/.outreach_history.json"),
        ]
        for p in alts:
            if p.exists():
                history_path = p
                break

    if not history_path.exists():
        return {"sent": 0, "bounced": 0, "replied": 0, "bounce_rate": 0, "reply_rate": 0}

    try:
        with open(history_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        contacts = data.get("contacts", [])
        sent = len([c for c in contacts if c.get("status") == "sent"])
        bounced = len([c for c in contacts if c.get("status") == "bounced"])
        replied = len([c for c in contacts if c.get("replied")])
        total = len(contacts)
        return {
            "sent": sent,
            "bounced": bounced,
            "replied": replied,
            "bounce_rate": round(bounced / total * 100, 1) if total else 0,
            "reply_rate": round(replied / total * 100, 1) if total else 0,
        }
    except Exception:
        return {"sent": 0, "bounced": 0, "replied": 0, "bounce_rate": 0, "reply_rate": 0}


def get_recent_contacts(n: int = 20) -> list[dict]:
    """Last N contacts from history."""
    history_path = Path("/root/.openclaw/workspace/outreach/.outreach_history.json")
    if not history_path.exists():
        alts = [
            Path("/root/openclaw-zero-token/skills/sg-outreach/.outreach_history.json"),
            Path("/root/.openclaw/workspace/.outreach_history.json"),
        ]
        for p in alts:
            if p.exists():
                history_path = p
                break

    if not history_path.exists():
        return []

    try:
        with open(history_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        contacts = data.get("contacts", [])
        contacts.sort(key=lambda c: c.get("timestamp", ""), reverse=True)
        return contacts[:n]
    except Exception:
        return []


def get_suppression_list() -> list[dict]:
    """Read suppressions (unsubscribe, bounce, negative)."""
    suppress_path = Path("/root/.openclaw/workspace/outreach/suppressions.json")
    if not suppress_path.exists():
        alts = [
            Path("/root/openclaw-zero-token/skills/sg-outreach/suppressions.json"),
            Path("/root/.openclaw/workspace/suppressions.json"),
        ]
        for p in alts:
            if p.exists():
                suppress_path = p
                break

    if not suppress_path.exists():
        return []

    try:
        with open(suppress_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def get_master_stats() -> list[MasterStat]:
    """Stats per industry master CSV."""
    stats = []
    master_dir = Path("/root/.openclaw/workspace/leads")
    if not master_dir.exists():
        return stats

    # Group by industry prefix
    industry_files = {}
    for path in master_dir.glob("*.csv"):
        name = path.name.lower()
        # Extract industry from filename
        industry = "other"
        for key in ["construction", "accounting", "medical", "education", "law", "tech", "restaurant", "retail", "logistics", "fintech", "insurance", "marketing", "interior"]:
            if key in name:
                industry = key
                break
        industry_files.setdefault(industry, []).append(path)

    for industry, paths in industry_files.items():
        total = 0
        latest = None
        for p in paths:
            rows, _ = _read_csv(p)
            total += len(rows)
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if latest is None or mtime > latest:
                latest = mtime
        stats.append(MasterStat(
            industry=industry.title(),
            file_count=len(paths),
            total_leads=total,
            last_updated=latest,
        ))

    stats.sort(key=lambda s: s.total_leads, reverse=True)
    return stats


def formula_inject_protect(value: str) -> str:
    """Prefix cells starting with formula injection chars with a single quote."""
    if value and str(value)[0] in ('=', '+', '-', '@', '\t', '\r', '|'):
        return "'" + str(value)
    return str(value)
