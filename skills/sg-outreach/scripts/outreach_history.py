#!/usr/bin/env python3
"""Global outreach history and suppression list for SG Outreach.

Prevents duplicate sends across campaigns by maintaining a central record
of every email address contacted, with status tracking (sent, replied,
unsubscribed, bounced).

History file: `.outreach_history.json` (in skill root)
"""

import fcntl
import json
import os
from datetime import datetime
from typing import Optional

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(SKILL_DIR, ".outreach_history.json")
_LOCK_FILE = HISTORY_FILE + ".lock"

# Statuses that permanently block further outreach
SUPPRESSION_STATUSES = {"unsubscribed", "bounced", "blacklisted"}


def _load_history() -> dict:
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _save_history(history: dict):
    """Atomic write: write to .tmp then rename so a crash never corrupts the file."""
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, default=str)
    os.replace(tmp, HISTORY_FILE)  # atomic on same filesystem


def get_history_entry(email: str) -> Optional[dict]:
    """Get full history record for an email address."""
    history = _load_history()
    return history.get(email.lower().strip())


def is_suppressed(email: str) -> tuple[bool, str]:
    """Check if email is on the suppression list.

    Returns: (is_suppressed, reason)
    """
    entry = get_history_entry(email)
    if not entry:
        return False, ""
    status = entry.get("status", "")
    if status in SUPPRESSION_STATUSES:
        return True, f"Suppressed: {status} (since {entry.get('last_sent_at', 'unknown')})"
    return False, ""


def was_already_sent(email: str, campaign: str = "") -> tuple[bool, str]:
    """Check if email was already sent in any campaign.

    Returns: (was_sent, reason)
    """
    entry = get_history_entry(email)
    if not entry:
        return False, ""
    status = entry.get("status", "")
    campaigns = entry.get("campaigns", [])

    # Only block if the email was actually sent or replied.
    # 'pending' means sequences were generated but not yet sent — allow it through.
    if status == "sent":
        if campaign and campaign in campaigns:
            return True, f"Already sent in this campaign ({campaign})"
        return True, f"Already sent on {entry.get('last_sent_at', 'unknown')} in {campaigns[-1] if campaigns else 'unknown'}"
    if status == "replied":
        return True, f"Already replied on {entry.get('last_sent_at', 'unknown')}"
    return False, ""


def record_contact(
    email: str,
    company_name: str = "",
    campaign: str = "",
    status: str = "pending",
    subject: str = "",
    sentiment: str = "",
):
    """Record or update a contact in the global history.

    Statuses: pending, sent, replied, unsubscribed, bounced, failed, blacklisted

    Uses an exclusive lock so concurrent pipeline runs don't overwrite each other's writes.
    """
    email = email.lower().strip()
    now = datetime.now().isoformat()

    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(_LOCK_FILE, "a") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            history = _load_history()

            if email not in history:
                history[email] = {
                    "company_name": company_name,
                    "first_sent_at": now,
                    "last_sent_at": now,
                    "campaigns": [campaign] if campaign else [],
                    "status": status,
                    "email_count": 1,
                    "last_subject": subject,
                    "reply_sentiment": sentiment,
                }
            else:
                entry = history[email]
                entry["last_sent_at"] = now
                entry["email_count"] = entry.get("email_count", 0) + 1
                if campaign and campaign not in entry["campaigns"]:
                    entry["campaigns"].append(campaign)
                if subject:
                    entry["last_subject"] = subject
                # Status upgrades: pending < sent < replied
                # Permanent statuses (unsubscribed, bounced, blacklisted) stick
                current = entry.get("status", "pending")
                if current not in SUPPRESSION_STATUSES:
                    if status in SUPPRESSION_STATUSES:
                        entry["status"] = status
                    elif status == "replied" and current != "replied":
                        entry["status"] = status
                        entry["reply_sentiment"] = sentiment
                    elif status == "sent" and current in ("pending", "failed"):
                        entry["status"] = status
                    elif status == "failed" and current == "pending":
                        entry["status"] = status
                if company_name:
                    entry["company_name"] = company_name

            _save_history(history)
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def suppress_email(email: str, reason: str = "unsubscribed"):
    """Permanently suppress an email address."""
    record_contact(email, status=reason)


def get_suppression_list() -> list[dict]:
    """Return all suppressed emails for export/reporting."""
    history = _load_history()
    return [
        {"email": email, **data}
        for email, data in history.items()
        if data.get("status") in SUPPRESSION_STATUSES
    ]


def get_stats() -> dict:
    """Return summary stats of the global history."""
    history = _load_history()
    total = len(history)
    suppressed = sum(1 for e in history.values() if e.get("status") in SUPPRESSION_STATUSES)
    sent = sum(1 for e in history.values() if e.get("status") == "sent")
    replied = sum(1 for e in history.values() if e.get("status") == "replied")
    pending = sum(1 for e in history.values() if e.get("status") == "pending")
    failed = sum(1 for e in history.values() if e.get("status") == "failed")
    bounced = sum(1 for e in history.values() if e.get("status") == "bounced")
    return {
        "total_contacts": total,
        "suppressed": suppressed,
        "sent": sent,
        "replied": replied,
        "pending": pending,
        "failed": failed,
        "bounced": bounced,
    }


