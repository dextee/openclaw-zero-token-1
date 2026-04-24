"""
seen_companies.py — Global cross-run dedup registry for lead generation.

Registry file: /root/.openclaw/workspace/leads/.seen_companies.jsonl
Append-only JSONL. One line per surfaced company.

Usage:
    from seen_companies import load_seen, filter_new, commit, stats, purge

CLI:
    python3 seen_companies.py --stats
    python3 seen_companies.py --purge --older-than-days 180
"""
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

REGISTRY_PATH = "/root/.openclaw/workspace/leads/.seen_companies.jsonl"
_LOCK_FILE = REGISTRY_PATH + ".lock"
OUTREACH_HISTORY_PATH = "/root/openclaw-zero-token/skills/sg-outreach/.outreach_history.json"


def _norm_domain(url_or_domain: str) -> str:
    """Normalize URL or bare domain to lowercase domain without www."""
    s = (url_or_domain or "").strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    s = s.split("/")[0].split("?")[0].split("#")[0]
    return s


def _load_outreach_seen() -> set[str]:
    """Load domains from outreach history (already-contacted companies)."""
    try:
        data = json.load(open(OUTREACH_HISTORY_PATH))
        domains: set[str] = set()
        for email in data:
            parts = email.split("@")
            if len(parts) == 2:
                domains.add(_norm_domain(parts[1]))
        return domains
    except Exception:
        return set()


def load_seen() -> set[str]:
    """Return set of normalized domains from the registry + outreach history."""
    seen: set[str] = set()
    if os.path.exists(REGISTRY_PATH):
        try:
            with open(REGISTRY_PATH) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        d = entry.get("domain_norm", "")
                        if d:
                            seen.add(d)
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass
    seen.update(_load_outreach_seen())
    return seen


def filter_new(
    rows: list[dict],
    industry: str = "",
) -> tuple[list[dict], list[dict]]:
    """Split rows into (new_rows, repeat_rows) based on registry.

    Gracefully returns all rows as new if registry is unreadable.
    """
    try:
        seen = load_seen()
    except Exception:
        return rows, []

    new_rows: list[dict] = []
    repeat_rows: list[dict] = []
    for r in rows:
        domain = _norm_domain(
            r.get("website") or r.get("domain") or r.get("company_website") or ""
        )
        if domain and domain in seen:
            repeat_rows.append(r)
        else:
            new_rows.append(r)
    return new_rows, repeat_rows


def commit(
    rows: list[dict],
    run_id: str,
    chat_id: str = "",
    industry: str = "",
    status: str = "surfaced",
) -> None:
    """Append rows to the registry. Skips rows already in registry.

    Uses an exclusive lock so concurrent pipeline runs don't double-write the same domain.
    """
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    with open(_LOCK_FILE, "a") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            # Re-read inside the lock so we see any writes from concurrent processes.
            existing = load_seen()
            with open(REGISTRY_PATH, "a") as f:
                for r in rows:
                    domain = _norm_domain(
                        r.get("website") or r.get("domain") or r.get("company_website") or ""
                    )
                    if not domain or domain in existing:
                        continue
                    entry: dict[str, Any] = {
                        "domain_norm": domain,
                        "company_name": (r.get("company_name") or "").strip(),
                        "industry": industry,
                        "first_seen_at": now,
                        "run_id": run_id,
                        "user_chat_id": chat_id,
                        "status": status,
                    }
                    f.write(json.dumps(entry) + "\n")
                    existing.add(domain)
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


_RUN_COUNTS_PATH = os.path.join(os.path.dirname(REGISTRY_PATH), "_run_counts.json")


