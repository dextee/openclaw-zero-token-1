---
name: sg-verify
description: "Email verification pipeline for Singapore B2B leads. Zero-cost — no paid APIs, no credits. Uses DNS MX lookup + SMTP RCPT TO handshake to confirm mailbox existence without sending any email. Generates email patterns (info@, sales@, enquiry@) for leads missing email addresses. Detects catch-all domains, Google/Microsoft providers, and port-25 blocking. Use when user says: verify emails, check email list, clean leads, validate emails, email verification, sg-verify, run verify on CSV, check which emails are valid."
metadata:
  {
    "openclaw": {
      "emoji": "✉️",
      "requires": { "bins": ["python3", "pip"] }
    }
  }
---

# SG Email Verifier — Zero-Cost Pipeline

Verifies emails via DNS + SMTP handshake. No APIs. No credits.
Input: any CSV with email/website columns.
Output: same CSV + 6 new columns (email_verified, email_confidence, etc.)

## Prerequisites

Install once:
```bash
pip install dnspython tqdm colorama
```

Script location: `/root/openclaw-zero-token/skills/sg-verify/scripts/verify_emails.py`

## Command Triggers

| User says | Action |
|---|---|
| "verify emails in [file]" | Run full pipeline on file |
| "clean the lead list" | Run on default sg_leads_raw.csv |
| "check which emails are valid" | Run + filter to verified only |
| "generate email patterns for leads" | Run with --skip-catchall-smtp flag |
| "sg-verify status" | Show last run summary from log |

## ⚡ EXECUTION ORDER FOR DEEPSEEK V4 — CRITICAL

**`process` does NOT exist on the DeepSeek V4 web bridge. DO NOT use `"background":true` in exec JSON.**

`background:true` immediately returns "use process to poll" — since `process` is unavailable, the model can never retrieve the output.

`backgroundMs` in config is set to **270s**. Any exec finishing before 270s returns output directly. With batches of 5–10 leads (15–60s each), all batches complete well within the 270s window — output comes back directly, no polling needed.

### Batch Size Limits — Deep Verification Standard

**Recommended: 5 per batch (deep mode)** — lower concurrency, more accurate pattern generation, better SMTP handshake reliability.
**Fast mode: 10 per batch** — still safe, but slightly less thorough.
**Absolute max: 10 per batch.** Never exceed 10. The user experience degrades and SMTP accuracy drops.

| File Size | Deep Mode (5/batch) | Fast Mode (10/batch) | Duration |
|-----------|---------------------|----------------------|----------|
| ≤5 leads | 1 batch | 1 batch | ~15-30s |
| 6-10 leads | 2 batches | 1 batch | ~30-60s |
| 11-25 leads | 5 batches | 3 batches | ~2-3 min total |
| 26-50 leads | 10 batches | 5 batches | ~4-5 min total |

**For files >10 leads, ALWAYS chunk. Use the slicing helper to create temp CSVs per batch, verify each, then merge.**

### Batch slicing helper (creates temp files for chunking)

```tool_json
{"tool":"exec","parameters":{"command":"python3 -c \"\nimport csv, os\ninput_file = '/root/.openclaw/workspace/leads/[INPUT].csv'\nbatch_size = 5  # or 10 for fast mode\nwith open(input_file, encoding='utf-8-sig') as f:\n    rows = list(csv.DictReader(f))\nheader = rows[0].keys() if rows else []\nfor i in range(0, len(rows), batch_size):\n    batch = rows[i:i+batch_size]\n    out = input_file.replace('.csv', f'_verify_batch{i//batch_size + 1}.csv')\n    with open(out, 'w', newline='', encoding='utf-8-sig') as fh:\n        w = csv.DictWriter(fh, fieldnames=header)\n        w.writeheader()\n        w.writerows(batch)\n    print(f'Batch {i//batch_size + 1}: {len(batch)} leads -> {out}')\n\" 2>&1"}}
```

### Step 1 — Send start notification FIRST (before exec):
```
✉️ Email verification started for [N] leads...
⏱️ Mode: [Deep / Fast] | Batch size: [5 or 10] | Batches: [Y]
⏳ Running batch 1/[Y] now — will notify you when done.
```

### Step 2 — Run verification (blocking exec — result returns directly):

```tool_json
{"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-verify/scripts/verify_emails.py /root/.openclaw/workspace/leads/[INPUT_FILENAME].csv --output /root/.openclaw/workspace/leads/[OUTPUT_FILENAME].csv 2>&1"}}
```