def get_deliverability_report() -> dict:
    """Return a deliverability health report based on global history.

    Key metrics:
    - Bounce rate: should be <5%
    - Reply rate: benchmark 2-10% for cold email
    - Suppression rate: tracks opt-outs
    - Failure rate: temporary + permanent send failures
    """
    history = _load_history()
    if not history:
        return {"message": "No history yet."}

    total = len(history)
    sent = sum(1 for e in history.values() if e.get("status") == "sent")
    replied = sum(1 for e in history.values() if e.get("status") == "replied")
    bounced = sum(1 for e in history.values() if e.get("status") == "bounced")
    failed = sum(1 for e in history.values() if e.get("status") == "failed")
    suppressed = sum(1 for e in history.values() if e.get("status") in SUPPRESSION_STATUSES)

    total_attempted = sent + replied + bounced + failed + suppressed

    report = {
        "total_contacts": total,
        "total_attempted": total_attempted,
        "bounce_rate_pct": (bounced / total_attempted * 100) if total_attempted else 0,
        "reply_rate_pct": (replied / (sent + replied) * 100) if (sent + replied) else 0,
        "suppression_rate_pct": (suppressed / total_attempted * 100) if total_attempted else 0,
        "failure_rate_pct": (failed / total_attempted * 100) if total_attempted else 0,
        "health_score": 100,
        "warnings": [],
    }

    # Health scoring
    if report["bounce_rate_pct"] > 5:
        report["health_score"] -= 30
        report["warnings"].append("Bounce rate >5% — list quality issue. Clean your leads.")
    elif report["bounce_rate_pct"] > 2:
        report["health_score"] -= 10
        report["warnings"].append("Bounce rate >2% — monitor closely.")

    if report["suppression_rate_pct"] > 1:
        report["health_score"] -= 20
        report["warnings"].append("Unsubscribe rate >1% — subject/body may be too aggressive.")
    elif report["suppression_rate_pct"] > 0.3:
        report["health_score"] -= 5
        report["warnings"].append("Unsubscribe rate >0.3% — watch for spam complaints.")

    if report["failure_rate_pct"] > 10:
        report["health_score"] -= 15
        report["warnings"].append("Failure rate >10% — check auth and connectivity.")

    report["health_score"] = max(0, report["health_score"])
    return report


def scan_previous_campaigns(leads_dir: str = "") -> dict:
    """Scan all sg_sequences_*.csv files in leads/ and build/update history.

    Useful for initial migration or recovery.
    """
    import csv as _csv

    if not leads_dir:
        leads_dir = os.path.join(SKILL_DIR, "leads")
    if not os.path.exists(leads_dir):
        return {"scanned": 0, "updated": 0}

    updated = 0
    scanned = 0

    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(_LOCK_FILE, "a") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            history = _load_history()

            for fname in sorted(os.listdir(leads_dir)):
                if not fname.startswith("sg_sequences_") or not fname.endswith(".csv"):
                    continue
                path = os.path.join(leads_dir, fname)
                try:
                    with open(path, "r", encoding="utf-8-sig") as f:
                        rows = list(_csv.DictReader(f))
                    for row in rows:
                        email = row.get("to_email", "").lower().strip()
                        if not email:
                            continue
                        scanned += 1
                        status = row.get("status", "pending")
                        if status not in ("pending", "", None):
                            if email not in history:
                                history[email] = {
                                    "company_name": row.get("company_name", ""),
                                    "first_sent_at": row.get("sent_at", datetime.now().isoformat()),
                                    "last_sent_at": row.get("sent_at", datetime.now().isoformat()),
                                    "campaigns": [fname],
                                    "status": status,
                                    "email_count": 1,
                                    "last_subject": row.get("subject", ""),
                                    "reply_sentiment": row.get("reply_sentiment", ""),
                                }
                                updated += 1
                            else:
                                entry = history[email]
                                if fname not in entry.get("campaigns", []):
                                    entry["campaigns"].append(fname)
                                if status in SUPPRESSION_STATUSES:
                                    entry["status"] = status
                                elif status == "replied" and entry.get("status") != "replied":
                                    entry["status"] = "replied"
                                elif status == "sent" and entry.get("status") == "pending":
                                    entry["status"] = "sent"
                                entry["last_sent_at"] = row.get("sent_at", datetime.now().isoformat())
                                updated += 1
                except Exception:
                    continue

            _save_history(history)
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)

    return {"scanned": scanned, "updated": updated}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Global Outreach History Manager")
    parser.add_argument("--stats", action="store_true", help="Show history stats")
    parser.add_argument("--suppress", metavar="EMAIL", help="Suppress an email")
    parser.add_argument("--reason", default="blacklisted", help="Suppression reason")
    parser.add_argument("--scan-campaigns", action="store_true", help="Scan all sequence CSVs and rebuild history")
    parser.add_argument("--check", metavar="EMAIL", help="Check history for an email")
    parser.add_argument("--deliverability-report", action="store_true", help="Generate deliverability health report")
    args = parser.parse_args()

    if args.stats:
        stats = get_stats()
        for k, v in stats.items():
            print(f"{k}: {v}")

    if args.suppress:
        suppress_email(args.suppress, args.reason)
        print(f"Suppressed: {args.suppress} ({args.reason})")

    if args.check:
        entry = get_history_entry(args.check)
        if entry:
            print(json.dumps(entry, indent=2))
        else:
            print("No history found.")

    if args.scan_campaigns:
        result = scan_previous_campaigns()
        print(f"Scanned {result['scanned']} rows, updated {result['updated']} history entries.")

    if args.deliverability_report:
        report = get_deliverability_report()
        print("\n📊 DELIVERABILITY REPORT")
        print("-" * 40)
        for k, v in report.items():
            if k == "warnings":
                if v:
                    print(f"\n⚠️  WARNINGS:")
                    for w in v:
                        print(f"   - {w}")
                else:
                    print("\n✅ No warnings. Deliverability looks healthy.")
            else:
                if isinstance(v, float):
                    print(f"  {k}: {v:.2f}")
                else:
                    print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
