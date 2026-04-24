---
name: sg-outreach
description: "Personalized email sequence generator and sender for SG B2B leads.
  Generates 3-7 email sequences based on lead tier (Hot/Warm/Cold), with actual
  high-converting cold email copy optimized using Gong.io (25M+ emails), Josh Braun,
  and Alex Berman data. Sends via Gmail API (OAuth2) OR Google Workspace SMTP (App Password).
  Includes reply tracking, performance reports, domain warmup, and lead deduplication.
  Use when user says: generate email sequences, send outreach emails, cold email campaign,
  sg-outreach, create email campaign, send to leads, check replies, outreach report,
  check gmail auth, mednefits outreach, workspace smtp, google workspace email."
metadata:
  {
    "openclaw": {
      "emoji": "📧",
      "requires": { "bins": ["python3", "pip"] }
    }
  }
---

# SG Outreach — Email Sequences + Gmail/Workspace Sender

## CRITICAL FILE PATHS (use these EXACT paths — do NOT guess)

| File | Absolute Path | Purpose |
|------|---------------|---------|
| Gmail sender (OAuth2) | `/root/openclaw-zero-token/skills/sg-outreach/scripts/gmail_sender.py` | Main email sender (Gmail API) |
| Workspace SMTP sender | `/root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_smtp_sender.py` | Never-expire SMTP sender (Google Workspace) |
| Workspace IMAP tracker | `/root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_imap_tracker.py` | Never-expire reply tracker (Google Workspace) |
| Sequence generator | `/root/openclaw-zero-token/skills/sg-outreach/scripts/generate_sequences.py` | Generates email sequences |
| Outreach tracker (OAuth) | `/root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_tracker.py` | Reply/bounce tracker (Gmail API) |
| Saleshandy export | `/root/openclaw-zero-token/skills/sg-outreach/scripts/export_saleshandy.py` | CSV export for Saleshandy |
| Domain warmup | `/root/openclaw-zero-token/skills/sg-outreach/scripts/domain_warmup.py` | Gradual send ramp (new accounts) |
| Deliverability check | `/root/openclaw-zero-token/skills/sg-outreach/scripts/deliverability_check.py` | SPF/DKIM/DMARC validator |
| Reply classifier | `/root/openclaw-zero-token/skills/sg-outreach/scripts/reply_classifier.py` | Classifies replies (positive/negative/OOO) |
| Lead deduplicator | `/root/openclaw-zero-token/skills/sg-outreach/scripts/lead_deduplicator.py` | Cross-campaign dedup |
| Email templates | `/root/openclaw-zero-token/skills/sg-outreach/references/sequence_templates.py` | Financing variant only |
| Sequence validator | `/root/openclaw-zero-token/skills/sg-outreach/scripts/validate_sequences.py` | Pre-send placeholder + sender check |
| Deliverability check | `/root/openclaw-zero-token/skills/sg-outreach/scripts/deliverability_check.py` | SPF/DKIM/DMARC/MX validator |
| Dependencies | `/root/openclaw-zero-token/skills/sg-outreach/requirements.txt` | Python pip packages |
| Lead input/output | `/root/openclaw-zero-token/skills/sg-outreach/leads/` | CSV input and generated sequences |
| OAuth credentials | `/root/openclaw-zero-token/skills/sg-outreach/credentials/client_secret.json` | Google OAuth2 Desktop client |
| Token cache | `/root/openclaw-zero-token/skills/sg-outreach/.gmail_token.json` | OAuth access + refresh token |
| SMTP config | `/root/openclaw-zero-token/skills/sg-outreach/.workspace_smtp_config.json` | Workspace SMTP/IMAP credentials (NEVER expires) |
| Auth status (OAuth) | `/root/openclaw-zero-token/skills/sg-outreach/.auth_status.json` | Last OAuth auth check result |
| Auth status (SMTP) | `/root/openclaw-zero-token/skills/sg-outreach/.workspace_auth_status.json` | Last SMTP auth check result |
| Compliance config | `/root/.openclaw/workspace/compliance/COMPLIANCE.json` | PDPA/SCA compliance footer data (REQUIRED before sending) |