**CRITICAL path rules:**
- Script: always `/root/openclaw-zero-token/skills/sg-verify/scripts/verify_emails.py`
- Input + output: always full absolute paths under `/root/.openclaw/workspace/leads/`
- Never use relative paths
- `process` does NOT exist — do not try to call it. Exec result is returned synchronously.

### Step 3 — On exec completion, show ALL rows in a code block, then send the summary:

**MANDATORY — Run this exec to display every lead with its verification result** (replace FILE_PATH):
```json
{"tool":"exec","parameters":{"command":"python3 -c \"\nimport csv\nrows = list(csv.DictReader(open('FILE_PATH', encoding='utf-8-sig')))\nprint(f'Total: {len(rows)} leads')\nfor i, r in enumerate(rows, 1):\n    co = (r.get('company_name') or '').strip()\n    em = (r.get('email') or r.get('contact_email') or '').strip()\n    st = (r.get('email_status') or r.get('email_verified') or '').strip()\n    nm = (r.get('decision_maker_name') or r.get('contact_1_name') or '').strip()\n    ti = (r.get('decision_maker_title') or r.get('contact_1_title') or '').strip()\n    ph = (r.get('phone') or r.get('direct_phone') or '').strip()\n    icon = {'valid':'OK','verified':'OK','true':'OK','catch_all':'CA','catch-all':'CA','risky':'CA','invalid':'XX','false':'XX','no_mx':'XX','unverifiable':'??','unknown_deliverable':'CA'}.get(st.lower(),'?')\n    print(f'[{icon}] {i}. {co}')\n    if nm: print(f'     {nm}' + (f' — {ti}' if ti else ''))\n    if em: print(f'     {em}')\n    if ph: print(f'     {ph}')\n    print()\n\" 2>&1"}}
```

**After the exec returns, wrap the entire output in triple backticks and send it as a code block:**
```
[OK] = verified   [CA] = catch-all (safe)   [XX] = invalid/dead   [??] = unverifiable
```

If more than 40 rows, run two exec calls (rows[:40] then rows[40:]) and send as two separate code-block messages.

**Then run stats:**
```json
{"tool":"exec","parameters":{"command":"python3 -c \"\nimport csv\nrows = list(csv.DictReader(open('FILE_PATH', encoding='utf-8-sig')))\ntotal = len(rows)\nok = sum(1 for r in rows if (r.get('email_status') or r.get('email_verified') or '').lower() in ('true','valid','verified'))\nca = sum(1 for r in rows if (r.get('email_status') or r.get('email_verified') or '').lower() in ('catch_all','catch-all','risky','unknown_deliverable'))\nbad = sum(1 for r in rows if (r.get('email_status') or r.get('email_verified') or '').lower() in ('false','invalid','no_mx'))\nunk = total - ok - ca - bad\nprint(f'total={total} verified={ok} catchall={ca} invalid={bad} unverifiable={unk}')\n\" 2>&1"}}
```

**Then send the summary message:**

```
✅ VERIFICATION COMPLETE!
📁 [output path]

📊 [verified]✅ verified · [catchall]⚠️ catch-all · [invalid]❌ invalid · [unverifiable]🔒 unverifiable

[Triple-check analysis based on actual numbers — see below]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔜 NEXT STEP — Choose one:
1️⃣ Generate outreach for verified + catch-all leads
2️⃣ Run sg-enrich to find better emails for failed leads
3️⃣ Re-run enrich on just the failed leads

Which would you like?
```

**Triple-check analysis rules (write based on actual numbers):**

If verified ≥ 60%: "Strong list. [N]% verified. Ready for outreach on verified + catch-all."

If verified 30–59%: "Moderate quality. Only [N]% fully verified. Recommend running pattern generation on failed leads or removing them."

If verified < 30%: "Poor email quality. Run sg-enrich contacts to find better emails before outreach. Do NOT send to failed/unverifiable addresses."

**NEVER list individual emails in the summary message — the full code block above already shows everything.**

**If this is the SECOND verify run (after enrichment):** append "Post-enrichment check — use only [OK] and [CA] leads for outreach."

### Step 4 — If exec output contains an error, report it:
```
❌ Verification failed.

Error: [error from exec output]
```

**NEVER fabricate stats. All numbers must come from exec reading the actual output CSV.**
**NEVER call `process` — it does not exist in the web tool set.**

## Usage Examples

**Standard run (recommended):**
```bash
python3 /root/openclaw-zero-token/skills/sg-verify/scripts/verify_emails.py \
  /root/.openclaw/workspace/leads/sg_leads_raw.csv \
  --output /root/.openclaw/workspace/leads/sg_leads_verified.csv
```

