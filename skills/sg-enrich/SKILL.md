---
name: sg-enrich
description: "Lead enrichment pipeline for Singapore B2B leads. Zero-cost — no paid APIs. Has TWO distinct scripts: (1) enrich_contacts.py for emails, phone numbers, and decision makers from websites and SearXNG search; (2) enrich_leads.py for intent signals (GeBIZ tenders, job postings, news), tech stack, and WhatsApp numbers. Use when user says: enrich leads, find WhatsApp numbers, detect tech stack, check tender activity, sg-enrich, run enrichment, find intent signals. ALSO use when user says: get emails, find decision makers, email enrichment, emails and phone numbers, enrich for emails, get contacts, find CEO emails — these route to enrich_contacts.py FIRST."
metadata:
  {
    "openclaw": {
      "emoji": "🔍",
      "requires": { "bins": ["python3", "pip"] }
    }
  }
---

# SG Lead Enrichment — Zero-Cost Pipeline

Discovers intent signals, tech stack, and WhatsApp numbers using
only browser-based scraping and free public data sources.

---

## ⚡ OPENCLAW SAFETY LIMITS — NEVER BREAK THESE

**DeepSeek V4 on OpenClaw / Telegram is unstable for long-running tasks.**
**If a single exec runs longer than ~3 minutes, the bot may appear to freeze or the session may die.**

### HARD BATCH SIZE LIMITS

| Script | Mode | Batch Size | Workers | Expected Duration | Safe? |
|--------|------|------------|---------|-------------------|-------|
| `enrich_leads.py` | `--skip-google` | **10 leads** | 3 | 30–60s | ✅ Yes |
| `enrich_leads.py` | Full (with Google) | **5 leads** | 2 | 2–4 min | ⚠️ Use only if user asks for tender/news/hiring |
| `enrich_contacts.py` | Default | **10 leads** | 3 | 40–80s | ✅ Yes |

Gateway hard kill: 300s. Keep all batches well under 240s to be safe.

**NEVER process an entire file in one exec call if it has more than the max per batch.**
**You MUST chunk the file into multiple sequential batches using `--limit` and `--offset`.**

### WHY CHUNKING IS MANDATORY

- Telegram users think the bot is broken after 60s of silence
- `backgroundMs` is set to 270s — exec auto-backgrounds any command still running at 2 minutes. `process` does NOT exist on the web bridge, so the model can never retrieve the output of a backgrounded command.
- Google rate limiting causes 30-60s pauses between searches
- A single 43-lead full enrichment took **10 minutes** — far beyond the 270s foreground window
- Chunking guarantees each batch completes within the 270s window and results come back directly

**NEVER use `"background":true` in exec JSON for enrichment.** It immediately returns a session ID and the model can never poll it. Run each batch synchronously — output comes back in 40-80s per batch.

---

## Prerequisites

Install once:
```bash
pip install requests beautifulsoup4 dnspython tqdm colorama lxml
```

Script locations:
- Intent signals: `/root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_leads.py`
- Contacts: `/root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_contacts.py`

---

## Command Triggers

| User says | Action |
|---|---|
| "enrich leads in [file]" | Run intent signals + tech stack pipeline (chunked) |
| "find WhatsApp numbers" | Run enrich_leads.py with --skip-google flag (chunked) |
| "check tender activity" | Run enrich_leads.py full pipeline (chunked, max 5/batch) |
| "detect tech stack" | Run enrich_leads.py --skip-google (chunked) |
| "sg-enrich status" | Show last run summary |
| "get emails" / "find decision makers" / "email enrichment" / "emails and phone numbers" / "enrich for emails" / "get contacts" / "get decision maker contacts" / "enrich contacts" / "find CEO emails" / "enrich with direct phone numbers" | **Run `enrich_contacts.py` FIRST** (chunked). |