**DO NOT look for these files — they DO NOT EXIST:**
- `gmail_sender.py` at root (WRONG — it's at `scripts/gmail_sender.py`)
- `credentials.json` at root (WRONG — it's at `credentials/client_secret.json`)
- `app_password.txt` (WRONG — store it inside `.workspace_smtp_config.json`)

## Install Dependencies

```bash
pip install -r /root/openclaw-zero-token/skills/sg-outreach/requirements.txt
```

---

## 🔐 Choose Your Auth Method

| Method | Best For | Expiry | Bot Intervention Required |
|--------|----------|--------|--------------------------|
| **OAuth2** (`gmail_sender.py`) | Personal Gmail (`arvion.sg@gmail.com`) | **7 days** if Google Cloud app is in Testing mode | Yes — Telegram re-auth flow |
| **SMTP + App Password** (`workspace_smtp_sender.py`) | Google Workspace (`admin@miraeadvisory.com`) | **Never** (unless revoked) | No — fully autonomous |

**Recommendation for production / zero-token OpenClaw:**
Use **SMTP + App Password** for the Workspace account. It requires zero human intervention, works forever, and never breaks at 2 AM because a token expired.

---

## 📋 Compliance Footer (PDPA / SCA)

**No hard block.** The sender auto-appends a footer from whatever fields are present in COMPLIANCE.json. Empty fields are silently omitted. The sender will always send if auth is OK.

Current config: `/root/.openclaw/workspace/compliance/COMPLIANCE.json`
```json
{
  "company_name": "Mirae Advisory",
  "physical_address": "One Raffles Place Mall, #02-01, Singapore 048616",
  "contact_email": "admin@miraeadvisory.com",
  "phone": "+65 8856 0414",
  "uen": ""
}
```

**What happens automatically:**
- Footer appended to every email: company name + physical address + `Unsubscribe: mailto:contact_email?subject=Unsubscribe`
- **Suppression check still runs** before every send (`is_suppressed()`) — opted-out recipients are always skipped
- Post-send logging (`record_contact()`) always runs regardless of footer state

---

## 🔐 Workspace SMTP (Never Expire) — RECOMMENDED

### Step 1: Generate an App Password in Google

1. Enable **2-Step Verification** on the Google Workspace account:
   https://myaccount.google.com/signinoptions/two-step-verification

2. Generate an **App Password**:
   https://myaccount.google.com/apppasswords
   - Select app: **Mail**
   - Select device: **Other (Custom name)** → type `OpenClaw-SG-Outreach`
   - Click **Generate**
   - Google will show a 16-character password like `abcd efgh ijkl mnop`
   - **Copy it immediately** — Google shows it only once

3. **Never use your regular Google password** in SMTP. Only the App Password works.

### Step 2: Create the Config File

Create `/root/openclaw-zero-token/skills/sg-outreach/.workspace_smtp_config.json`:

```json
{
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 465,
  "imap_host": "imap.gmail.com",
  "imap_port": 993,
  "email": "admin@miraeadvisory.com",
  "app_password": "abcd efgh ijkl mnop"
}
```

Replace `app_password` with the actual 16-char code from Google.

### Step 3: Verify It Works

```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_smtp_sender.py --check-auth
```

Expected output: `Auth OK — admin@miraeadvisory.com (SMTP)`

### Step 4: Send Emails (NEVER Compose Copy Yourself)

**CRITICAL RULE:** The bot must NEVER write its own email subject or body. All emails MUST come from `generate_sequences.py` using the financing template. This prevents spammy AI-generated copy that triggers filters and looks unprofessional.

**For a single recipient, create a mini-sequence first:**

Step 1 — Use the `write` tool to create the CSV (avoid heredocs in exec — they confuse JSON formatting):
```json
{"tool":"write","parameters":{"path":"/tmp/mini_lead.csv","content":"company_name,email,lead_score_v2,decision_maker_name,industry,area\nTarget Company,contact@example.com,60,John Doe,Construction,Singapore"}}
```

Step 2 — Generate sequences (use `--single` for one-off sends, no follow-ups):
```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/generate_sequences.py /tmp/mini_lead.csv --sender-name "<USER_PROVIDED_NAME>" --single --output /tmp/mini_sequences.csv
```
**Always use the sender name the user provided. Never hardcode a name.**

Step 3 — Validate:
```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/validate_sequences.py --sequences /tmp/mini_sequences.csv
```

Step 4 — Send (dry run first, then live):
```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_smtp_sender.py --sequences /tmp/mini_sequences.csv --dry-run
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_smtp_sender.py --sequences /tmp/mini_sequences.csv --daily-limit 450
```

**Sequences (dry run first):**
```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_smtp_sender.py \
  --sequences leads/sg_sequences_20260420.csv \
  --dry-run
```

**Sequences (live send):**
```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_smtp_sender.py \
  --sequences leads/sg_sequences_20260420.csv \
  --daily-limit 450
```

### Step 5: Reply Tracking (IMAP — Also Never Expires)

```bash
# Check for replies
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_imap_tracker.py \
  --sequences leads/sg_sequences_20260420.csv

# Check + generate report
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_imap_tracker.py \
  --sequences leads/sg_sequences_20260420.csv --report
```

---

## ⚠️ AUTH FAILURE RECOVERY — TELEGRAM FLOW (OAuth2 only)

**When you see `AUTH_FAILED` or `invalid_grant` from `gmail_sender.py`, do this EXACTLY:**

1. Generate a new auth URL:
```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/gmail_sender.py --generate-auth-url
```

2. Send the user this message in Telegram:
```
Gmail auth expired. Click this link to reconnect:
<the URL from step 1>

After clicking Allow, copy the code shown on the page and paste it here.
```

3. When the user pastes the code, run:
```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/gmail_sender.py --exchange-code "<the code they sent>"
```

4. Check the output. If it says `SUCCESS: Authenticated as arvion.sg@gmail.com` → confirm to user. If it fails → report the exact error.

**Never tell the user to SSH in or run Python manually. These commands handle everything.**

## Check Auth Status (OAuth2)

```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/gmail_sender.py --check-auth
```

Output:
- `Auth OK — arvion.sg@gmail.com` → all good
- `AUTH_FAILED: ...` → run the recovery flow above

## How to Send a Single One-Off Email (OAuth2)

**NEVER compose subject/body yourself.** Use the mini-sequence workflow above. If you absolutely must use `--to` (not recommended), the subject and body must be copied EXACTLY from a generated sequences CSV — never AI-generated.

```bash
# WRONG — bot writing its own copy. NEVER do this.
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/gmail_sender.py \
  --to "recipient@example.com" \
  --subject "Quick question about design financing" \
  --body "I noticed your design work..." \
  --sender-name "Vincent"

# CORRECT — use sequences from generate_sequences.py
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/gmail_sender.py \
  --sequences /tmp/mini_sequences.csv --daily-limit 450
```

---

## Financing Variant (Lender Comparison)

For business financing / SME loan comparison campaigns:

**2 subjects that rotate across leads:**
1. `"Need Business Financing? We Compare Lenders So You Don't Have To"`
2. `"Tired of Bank Rejections? We Find the Right Financing for You"`

**Email #1 body:**
Problem → Credibility → Soft CTA (~80 words)
- Problem: Weeks wasted comparing lenders, bank rejections, bad rates
- Credibility: 15+ lenders compared, no fees, no credit impact
- CTA: "Worth a 5-minute call to see what you qualify for?"

**Email #2 follow-up (auto-used when variant=financing):**
Case study angle — a similar business got 1.2% lower rate through an alternative lender.

**How to use:**
```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/generate_sequences.py \
  leads/sg_leads_enriched.csv \
  --sender-name "<USER_PROVIDED_NAME>"
```
**Replace `<USER_PROVIDED_NAME>` with the exact name the user provided. Do NOT hardcode names. The other fields (title, company, email) use defaults automatically.**

Set `variant=financing_variant` in your leads CSV to trigger this template.

## Validate Sequences Before Sending

Always validate before dry-run or live send:

```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/validate_sequences.py \
  --sequences /root/openclaw-zero-token/skills/sg-outreach/leads/sg_sequences_20260421.csv
```

Checks performed:
- `sender_name` is not empty
- `sender_email` is not empty
- No unfilled `{{placeholders}}` remain in subject or body
- No empty subjects or bodies
- No empty recipient emails

Exit code `0` = safe to send. Exit code `1` = fix errors first.

## 🚨 MANDATORY SENDER PROMPT — ASK USER FOR NAME ONLY

**Before running `generate_sequences.py` or ANY sender, the bot MUST ask the user for `sender_name` via Telegram.**

### Why this is mandatory
- `generate_sequences.py` requires `--sender-name`
- If empty, emails will have no signature (looks unprofessional)
- The bot must NEVER guess the sender name from context, previous chats, or hardcode "Wei Xian"
- The user decides who the email appears to come from

### Hardcoded defaults (do NOT ask user for these)
| Field | Default Value | Why |
|-------|--------------|-----|
| `sender_email` | *(empty — sender script uses config file)* | Same account always |
| `sender_title` | `"Business Development"` | Always the same |
| `sender_company` | `"Mirae Advisory"` | Always the same |

### What to ask (exact Telegram message)
```
Before I generate the outreach sequences, what sender name should I use?
(e.g. "Wei Xian")
```

### How to capture the reply and proceed
1. Send the message above
2. Wait for the user's reply
3. Extract the person name from their reply
4. If the reply does not contain a clear person name, ask again: "Please provide a sender name (e.g. 'Alex Tan')."
5. Once you have the name, run `generate_sequences.py` with ONLY `--sender-name "<name>"`

### WRONG (do NOT do this)
- Guessing: "I'll use Wei Xian as the sender name" — **NEVER assume**
- Hardcoding: `--sender-name "Wei Xian"` in a command without asking
- Asking for email/title/company — these are always the same, do NOT ask
- Skipping: generating sequences without `--sender-name` and hoping it works

### CORRECT workflow
```
Bot:  "Before I generate the outreach sequences, what sender name should I use?"
User: "Use Alex Tan"
Bot:  [reads SKILL.md, creates mini CSV, runs generate_sequences.py --sender-name "Alex Tan" --single, validates, sends]
```

---

## Production Workflow (Recommended Order)

```
1. Ask sender    → Bot asks user for sender_name ONLY (title/company/email use defaults)
2. Deduplicate   → lead_deduplicator.py (removes already-contacted leads)
3. Generate      → generate_sequences.py (creates sequences with history check)
4. Validate      → validate_sequences.py (checks for empty placeholders BEFORE sending)
5. Dry run       → sender --dry-run (preview without sending)
6. Send          → sender --sequences (live send with history protection)
7. Track replies → workspace_imap_tracker.py (updates + auto-suppresses)
8. Report        → workspace_imap_tracker.py --report
```

**Critical:** Always run `lead_deduplicator.py` before `generate_sequences.py`. The generator also has a built-in history check, but deduplication at the source keeps your sequences cleaner.

### Validation step (NEW — always run before sending)
```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/validate_sequences.py \
  --sequences /root/openclaw-zero-token/skills/sg-outreach/leads/sg_sequences_20260421.csv
```

**If validation fails:**
- `sender_name is EMPTY` → go back to "Ask sender" step
- `Unfilled placeholders` → regenerate sequences with correct --sender-name

**Only proceed to dry-run/live-send if validation returns `All clear. Safe to send.`**

## Quick Start — Generate Sequences

**AFTER asking the user for sender details, run:**

```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/generate_sequences.py \
  /path/to/enriched_leads.csv \
  --sender-name "<USER_REPLY_NAME>"
```

**With history check and campaign name:**
```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/generate_sequences.py \
  /path/to/enriched_leads.csv \
  --sender-name "<USER_REPLY_NAME>" \
  --campaign-name "construction_apr_2026"
```

**Replace `<USER_REPLY_NAME>` with the exact name the user provided. Do NOT hardcode names. The other fields (title, company, email) use defaults automatically.**

### Input CSV Format (enriched_leads.csv)

Required columns:
| Column | Example | Purpose |
|--------|---------|---------|
| `company_name` | "Acme Pte Ltd" | Company name |
| `email` or `Email` or `EMAIL` | "john@acme.com" | Recipient email |
| `lead_score_v2` (or `lead_score`) | 85 | Determines tier (A/B/C) |
| `decision_maker_name` | "John Tan" | Personalization |
| `industry` | "Fintech" | Industry context |
| `area` | "Singapore" | Geographic context |
| `personalization_hook` | "Raised $2M seed round" | Opening line data |

Optional signal columns (for variant selection):
| Column | Example | Triggers |
|--------|---------|----------|
| `hiring_signals` | "Senior SDR role" | Hiring variant |
| `recent_tender` | true/false | Tender variant |
| `tender_value` | "$500K" | Tender variant value |
| `news_signal` | "Opened new office" | News variant |
| `tech_stack` | "Salesforce" | Tech variant |
| `variant` | "mednefits_variant" | Force a specific template variant |
| `variant` | "financing_variant" | Business financing / lender comparison variant |
| `whatsapp_number` | "+6591234567" | Multi-channel |
| `outreach_channel` | "email" or "whatsapp" | Channel routing |
| `booking_link` | "https://cal.com/wei" | Used by mednefits_variant |

### Output CSV (leads/sg_sequences_YYYYMMDD.csv)

Generated with one row per email (a 5-email sequence = 5 rows per lead):
| Column | Populated by |
|--------|-------------|
| `lead_id` | generate_sequences.py (MD5 hash) |
| `company_name`, `to_email`, `to_name` | Input CSV |
| `subject`, `body` | Template + fill |
| `send_delay_days`, `email_number` | Tier config |
| `sequence_tier`, `template_variant`, `spam_warnings` | Generation |
| `sender_name`, `sender_email` | CLI args (used by sender scripts) |
| `status`, `sent_at`, `thread_id` | gmail_sender.py / workspace_smtp_sender.py |
| `replied`, `replied_at`, `status` | outreach_tracker.py / workspace_imap_tracker.py |

## Sequence Tiers (Optimized with Gong/Braun/Berman data)

| Tier | Score | Emails | Gap | Strategy |
|------|-------|--------|-----|----------|
| A (Aggressive) | 80+ | 3 | 3 days | Problem → Insight → Soft ask |
| B (Nurture) | 45-79 | 5 | 4 days | Problem → Data → Proof → Timing → Breakup |
| C (Slow Burn) | 20-44 | 7 | 5 days | Observation → Insight → Proof → Objection → Angle → Resource → Breakup |

**Template optimizations applied (2026-04-08):**
- Zero product/service pitching in cold tiers (Gong: mentioning solution = -57% replies)
- All cold emails ≤100 words (Gong: 3-4 sentences optimal)
- Subject lines 2-5 words, no buzzwords (Gong: long subjects = -17.9% opens)
- Interest-based CTAs: "Worth exploring?" not "Can we book Tuesday?" (Braun: 2x replies)
- Cold reading openings: "I noticed...", "Looks like..." (Saraev)

## Reply Tracking

### Option A: IMAP (Never Expire — Recommended)
```bash
# Check for replies (looks back 30 days by default)
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_imap_tracker.py \
  --sequences leads/sg_sequences_20260408.csv

# Generate performance report
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_imap_tracker.py \
  --sequences leads/sg_sequences_20260408.csv --report
```

### Option B: Gmail API (OAuth2 — Requires periodic re-auth)
```bash
# Check for replies
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_tracker.py \
  --sequences leads/sg_sequences_20260408.csv

# Generate performance report
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_tracker.py \
  --sequences leads/sg_sequences_20260408.csv --report
```

## Domain Warmup (New Sending Accounts)

For new Gmail/Workspace accounts, DO NOT send 450/day immediately. Use the warmup script:

```bash
python3 scripts/domain_warmup.py --check  # Current status
python3 scripts/domain_warmup.py --start   # Begin warmup
```

| Week | Max sends/day | Notes |
|------|--------------|-------|
| 1-2 | 10-20 | Very conservative |
| 3-4 | 30-50 | Gradual increase |
| 5-6 | 50-100 | Approaching normal |
| 7+ | 100-150 | Full capacity for single account |

## Deliverability Check

```bash
python3 scripts/deliverability_check.py
# Checks: SPF, DKIM, DMARC, token health, spam score
```

## Lead Deduplication & Global Suppression List

The system maintains a **global outreach history** (`.outreach_history.json`) that tracks every email address ever contacted, with statuses:
- `pending` — sequence generated but not yet sent
- `sent` — email was sent
- `replied` — prospect replied
- `unsubscribed` — prospect opted out (permanently blocked)
- `bounced` — email bounced (permanently blocked)
- `failed` — send failed
- `blacklisted` — manually suppressed

**Suppression is automatic.** When a prospect replies "unsubscribe" or "stop", or when a negative reply is detected, their email is permanently added to the suppression list. Future campaigns will skip them automatically.

### Deduplicate before generating sequences

```bash
# Remove leads already contacted in ANY previous campaign
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/lead_deduplicator.py \
  --input /root/.openclaw/workspace/leads/sg_leads_enriched.csv \
  --output /root/.openclaw/workspace/leads/sg_leads_deduped.csv
```

Checks against:
1. All previous `sg_sequences_*.csv` files in `leads/`
2. Global outreach history (`.outreach_history.json`)
3. Suppression list (unsubscribed / bounced / blacklisted)

```bash
# Compare against a specific previous campaign only
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/lead_deduplicator.py \
  --input /root/.openclaw/workspace/leads/sg_leads_enriched.csv \
  --previous /root/openclaw-zero-token/skills/sg-outreach/leads/sg_sequences_20260401.csv \
  --output /root/.openclaw/workspace/leads/sg_leads_deduped.csv
```

### History management commands

```bash
# Show history stats
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_history.py --stats

# Check a specific email
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_history.py --check prospect@example.com

# Manually suppress an email
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_history.py --suppress prospect@example.com --reason blacklisted

# Rebuild history from all past sequence CSVs (useful after migration)
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_history.py --scan-campaigns
```

## Saleshandy Export

```bash
python3 scripts/export_saleshandy.py leads/sg_sequences_20260408.csv
# Outputs: leads/sg_saleshandy_export_20260408.csv
```

## Deliverability Rules

1. **Plain text only** — no HTML
2. **Max 450/day** — personal Gmail API limit (100-150/day recommended)
3. **2-3 second delay** — random between sends
4. **Auto-unsubscribe** — removes anyone who replies "unsubscribe" (adds to global suppression list)
5. **SPF/DKIM/DMARC** — must be configured (check with deliverability_check.py)
6. **Domain warmup** — gradual ramp for new accounts (see warmup schedule)
7. **No spam words** — 16-word list checked automatically during generation
8. **Duplicate protection** — global history prevents re-sending to same email across campaigns
9. **Suppression list** — unsubscribed/bounced emails are permanently blocked from all future campaigns
10. **Domain throttling** — 45-second minimum gap between sends to the same domain (prevents spam-filter triggering)
11. **Auto-backup** — sequences CSV is auto-backed up before first live send
12. **Email threading** — follow-ups include `In-Reply-To` header referencing email #1
13. **Retry logic** — temporary errors (rate limits, timeouts) retry 3× with 5s/15s/60s backoff
14. **Bounce detection** — hard bounces are auto-detected and permanently suppressed
15. **A/B subject tracking** — `subject_variant` column records which subject rotation was used

## State Management

| File | Purpose |
|------|---------|
| `.outreach_state.json` | Daily send counter, campaign start date. Resets at midnight. |
| `.warmup_state.json` | Domain warmup progress (current week, daily count). |
| `.gmail_token.json` | OAuth2 access + refresh token. Auto-refreshes while valid. |
| `.auth_status.json` | Last OAuth auth check result. Bot reads this to alert on failures. |
| `.workspace_smtp_config.json` | Workspace SMTP/IMAP credentials. Never expires. |
| `.workspace_auth_status.json` | Last SMTP auth check result. |

## Domain Throttling

Sending too many emails to the same domain in quick succession triggers spam filters. The system automatically enforces a **45-second minimum gap** between sends to the same domain.

If throttling is active, you'll see:
```
Domain throttle: waiting 23s for gmail.com
```

To adjust the delay, edit `scripts/domain_throttle.py`:
```python
DEFAULT_MIN_DELAY = 45  # seconds
```

## Retry Logic

Temporary failures automatically retry with exponential backoff:
- Attempt 1 fails → wait 5 seconds → retry
- Attempt 2 fails → wait 15 seconds → retry
- Attempt 3 fails → wait 60 seconds → retry
- Still failing → mark as `failed`

**Permanent failures** (invalid recipient, auth error) fail immediately without retry.

## Bounce Detection

Both reply trackers (`outreach_tracker.py` for Gmail API, `workspace_imap_tracker.py` for IMAP) automatically detect bounce notifications after sending.

**Hard bounces** (mailbox doesn't exist, domain invalid) → permanently suppressed
**Soft bounces** (mailbox full, temporary failure) → recorded as `failed`

Run bounce detection manually:
```bash
# After sending, check for bounces
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_imap_tracker.py \
  --sequences leads/sg_sequences_20260421.csv
```

## Deliverability Monitoring

Generate a health report anytime:
```bash
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_history.py --deliverability-report
```

**Report metrics:**
- Bounce rate (warning if >5%)
- Reply rate (benchmark: 2-10% for cold email)
- Suppression/unsubscribe rate (warning if >1%)
- Failure rate (warning if >10%)
- Health score (0-100)

**Recommended schedule:** Run `--deliverability-report` weekly.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `AUTH_FAILED: Gmail not authenticated` (OAuth) | Run `--generate-auth-url`, send link to user, then `--exchange-code <code>` |
| `AUTH_FAILED: Token has been expired or revoked` (OAuth) | Same as above — full OAuth re-auth required |
| `AUTH_FAILED: email or app_password missing` (SMTP) | Create `.workspace_smtp_config.json` with correct credentials |
| `AUTH_FAILED: SMTP auth error` (SMTP) | Ensure 2-Step Verification is ON and you are using an App Password, not your regular password |
| `ModuleNotFoundError: No module named 'google.auth'` | Run `pip install -r requirements.txt` |
| `Quota exceeded` | Daily 500-email Gmail API limit hit. Wait until midnight SGT. |
| `Error: Sequences file not found` | Run `generate_sequences.py` first, or check `leads/` directory |
| Email 2 fires too early | Fixed 2026-04-08 — delay now anchors to Email 1's actual sent_at |
| No replies despite high opens | Check CTA — should be interest-based ("Worth exploring?"), not time-based |
| Emails going to spam | Run `deliverability_check.py` — likely missing SPF/DKIM/DMARC |
| Skipped (dup) count is high | These leads were already contacted. Run `lead_deduplicator.py` first next time. |
| Domain throttle keeps waiting | Normal — protects sender reputation. Reduce batch size or increase delay. |
