"""CSV reading, caching, and lead management for the portal."""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import csv
import json
import hashlib
import re
from datetime import datetime, timedelta, timezone

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
OUTREACH_BASE = Path("/root/.openclaw/workspace/outreach")

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
class ActiveCampaign:
    user_id: str
    sender_name: str
    sender_company: str
    daily_limit: int
    sequences_csv: Path
    total_sequences: int
    sent: int
    pending: int
    failed: int
    replied: int
    reply_rate: float
    positive_replies: int
    negative_replies: int
    bounced: int
    senders: list
    next_run_sgt: str
    campaign_started: str
    is_paused: bool
    days_remaining: int
    pct_complete: float
    consecutive_failures: int
    last_run_ok: Optional[bool]  # None = no runs yet

@dataclass
class MasterStat:
    industry: str
    file_count: int
    total_leads: int
    last_updated: Optional[datetime] = None

_CSV_CACHE_MAX = 80
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
    if len(_csv_cache) >= _CSV_CACHE_MAX:
        _csv_cache.pop(next(iter(_csv_cache)))
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
    """Determine stage from directory name, then filename."""
    parts = [p.lower() for p in path.parts]
    if "sg-leadgen" in parts or "leadgen" in parts:
        return "leadgen"
    if "sg-enrich" in parts or "enrich" in parts:
        return "enriched"
    if "sg-verify" in parts or "verify" in parts:
        return "verified"
    if "sg-outreach" in parts or "outreach" in parts:
        return "outreach"
    name = path.name.lower()
    if "sequence" in name:
        return "sequences"
    if "verif" in name:
        return "verified"
    if "enrich" in name:
        return "enriched"
    if "_raw" in name or "_dedup" in name or "_scored" in name or "_pipeline" in name:
        return "leadgen"
    return "other"


def _compute_row_hash(row: dict) -> str:
    """Compute a stable hash for a row."""
    vals = "|".join(str(v) for k, v in row.items() if k != "_row_hash")
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

    value = formula_inject_protect(value)  # sanitise before write

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


def _calc_next_run_sgt(cron_expr: str) -> str:
    """Next fire time in SGT. Server is Europe/Berlin (CEST=UTC+2); cron uses local time."""
    try:
        from zoneinfo import ZoneInfo
        parts = cron_expr.split()
        if len(parts) < 2:
            return "Unknown"
        minute = int(parts[0])
        hour = int(parts[1])
        server_tz = ZoneInfo("Europe/Berlin")
        sgt_tz = ZoneInfo("Asia/Singapore")
        now_server = datetime.now(server_tz)
        next_server = now_server.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_server <= now_server:
            next_server += timedelta(days=1)
        return next_server.astimezone(sgt_tz).strftime("%a %-d %b, %I:%M %p SGT")
    except Exception:
        return "Unknown"