**CRITICAL routing rule:** When the user's request mentions "email", "contact", "decision maker", "phone numbers", or "CEO" — run `enrich_contacts.py`, NOT `enrich_leads.py`. The intent signals script does NOT extract email addresses.

---

## Chunked Execution — The Only Safe Way

### Step 0 — Count rows FIRST

Before enriching, you MUST know how many leads are in the file:

```tool_json
{"tool":"exec","parameters":{"command":"python3 -c \"import csv; rows=list(csv.DictReader(open('/root/.openclaw/workspace/leads/[FILENAME].csv', encoding='utf-8-sig'))); print(f'total_rows={len(rows)}')\" 2>&1"}}
```

### Step 1 — Determine batch size

| Total Leads | Mode | Batch Size | Number of Batches |
|-------------|------|------------|-------------------|
| 1-10 | `--skip-google` | All | 1 |
| 11-30 | `--skip-google` | 10 | 3 |
| 31-50 | `--skip-google` | 10 | 5 |
| 1-5 | Full Google | All | 1 |
| 6-20 | Full Google | 5 | 4 |
| 21-50 | Full Google | 5 | 10 |

**Default recommendation:** Always use `--skip-google` unless the user explicitly asks for tender/news/hiring signals. It is 10x faster and safer.

### Step 2 — Send start notification with batch plan

```
🔄 Enrichment started for [N] companies...
⏱️ Mode: [skip-google / full-google] | Batch size: [X] | Batches: [Y]
⏳ Processing batch 1/[Y] now.
```

### Step 3 — Run batch 1 (blocking exec — result returns directly, no process poll needed)

**`process` does NOT exist for DeepSeek V4. Exec is synchronous. Each 10-lead batch completes in 40–80s, well within the 300s limit.**

**For intent signals (enrich_leads.py) — Batch 1:**

```tool_json
{"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_leads.py /root/.openclaw/workspace/leads/[INPUT].csv --output /root/.openclaw/workspace/leads/[INPUT]_enriched_batch1.csv --skip-google --limit 10 --offset 0 2>&1"}}
```

**For contacts (enrich_contacts.py) — Batch 1:**

```tool_json
{"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_contacts.py /root/.openclaw/workspace/leads/[INPUT].csv --output /root/.openclaw/workspace/leads/[INPUT]_contacts_batch1.csv --workers 3 --limit 10 2>&1"}}
```

**New columns added by enrich_contacts.py:**
| Column | Source | Notes |
|--------|--------|-------|
| `direct_email` | Website scrape | Best non-generic email found |
| `direct_phone` | Website scrape | Best SG phone found |
| `whatsapp` | wa.me links | WhatsApp number if on website |
| `decision_maker_name` | Website + LinkedIn | Top-ranked contact (backward compat) |
| `decision_maker_title` | Website + LinkedIn | Title of top-ranked contact |
| `contact_1_name` | Website + LinkedIn | Same as decision_maker_name |
| `contact_1_title` | Website + LinkedIn | Same as decision_maker_title |
| `contact_2_name` | Website + LinkedIn | Second-ranked contact |
| `contact_2_title` | Website + LinkedIn | Title of second contact |
| `contact_3_name` | Website + LinkedIn | Third-ranked contact |
| `contact_3_title` | Website + LinkedIn | Title of third contact |
| `mas_licensed` | SearXNG (MAS FID) | `yes` / `no` / `unknown` (off by default) |

**MAS licensed check:** Disabled by default (`--no-mas`). Enable with `--mas` if needed.

**CRITICAL path rules:**
- Always use `--limit` and `--offset` for `enrich_leads.py`
- Always use `--limit` for `enrich_contacts.py`
- Always use `--skip-google` by default
- Never omit `--limit` — this is what keeps batches small and safe

### Step 4 — On exec completion, auto-prompt next batch

**DO NOT ask the user for confirmation. Automatically execute the next batch.**

Send completion message:
```
✅ Batch 1/[Y] complete! ([N] companies enriched)
⏳ Starting batch 2/[Y] now...
```

