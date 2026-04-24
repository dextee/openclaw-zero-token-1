#!/usr/bin/env python3
"""Domain-level send throttling for SG Outreach.

Prevents sending too many emails to the same domain in quick succession,
which triggers spam filters. Maintains a simple in-memory and on-disk log
of last send time per domain.

Usage:
    from domain_throttle import DomainThrottle
    throttle = DomainThrottle(min_delay_seconds=60)
    if throttle.can_send("example.com"):
        throttle.record_send("example.com")
    else:
        wait_time = throttle.time_until_next("example.com")
        time.sleep(wait_time)
"""

import json
import os
import time
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THROTTLE_FILE = os.path.join(SKILL_DIR, ".domain_throttle.json")

DEFAULT_MIN_DELAY = 45  # seconds between sends to same domain


class DomainThrottle:
    def __init__(self, min_delay_seconds: int = DEFAULT_MIN_DELAY):
        self.min_delay = min_delay_seconds
        self._log = self._load()

    def _load(self) -> dict:
        if os.path.exists(THROTTLE_FILE):
            try:
                with open(THROTTLE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save(self):
        os.makedirs(os.path.dirname(THROTTLE_FILE), exist_ok=True)
        with open(THROTTLE_FILE, "w", encoding="utf-8") as f:
            json.dump(self._log, f, indent=2)

    def can_send(self, domain: str) -> bool:
        domain = domain.lower().strip()
        last_sent = self._log.get(domain)
        if not last_sent:
            return True
        elapsed = time.time() - last_sent
        return elapsed >= self.min_delay

    def time_until_next(self, domain: str) -> float:
        domain = domain.lower().strip()
        last_sent = self._log.get(domain)
        if not last_sent:
            return 0.0
        remaining = self.min_delay - (time.time() - last_sent)
        return max(0.0, remaining)

    def record_send(self, domain: str):
        domain = domain.lower().strip()
        self._log[domain] = time.time()
        self._save()

    def wait_if_needed(self, domain: str):
        if not self.can_send(domain):
            wait_sec = self.time_until_next(domain)
            if wait_sec > 0:
                time.sleep(wait_sec)
        self.record_send(domain)

    def reset(self):
        self._log = {}
        self._save()


def extract_domain(email: str) -> str:
    """Extract domain from email address."""
    if "@" in email:
        return email.split("@")[-1].lower().strip()
    return ""