def _get_run_count_from_jsonl(industry: str) -> int:
    """Count unique run_ids in JSONL registry for this industry."""
    if not os.path.exists(REGISTRY_PATH):
        return 0
    try:
        run_ids: set[str] = set()
        with open(REGISTRY_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("industry", "").lower() == industry.lower():
                        rid = entry.get("run_id", "")
                        if rid:
                            run_ids.add(rid)
                except json.JSONDecodeError:
                    pass
        return len(run_ids)
    except Exception:
        return 0


def record_run(industry: str, run_id: str) -> int:
    """Record that a pipeline run completed for this industry. Returns new run count.

    Stored in a separate JSON file so the count increments even when no new domains
    were committed (e.g., when all output companies lack a website field).
    On first use, seeds from the JSONL registry count so pagination continues correctly.
    """
    os.makedirs(os.path.dirname(_RUN_COUNTS_PATH), exist_ok=True)
    try:
        counts: dict[str, list[str]] = {}
        if os.path.exists(_RUN_COUNTS_PATH):
            with open(_RUN_COUNTS_PATH) as f:
                counts = json.load(f)
        key = industry.lower()
        if key not in counts:
            # First time tracking this industry — seed from JSONL count
            legacy_count = _get_run_count_from_jsonl(industry)
            counts[key] = [f"legacy_{i}" for i in range(legacy_count)]
        runs = counts[key]
        if run_id not in runs:
            runs.append(run_id)
            counts[key] = runs
            with open(_RUN_COUNTS_PATH, "w") as f:
                json.dump(counts, f, indent=2)
        return len(runs)
    except Exception:
        return 0


def get_run_count(industry: str) -> int:
    """Return number of completed runs for this industry.

    Reads from _run_counts.json (populated by record_run). Falls back to counting
    unique run_ids in the JSONL registry when the file doesn't exist yet.
    Returns 0 if no runs recorded.
    """
    if os.path.exists(_RUN_COUNTS_PATH):
        try:
            with open(_RUN_COUNTS_PATH) as f:
                counts = json.load(f)
            return len(counts.get(industry.lower(), []))
        except Exception:
            pass
    # File doesn't exist yet — fall back to JSONL count
    return _get_run_count_from_jsonl(industry)


def stats() -> dict:
    """Return registry statistics."""
    if not os.path.exists(REGISTRY_PATH):
        return {"total": 0, "industries": {}, "most_recent": None}

    entries: list[dict] = []
    with open(REGISTRY_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    by_industry: dict[str, int] = {}
    most_recent = None
    for e in entries:
        ind = e.get("industry") or "unknown"
        by_industry[ind] = by_industry.get(ind, 0) + 1
        ts = e.get("first_seen_at")
        if ts and (most_recent is None or ts > most_recent):
            most_recent = ts

    return {
        "total": len(entries),
        "industries": dict(sorted(by_industry.items(), key=lambda x: -x[1])),
        "most_recent": most_recent,
    }


def purge(older_than_days: int = 180) -> int:
    """Remove entries older than N days. Returns count purged.

    Uses exclusive lock + atomic rename so concurrent readers never see a partial file.
    """
    if not os.path.exists(REGISTRY_PATH):
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)

    with open(_LOCK_FILE, "a") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            kept: list[str] = []
            purged = 0
            with open(REGISTRY_PATH) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts_str = entry.get("first_seen_at", "")
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str)
                            if ts < cutoff:
                                purged += 1
                                continue
                    except Exception:
                        pass
                    kept.append(line)

            tmp_path = REGISTRY_PATH + ".tmp"
            with open(tmp_path, "w") as f:
                for line in kept:
                    f.write(line + "\n")
            os.replace(tmp_path, REGISTRY_PATH)  # atomic on same filesystem
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)

    return purged


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Seen-companies registry tool")
    parser.add_argument("--stats", action="store_true", help="Print registry statistics")
    parser.add_argument("--purge", action="store_true", help="Purge old entries")
    parser.add_argument("--older-than-days", type=int, default=180)
    args = parser.parse_args()

    if args.stats:
        s = stats()
        print(f"Total companies seen: {s['total']}")
        print(f"Most recent:          {s['most_recent'] or 'never'}")
        print("Top industries:")
        for ind, count in list(s["industries"].items())[:10]:
            print(f"  {ind:30s} {count}")
    elif args.purge:
        n = purge(args.older_than_days)
        print(f"Purged {n} entries older than {args.older_than_days} days.")
    else:
        parser.print_help()