Then immediately start batch 2:

```tool_json
{"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_leads.py /root/.openclaw/workspace/leads/[INPUT].csv --output /root/.openclaw/workspace/leads/[INPUT]_enriched_batch2.csv --skip-google --limit 10 --offset 10 2>&1"}}
```

**Repeat Step 4 until all batches are done.**

### Step 6 — Merge all batch files

After the final batch completes, merge all batch CSVs into one final file:

```tool_json
{"tool":"exec","parameters":{"command":"python3 -c \"\nimport csv, os, glob\nbase = '/root/.openclaw/workspace/leads/[INPUT]'\nbatches = sorted(glob.glob(base + '_enriched_batch*.csv'))\nif not batches:\n    print('No batch files found')\n    exit(1)\nrows = []\nheader = None\nfor f in batches:\n    with open(f, 'r', encoding='utf-8-sig') as fh:\n        reader = csv.DictReader(fh)\n        if not header:\n            header = reader.fieldnames\n        rows.extend(list(reader))\noutput = base + '_enriched.csv'\nwith open(output, 'w', newline='', encoding='utf-8-sig') as fh:\n    writer = csv.DictWriter(fh, fieldnames=header)\n    writer.writeheader()\n    writer.writerows(rows)\nprint(f'Merged {len(batches)} batches, {len(rows)} total rows -> {output}')\n\" 2>&1"}}
```

### Step 7 — Present final stats

```tool_json
{"tool":"exec","parameters":{"command":"python3 -c \"\nimport csv\nwith open('/root/.openclaw/workspace/leads/[INPUT]_enriched.csv', encoding='utf-8-sig') as f:\n    rows = list(csv.DictReader(f))\ntotal = len(rows)\nwa = sum(1 for r in rows if r.get('whatsapp_number','').strip())\ntech = sum(1 for r in rows if r.get('tech_stack','').strip())\nhot = sum(1 for r in rows if float(r.get('lead_score_v2') or r.get('lead_score') or 0) >= 70)\nprint(f'total={total} whatsapp={wa} tech={tech} hot={hot}')\nfor r in rows[:10]:\n    print(f\\\"{r.get('company_name','?')} | {r.get('whatsapp_number','') or 'no WA'} | {r.get('tech_stack','') or 'no tech'} | score={r.get('lead_score_v2','?')}\\\")\n\" 2>&1"}}
```

Then send:
```
✅ ALL BATCHES COMPLETE!

📁 File: /root/.openclaw/workspace/leads/[INPUT]_enriched.csv
📊 Total: [N] companies | WhatsApp: [N] | Tech: [N] | Hot: [N]
🔢 Batches processed: [Y]

🔜 MANDATORY NEXT STEP:
If this enrichment found new emails (especially from contact enrichment), they MUST be verified.

Run sg-verify on this file before outreach? (5 per batch, deep mode)

Verify → Outreach. Never outreach on unverified emails.
```

---

## Full Example — 25 Leads with Skip-Google (3 Batches)

**User:** `enrich leads in sg_leads_verified.csv`

**Model behavior:**

1. Count rows: `total_rows=25`
2. Announce plan:
   ```
   🔄 Enrichment started for 25 companies...
   ⏱️ Mode: skip-google (fast & stable) | Batch size: 10 | Batches: 3
   ⏳ Processing batch 1/3 now.
   ```
3. **Batch 1** (offset=0, limit=10) — blocking exec, result returns directly:
   ```tool_json
   {"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_leads.py /root/.openclaw/workspace/leads/sg_leads_verified.csv --output /root/.openclaw/workspace/leads/sg_leads_verified_enriched_batch1.csv --skip-google --limit 10 --offset 0 2>&1"}}
   ```
