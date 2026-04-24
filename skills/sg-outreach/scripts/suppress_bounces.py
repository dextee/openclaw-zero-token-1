#!/usr/bin/env python3
"""Post-run bounce suppression parser.

Reads last_run.log, extracts emails with permanent SMTP failures,
and adds them to the global suppression list.

Usage:
    python3 suppress_bounces.py --log /path/to/last_run.log --user-id <chat_id>
"""

import argparse
import os
import re
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
import outreach_history as oh

# ANSI escape sequence stripper
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Permanent-failure keywords (case-insensitive)
_PERMANENT_REASONS = [
    "recipient refused",
    "sender refused",
    "550",
    "551",
    "552",
    "553",
    "554",
    "mailbox",
    "does not exist",
    "invalid address",
    "user unknown",
]


def is_permanent_failure(reason: str) -> bool:
    lowered = reason.lower()
    return any(k in lowered for k in _PERMANENT_REASONS)


def parse_log(log_path: str) -> list[tuple[str, str]]:
    """Return list of (email, reason) for permanent failures."""
    if not os.path.exists(log_path):
        return []
    bounces = []
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            clean = _ANSI_RE.sub("", line)
            # Match: "Failed #N to email@domain: failed: reason"
            m = re.search(r"Failed\s+#?\d+\s+to\s+([^\s:]+):\s*failed:\s*(.+)", clean)
            if m:
                email = m.group(1).strip()
                reason = m.group(2).strip()
                if is_permanent_failure(reason):
                    bounces.append((email, reason))
    return bounces


def main():
    parser = argparse.ArgumentParser(description="Suppress bounced emails")
    parser.add_argument("--log", required=True, help="Path to last_run.log")
    parser.add_argument("--user-id", default="", help="User chat ID (for logging)")
    args = parser.parse_args()

    bounces = parse_log(args.log)
    if not bounces:
        print("No permanent bounces found.")
        return

    suppressed = 0
    for email, reason in bounces:
        oh.record_contact(email=email, status="bounced")
        suppressed += 1
        print(f"Suppressed: {email} — {reason}")

    print(f"Total suppressed: {suppressed}")


if __name__ == "__main__":
    main()