**Faster: skip SMTP on catch-all domains:**
```bash
python3 /root/openclaw-zero-token/skills/sg-verify/scripts/verify_emails.py \
  /root/.openclaw/workspace/leads/sg_leads_raw.csv \
  --skip-catchall-smtp \
  --output /root/.openclaw/workspace/leads/sg_leads_verified.csv
```

**Adjust concurrency:**
```bash
python3 /root/openclaw-zero-token/skills/sg-verify/scripts/verify_emails.py \
  /root/.openclaw/workspace/leads/sg_leads_raw.csv \
  --workers 3 --delay 1.5 \
  --output /root/.openclaw/workspace/leads/sg_leads_verified.csv
```

**Script path:** `/root/openclaw-zero-token/skills/sg-verify/scripts/verify_emails.py`
**Leads dir:** `/root/.openclaw/workspace/leads/`
**NEVER use `skills/sg-verify/...` or `leads/...` — always full absolute paths**

## Output Columns Added

| Column | Values | Meaning |
|---|---|---|
| email_verified | true / false / catch_all / unverifiable / no_mx / invalid_format | Final verdict |
| email_confidence | 0–100 | Confidence score |
| email_source | scraped / pattern_info / pattern_enquiry / etc. | Where email came from |
| email_status_detail | Human-readable string | Explains the result |
| mx_provider | google / microsoft / custom / none | Mail infrastructure |
| is_catch_all | true / false / unknown | Whether domain accepts all mail |

## Confidence Score Guide

| Score | Meaning | Action |
|---|---|---|
| 80–100 | SMTP confirmed, not catch-all | Safe to send |
| 60–79 | SMTP confirmed OR high-confidence pattern | Send with normal care |
| 40–59 | Catch-all domain or ambiguous response | Send cautiously, monitor bounce rate |
| 20–39 | Connection blocked / timeout | Only send if no better contact |
| 0–19 | Definitively rejected or invalid format | Do not send |

## How It Works

**Stage 1 — Format validation**
Regex check. Rejects malformed addresses instantly.

**Stage 2 — MX record lookup**
DNS query for domain's mail servers. No MX = dead domain. Cached per domain.

**Stage 3 — Catch-all detection**
Sends RCPT TO for a random impossible address (e.g. xtest84729201@domain.com).
If server accepts it → domain is catch-all. Cached per domain (one check total).

**Stage 4 — SMTP handshake**
Full SMTP conversation on port 25 (fallback to 587):
EHLO → MAIL FROM → RCPT TO → RSET → QUIT
Server response 250 = mailbox exists. 550 = does not exist.
No email is ever sent. Recipient is never notified.

**Stage 5 — Pattern generation (if no email in CSV)**
Tries patterns in order: info@ → sales@ → enquiry@ → admin@ →
contact@ → firstname@ → firstname.lastname@
Stops at first 250 response.

## Singapore-Specific Notes

- `enquiry@` is the most common SG business contact pattern — always tried
- ACRA-registered Pte Ltd companies on Singnet/StarHub hosting: use port 587 fallback
- Google Workspace (very common for SG SMEs): SMTP probes often blocked.
  Script marks as `unverifiable` with confidence 55 — do not discard these.
- Port 25 blocked? Script detects this and warns. Run on a VPS for full accuracy.

## Interpreting Results for Outreach

After running, filter for outreach:
- `email_verified == 'true'` → Tier 1 send list
- `email_verified == 'catch_all' AND email_confidence >= 50` → Tier 2 (monitor bounces)
- `email_verified == 'unverifiable' AND mx_provider == 'google'` → Tier 2 (Google blocks probes)
- Everything else → do not send

## Error Recovery

| Error | What happened | Fix |
|---|---|---|
| "Port 25 may be blocked" | ISP/cloud blocks outbound port 25 | Run on VPS, or use --skip-catchall-smtp |
| All results 'unverifiable' | Firewall issue | Check outbound port 25 access |
| Script crash mid-run | Unhandled exception | Partial results saved. Re-run with same command, results will append |
| "No MX records found" | Domain is dead or wrong domain extracted | Check website column formatting |

## Integration with sg-leadgen

Takes `leads/sg_leads_raw.csv` from sg-leadgen output directly.
Outputs `leads/sg_leads_verified.csv` ready for sg-enrich input.

Adds 0 cost. Runs at ~30–60 leads/minute on a standard VPS with port 25 open.
On residential/cloud IPs (port 25 blocked): ~100 leads/minute (MX-only mode).