4. Batch 1 exec returns with output. Auto-announce + start **Batch 2** (offset=10, limit=10):
   ```
   ✅ Batch 1/3 complete! (10 companies)
   ⏳ Starting batch 2/3 now...
   ```
   ```tool_json
   {"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_leads.py /root/.openclaw/workspace/leads/sg_leads_verified.csv --output /root/.openclaw/workspace/leads/sg_leads_verified_enriched_batch2.csv --skip-google --limit 10 --offset 10 2>&1"}}
   ```
5. Batch 2 exec returns. Auto-announce + start **Batch 3** (offset=20, limit=5):
   ```
   ✅ Batch 2/3 complete! (10 companies)
   ⏳ Starting batch 3/3 now...
   ```
   ```tool_json
   {"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_leads.py /root/.openclaw/workspace/leads/sg_leads_verified.csv --output /root/.openclaw/workspace/leads/sg_leads_verified_enriched_batch3.csv --skip-google --limit 5 --offset 20 2>&1"}}
   ```
6. Batch 3 exec returns. Merge all 3 batch files into `sg_leads_verified_enriched.csv`
10. Present final stats

**Total estimated time:** ~3-4 minutes (3 batches × ~60-90s each, with polling overhead)

**User experience:** Progress update every 60-90s. Never silent for >2 minutes.

---

## Contact Enrichment — Decision Makers, Emails, Phones

Use the **contact enrichment script** when the user asks for:
- "get decision maker contacts"
- "find CEO emails"
- "enrich with direct phone numbers"
- "get founder names"

### Chunked execution — use `--offset` exactly like enrich_leads.py:

**Batch 1 (rows 0–9):**
```tool_json
{"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_contacts.py /root/.openclaw/workspace/leads/[INPUT].csv --output /root/.openclaw/workspace/leads/[INPUT]_contacts_batch1.csv --workers 3 --limit 10 --offset 0 2>&1"}}
```

**Batch 2 (rows 10–19):**
```tool_json
{"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_contacts.py /root/.openclaw/workspace/leads/[INPUT].csv --output /root/.openclaw/workspace/leads/[INPUT]_contacts_batch2.csv --workers 3 --limit 10 --offset 10 2>&1"}}
```

**Batch 3 (rows 20–N):**
```tool_json
{"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_contacts.py /root/.openclaw/workspace/leads/[INPUT].csv --output /root/.openclaw/workspace/leads/[INPUT]_contacts_batch3.csv --workers 3 --limit 10 --offset 20 2>&1"}}
```

### What it does:
- SSL bypass (handles expired/self-signed SG SME certs)
- Cloudflare email decode (recovers hidden emails from `data-cfemail` attributes)
- JSON-LD structured data parsing (extracts emails and people from `<script type="application/ld+json">`)
- Contact page link discovery (finds `/contact-us`, `/about-us`, `/team`, `/leadership`, etc.)
- Probes 5 standard paths: `/contact`, `/contact-us`, `/about-us`, `/team`, `/leadership`
- Also fetches up to 4 contact pages discovered in homepage HTML
- Extracts names with titles (CEO, Founder, Director, Managing Director, etc.)
- Searches SearXNG for `"Company Name" CEO Singapore contact email`
- Compiles direct emails and Singapore phone numbers
- Pattern fallback: generates `enquiry@domain.com` if no email found
- Email false-positive filters (rejects image filenames, hex hashes, timestamps)
- Decision maker false-positive filters (rejects "Google Premier Partner", etc.)

### ⚠️ AFTER CONTACT ENRICHMENT — VERIFY AGAIN

Contact enrichment discovers NEW emails from websites and search results. These emails are UNVERIFIED.

**After ALL contact enrichment batches complete and merge, do the following IN ORDER:**