def get_active_campaigns() -> list[ActiveCampaign]:
    """Read active outreach campaigns from workspace/outreach/user_*/."""
    campaigns: list[ActiveCampaign] = []
    if not OUTREACH_BASE.exists():
        return campaigns

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for user_dir in sorted(OUTREACH_BASE.glob("user_*")):
        campaign_file = user_dir / "active_campaign.json"
        if not campaign_file.exists():
            continue
        try:
            with open(campaign_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            continue

        sequences_path_str = cfg.get("sequences_csv", "")
        sequences_path = Path(sequences_path_str) if sequences_path_str else Path()
        total = sent = pending = failed = replied = positive_replies = negative_replies = bounced = 0
        # per-sender reply counts: {email: count}
        sender_replied_map: dict[str, int] = {}
        if sequences_path.exists():
            try:
                with open(sequences_path, "r", encoding="utf-8-sig", newline="") as f:
                    reader_obj = csv.DictReader(f)
                    for row in reader_obj:
                        s = row.get("status", "").strip()
                        total += 1
                        if s == "sent":
                            sent += 1
                        elif s == "failed":
                            failed += 1
                        else:
                            pending += 1
                        if row.get("replied", "").strip().lower() == "true":
                            replied += 1
                            sentiment = row.get("reply_sentiment", "").strip()
                            if sentiment == "Positive":
                                positive_replies += 1
                            elif sentiment == "Negative":
                                negative_replies += 1
                            s_email = row.get("sender_email", "").strip().lower()
                            if s_email:
                                sender_replied_map[s_email] = sender_replied_map.get(s_email, 0) + 1
            except Exception:
                pass
        reply_rate = round(replied / sent * 100, 1) if sent > 0 else 0.0

        senders_state = []
        for s in cfg.get("senders", []):
            state_file_str = s.get("state_file", "")
            daily_lim = s.get("daily_limit", 25)
            s_email = s.get("email", "")
            sender_info: dict = {
                "email": s_email,
                "name": (s_email.split("@")[0]).title(),
                "daily_limit": daily_lim,
                "sent_today": 0,
                "last_send_date": "",
                "is_done_today": False,
                "replied": sender_replied_map.get(s_email.lower(), 0),
            }
            if state_file_str:
                sf = Path(state_file_str)
                if sf.exists():
                    try:
                        with open(sf, "r", encoding="utf-8") as f:
                            state = json.load(f)
                        sent_today = state.get("sent_today", 0)
                        last_date = state.get("last_send_date", "")
                        sender_info["sent_today"] = sent_today
                        sender_info["last_send_date"] = last_date
                        sender_info["is_done_today"] = (
                            last_date == today_str and sent_today >= daily_lim
                        )
                    except Exception:
                        pass
            senders_state.append(sender_info)

        daily_limit = cfg.get("daily_limit", 100)
        days_remaining = max(0, (pending + daily_limit - 1) // daily_limit) if daily_limit > 0 else 0
        pct_complete = round(sent / total * 100, 1) if total > 0 else 0.0
        is_paused = (user_dir / "paused.flag").exists()
        next_run_sgt = _calc_next_run_sgt(cfg.get("cron_expr", "0 8 * * *"))

        # Watchdog: parse runs.log for consecutive tail failures and last run result
        consecutive_failures = 0
        last_run_ok: Optional[bool] = None
        runs_log_path = user_dir / "runs.log"
        if runs_log_path.exists():
            try:
                log_lines = [l for l in runs_log_path.read_text(encoding="utf-8").strip().splitlines() if l.strip()]
                if log_lines:
                    last_line = log_lines[-1]
                    last_run_ok = ("rc=0" in last_line)
                    # count consecutive failures from the end
                    for line in reversed(log_lines):
                        is_fail = "sent=0" in line and "rc=" in line and "rc=0" not in line
                        if is_fail:
                            consecutive_failures += 1
                        else:
                            break
            except Exception:
                pass

        campaigns.append(ActiveCampaign(
            user_id=cfg.get("chat_id", user_dir.name),
            sender_name=cfg.get("sender_name", "") or "Mirae Advisory",
            sender_company=cfg.get("sender_company", "Mirae Advisory"),
            daily_limit=daily_limit,
            sequences_csv=sequences_path,
            total_sequences=total,
            sent=sent,
            pending=pending,
            failed=failed,
            replied=replied,
            reply_rate=reply_rate,
            positive_replies=positive_replies,
            negative_replies=negative_replies,
            bounced=bounced,
            senders=senders_state,
            next_run_sgt=next_run_sgt,
            campaign_started=cfg.get("campaign_started", ""),
            is_paused=is_paused,
            days_remaining=days_remaining,
            pct_complete=pct_complete,
            consecutive_failures=consecutive_failures,
            last_run_ok=last_run_ok,
        ))

    return campaigns


def get_dashboard_data() -> dict:
    """Aggregate dashboard KPIs including outreach campaign stats."""
    files = list_lead_files()
    total_files = len(files)
    total_leads = sum(f.row_count for f in files)

    by_stage: dict[str, int] = {}
    for f in files:
        by_stage[f.stage] = by_stage.get(f.stage, 0) + f.row_count

    recent_uploads = [
        {"filename": f.filename, "stage": f.stage, "mtime": f.mtime.isoformat(), "rows": f.row_count}
        for f in files[:8]
    ]

    # Pipeline health
    if not files:
        health = {"status": "empty", "color": "red", "message": "No lead files found"}
    else:
        newest = files[0].mtime
        age_days = (datetime.now(timezone.utc) - newest).total_seconds() / 86400
        if age_days < 1:
            health = {"status": "healthy", "color": "green", "message": "Recent activity"}
        elif age_days < 7:
            health = {"status": "stale", "color": "yellow", "message": f"Last activity {age_days:.1f}d ago"}
        else:
            health = {"status": "stale", "color": "red", "message": f"Last activity {age_days:.1f}d ago"}

    campaigns = get_active_campaigns()
    total_sent = sum(c.sent for c in campaigns)
    total_replied = sum(c.replied for c in campaigns)
    total_pending = sum(c.pending for c in campaigns)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sent_today = sum(
        s["sent_today"]
        for c in campaigns
        for s in c.senders
        if s.get("last_send_date") == today_str
    )
    reply_rate = round(total_replied / total_sent * 100, 1) if total_sent > 0 else 0.0

    return {
        "total_files": total_files,
        "total_leads": total_leads,
        "by_stage": by_stage,
        "recent_uploads": recent_uploads,
        "health": health,
        "campaigns": campaigns,
        "total_sent": total_sent,
        "total_replied": total_replied,
        "total_pending": total_pending,
        "sent_today": sent_today,
        "reply_rate": reply_rate,
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
    """Read outreach stats from active campaigns' sequences CSV."""
    campaigns = get_active_campaigns()
    if not campaigns:
        return {"sent": 0, "bounced": 0, "replied": 0, "bounce_rate": 0, "reply_rate": 0}
    sent = replied = 0
    for c in campaigns:
        if not c.sequences_csv or not c.sequences_csv.exists():
            continue
        try:
            with open(c.sequences_csv, "r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("status") == "sent":
                        sent += 1
                        if row.get("replied", "").strip().lower() == "true":
                            replied += 1
        except Exception:
            pass
    return {
        "sent": sent,
        "bounced": 0,
        "replied": replied,
        "bounce_rate": 0,
        "reply_rate": round(replied / sent * 100, 1) if sent else 0,
    }


def get_reply_rows(sentiment_filter: str = "") -> list[dict]:
    """Return all replied sequences across all campaigns, sorted by replied_at desc."""
    campaigns = get_active_campaigns()
    rows = []
    for c in campaigns:
        if not c.sequences_csv or not c.sequences_csv.exists():
            continue
        try:
            with open(c.sequences_csv, "r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("replied", "").strip().lower() != "true":
                        continue
                    sentiment = row.get("reply_sentiment", "").strip() or "Neutral"
                    if sentiment_filter and sentiment != sentiment_filter:
                        continue
                    rows.append({
                        "company_name": row.get("company_name", ""),
                        "to_email": row.get("to_email", ""),
                        "to_name": row.get("to_name", ""),
                        "sender_email": row.get("sender_email", ""),
                        "subject": row.get("subject", ""),
                        "replied_at": row.get("replied_at", ""),
                        "reply_sentiment": sentiment,
                        "email_number": row.get("email_number", "1"),
                    })
        except Exception:
            pass
    rows.sort(key=lambda r: r.get("replied_at", ""), reverse=True)
    return rows


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
