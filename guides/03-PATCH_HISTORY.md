# Patch History — Mirae OpenClaw Zero-Token

> Complete record of all production fixes and feature additions.
> Source: `workspace/AGENTS.md` patch notes section.
> Last updated: 2026-04-24

## 10. Patch Notes

### 2026-04-21 (v9) — sg-outreach production hardening (round 2)

**Root cause:** After v8's deduplication/suppression foundation, the system still lacked domain throttling, retry logic, bounce detection, email threading, and deliverability monitoring.

**Fixes implemented:**

1. **Domain-level throttling** (`domain_throttle.py`)
   - 45-second minimum gap between sends to the same domain
   - Prevents triggering corporate spam filters (especially Gmail, Outlook)
   - Auto-waits and resumes without user intervention

2. **Retry logic with exponential backoff**
   - Temporary errors (rate limits, timeouts, 5xx) retry 3×: 5s → 15s → 60s
   - Permanent errors (invalid recipient, auth failure) fail immediately
   - Applied to both `workspace_smtp_sender.py` and `gmail_sender.py`

3. **Auto-backup before sending**
   - Before first live send, copies `sg_sequences_YYYYMMDD.csv` to `sg_sequences_YYYYMMDD_backup.csv`
   - Protects against accidental overwrites or crashes mid-send

4. **Email threading for follow-ups**
   - Follow-up emails (email #2, #3+) now include `In-Reply-To` and `References` headers
   - Points to the `message_id` of email #1
   - Follow-ups appear in the SAME thread in the recipient's inbox

5. **Bounce detection** (both reply trackers)
   - Searches inbox for "Delivery Status Notification" and "Mail Delivery Subsystem" messages
   - Parses the original recipient email from bounce body
   - Hard bounces → permanent suppression
   - Soft bounces → recorded as failed

6. **A/B subject line tracking**
   - `generate_sequences.py` now writes a `subject_variant` column
   - Format: `subj_1_of_3`, `subj_2_of_3`, etc.
   - Enables clean A/B comparison in reports

7. **Deliverability health report**
   - `outreach_history.py --deliverability-report`
   - Calculates bounce rate, reply rate, suppression rate, failure rate
   - Health score 0-100 with warnings:
     - Bounce >5% → "Clean your leads"
     - Unsubscribe >1% → "Subject/body too aggressive"
     - Failure >10% → "Check auth/connectivity"

**Production workflow updated in SKILL.md:**
`deduplicate → generate → dry-run → send → track replies + bounces → deliverability report`

Files changed:

- `skills/sg-outreach/scripts/domain_throttle.py` — new
- `skills/sg-outreach/scripts/workspace_smtp_sender.py` — throttle, retry, backup, threading
- `skills/sg-outreach/scripts/gmail_sender.py` — throttle, retry, backup, threading
- `skills/sg-outreach/scripts/workspace_imap_tracker.py` — bounce detection
- `skills/sg-outreach/scripts/outreach_tracker.py` — bounce detection
- `skills/sg-outreach/scripts/outreach_history.py` — deliverability report
- `skills/sg-outreach/scripts/generate_sequences.py` — A/B subject tracking
- `skills/sg-outreach/SKILL.md` — new sections for all features

---