**Step 1 — Show EVERY row from the enriched CSV.** Use this exec (replace FILE_PATH with the actual merged output path):
```json
{"tool":"exec","parameters":{"command":"python3 -c \"\nimport csv\nrows = list(csv.DictReader(open('FILE_PATH', encoding='utf-8-sig')))\nprint(f'Total: {len(rows)} leads\\n')\nfor i, r in enumerate(rows, 1):\n    co = (r.get('company_name') or '').strip()\n    nm = (r.get('decision_maker_name') or r.get('contact_1_name') or '').strip()\n    ti = (r.get('decision_maker_title') or r.get('contact_1_title') or '').strip()\n    em = (r.get('email') or r.get('direct_email') or r.get('contact_email') or '').strip()\n    ph = (r.get('phone') or r.get('direct_phone') or '').strip()\n    we = (r.get('website') or '').strip()\n    line = f'{i}. {co}'\n    print(line)\n    if nm: print(f'   {nm}' + (f' — {ti}' if ti else ''))\n    if em: print(f'   {em}')\n    if ph: print(f'   {ph}')\n    if we: print(f'   {we}')\n    print()\n\" 2>&1"}}
```

**After the exec returns, wrap the entire output in triple backticks and send it as a code block.** EVERY row must appear — never cap at 5, 10, or any other number. If there are more than 40 rows, split into two exec calls (rows[:40] and rows[40:]) and send as two separate code-block messages.

**Step 2 — After displaying all rows, send the verification notice:**
```
✅ Enrichment complete!

[N] companies · [DM count] decision makers found · [email count] new emails · [phone count] phone numbers

📁 FILE_PATH

These new emails are UNVERIFIED — they came from scraped pages and may be stale.
🔜 Run sg-verify on this file before outreach.

Type "verify" to start, or "show top 10" for highest-value leads first.
```

**NEVER skip Step 1. The user must see ALL rows before deciding what to do next.**

### New columns added:
- `decision_maker_name` — best contact person found
- `decision_maker_title` — their title
- `direct_email` — best email (prefers non-generic addresses)
- `direct_phone` — cleaned Singapore phone number

---

## Output Columns Added (enrich_leads.py)

| Column | Meaning |
|---|---|
| `whatsapp_number` | Extracted WhatsApp number or empty |
| `tech_stack` | Comma-separated tech detected (Shopify, Google Analytics, etc.) |
| `intent_signals` | Comma-separated signals (hiring_sales, gebiz_tender, etc.) |
| `recent_tender` | true / false / unknown |
| `tender_value` | SGD amount or empty |
| `hiring_signals` | Job titles being hired |
| `news_signal` | 1-sentence news summary or empty |
| `personalization_hook` | 1-sentence outreach angle |
| `outreach_channel` | email / email+whatsapp / linkedin |
| `enrichment_score_bonus` | Additional points (0-50) |
| `lead_score_v2` | Updated score (original + bonus) |

---

## How It Works

**Module 1 — Tech Stack Detection**
Fetches website HTML, scans headers and body for 40+ technology signatures:
CMS (Shopify, WordPress, Wix), CRM (HubSpot, Salesforce), analytics (GA, FB Pixel),
payments (Stripe, PayPal), hosting (AWS, Cloudflare), marketing (Mailchimp, Klaviyo).

**Module 2 — WhatsApp Finder**
Searches for wa.me links, WhatsApp API links, and text patterns mentioning WhatsApp
near phone numbers. Cleans numbers to +65XXXXXXXX format.

**Module 3 — Intent Signals (ONLY with full Google mode)**
Google searches for:
- GeBIZ tenders (SG government contracts) with dollar amounts
- MyCareersFuture job postings with hiring signal titles
- Recent news mentioning expansion/funding/launch/award

Rate limited: 3-6s delay between Google requests, 30s pause every 20 requests.
**This is why full-Google mode is limited to 5 leads per batch.**

---

## Performance & Timing (Realistic)

| Script / Mode | Batch | Workers | Duration | Verdict |
|---------------|-------|---------|----------|---------|
| `enrich_leads.py --skip-google` | 10 | 3 | 30–60s | ✅ Safe |
| `enrich_leads.py --skip-google` | 15 | 3 | 60–90s | ✅ Safe |
| `enrich_leads.py --skip-google` | 25 | 3 | 2–3 min | ⚠️ Risky |
| `enrich_leads.py` full Google | 5 | 2 | 2–4 min | ⚠️ Borderline |
| `enrich_leads.py` full Google | 10 | 3 | 5–8 min | ❌ Will timeout |
| `enrich_contacts.py` | 10 | 3 | 40–80s | ✅ Safe |
| `enrich_contacts.py` | 15 | 3 | 80–270s | ✅ Safe |
| `enrich_contacts.py` | 20 | 3 | 120–180s | ⚠️ Borderline |

**How per-lead timing works for enrich_contacts.py:**
- 1 homepage fetch (6s timeout)
- Up to 4 discovered contact pages (6s each)
- 5 standard paths probed: `/contact`, `/contact-us`, `/about-us`, `/team`, `/leadership` (6s each)
- Optional SearXNG search if no emails/people found (15s)
- Worst case per lead: ~60s. With 3 workers, 10 leads ≈ 40–80s wall time.

**Rule of thumb:** If a batch might take >4 minutes, split it further.

---

## Personalization Hooks (Priority Order)

1. GeBIZ tender activity → "Recently active on GeBIZ with SGD X in contracts"
2. News signal → "Noticed: [news snippet]"
3. Hiring signals → "Currently hiring [role] — signals [pain point]"
4. Tech stack (e-commerce) → "Running e-commerce on [tech]"
5. Tech stack (CRM) → "Already using [CRM] — sales stack in place"
6. WhatsApp reachable → "WhatsApp-reachable — likely responsive"
7. Default → "Active [industry] business in [area]"

---

## Singapore-Specific Notes

- `enquiry@` email pattern is tried before admin@ (most common SG business pattern)
- SSL verification disabled — many SG SME sites have expired/self-signed certs
- Google rate limiting prevents 429 blocks
- Port 25 blocked warning from sg-verify handled gracefully

---

## Integration Pipeline — VERIFY TWICE RULE

```
sg-leadgen (max 25) → sg-verify (5/batch) → sg-enrich → sg-verify (new emails) → outreach
```

1. `sg-leadgen` generates `leads/sg_leads_raw.csv` (max 25)
2. `sg-verify` validates initial emails → `leads/sg_leads_verified.csv` (5 per batch, deep mode)
3. `sg-enrich` adds intent signals / tech stack → `leads/sg_leads_enriched.csv`
4. `sg-enrich contacts` adds decision-makers + NEW emails → `leads/sg_leads_contacts.csv`
5. **MANDATORY: `sg-verify` AGAIN on the contacts file** — enrichment finds new emails that must be verified
6. Filter for `direct_email != ''` and `lead_score_v2 >= 70` for Tier 1 outreach

**⚠️ THE VERIFY TWICE RULE:**
- First verify: after leadgen (catches bad pattern emails, dead domains)
- Second verify: after contact enrichment (validates newly discovered DM emails)
- NEVER skip the second verify. Newly found emails are often from scraped pages and can be stale or wrong.
- The bot MUST suggest this second verify in every enrichment completion message.

---

## Error Recovery

| Error | Fix |
|---|---|
| "Connection refused" on website | Site may be down — tech_stack and WhatsApp will be empty |
| Google 429 | Script auto-sleeps 60s and retries. This is why we limit batch size. |
| SSL errors | Handled gracefully — verify=False in all requests |
| Batch timed out | Re-run the SAME batch command. Partial results are NOT saved per batch, so re-running is safe. |
| "No batch files found" on merge | Check that all batch files were created. Re-run any missing batches. |

---

## Anti-Fabrication Rules

1. **NEVER say enrichment is complete until ALL batches are done and merged.**
2. **NEVER present stats from a single batch as final stats.**
3. **NEVER fabricate WhatsApp numbers, tech stacks, or intent signals.**
4. **Always read the final merged CSV before presenting results.**
5. **If a batch fails, report it honestly and retry that batch only.**
