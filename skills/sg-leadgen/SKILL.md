---
name: sg-leadgen
description: "Singapore B2B lead generation and enrichment. Uses SearXNG search and website enrichment to discover and score leads. Outputs enriched, deduplicated CSV lead lists. Use when the user mentions Singapore leads, business directory scraping, SG prospects, lead generation, B2B prospecting, company enrichment, or finding decision makers in Singapore."
metadata:
  {
    "openclaw": {
      "emoji": "🦁",
      "requires": { "bins": ["curl", "python3"] }
    }
  }
---

# Singapore Lead Generation & Enrichment

## ⚡ EXECUTION MODE — READ THIS FIRST

**When triggered by any of these — DO NOT EXPLAIN. START EXECUTING IMMEDIATELY:**
- `/sg-leadgen start [industry]` or `/sg-leadgen start [industry] --target [N]`
- "run sg-leadgen for [industry]" / "Run sg-leadgen targeting [X]"
- "find Singapore leads for [industry]"

**CORRECT behavior when triggered:**
1. DO NOT summarize this document
2. DO NOT explain the pipeline, list capabilities, or describe rate limiting
3. DO NOT ask for confirmation
4. IMMEDIATELY output a `tool_json` block calling `read` on this SKILL.md
5. After `read` returns, send a start message, then call `exec` (blocking — result returns directly, no polling needed)
6. NEVER display leads as a markdown table in chat BEFORE the CSV is saved
7. NEVER fabricate leads — only use data from the pipeline results
8. Before writing ANY data to CSV, you MUST have run the pipeline and obtained real data
9. AFTER saving the CSV, ALWAYS show ALL rows — never truncate (company name, phone, email, website)

**Example — if user says `/sg-leadgen start "Digital Marketing Agencies"`:**
*(Default target is 25. Never exceed 25 unless user explicitly asks for more.)*
Your FIRST output must be:
```tool_json
{"tool":"read","parameters":{"path":"/root/openclaw-zero-token/skills/sg-leadgen/SKILL.md"}}
```

Then after read returns:
```
🔄 Lead generation started for Digital Marketing Agencies...
⏱️ Estimated time: ~20-30 seconds
⏳ Running search → enrichment → deduplication now.
```

```tool_json
{"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-leadgen/scripts/run_full_pipeline.py 'Digital Marketing Agencies' --target 25 --output /root/.openclaw/workspace/leads/sg_leads_digitalmarketingagencies_17042026.csv --workers 5 --min-score 0 2>&1"}}
```

**If user explicitly wants more than 25:** Use their number, but warn: "⚠️ Large lists are harder to verify/enrich in batches. I recommend starting with 25."

**NEVER default to more than 25.** The quality drops and batch processing becomes unwieldy.

When `exec` returns, display ALL rows from the CSV — EVERY company, no cap. Use this exec (replace FILE_PATH):
```json
{"tool":"exec","parameters":{"command":"python3 -c \"\nimport csv\nrows = list(csv.DictReader(open('FILE_PATH', encoding='utf-8-sig')))\nprint(f'Total: {len(rows)} leads\\n')\nfor i, r in enumerate(rows, 1):\n    co = (r.get('company_name') or '').strip()\n    nm = (r.get('decision_maker_name') or r.get('contact_1_name') or '').strip()\n    ti = (r.get('decision_maker_title') or r.get('contact_1_title') or '').strip()\n    em = (r.get('email') or r.get('contact_email') or '').strip()\n    ph = (r.get('phone') or '').strip()\n    we = (r.get('website') or '').strip()\n    sc = (r.get('lead_score') or '').strip()\n    tr = (r.get('lead_tier') or '').strip()\n    line = f'{i}. {co}'\n    if sc: line += f' [{tr} {sc}]'\n    print(line)\n    if nm: print(f'   {nm}' + (f' — {ti}' if ti else ''))\n    if em: print(f'   {em}')\n    if ph: print(f'   {ph}')\n    if we: print(f'   {we}')\n    print()\n\" 2>&1"}}
```

After the exec returns, wrap the entire output in triple backticks and send it as a code block. If there are more than 40 rows, run two exec calls (rows[:40] then rows[40:]) and send as two separate code-block messages. NEVER show only a summary.

**CRITICAL: No Tool Calls = No Data**
- If you did NOT run the pipeline, you have NO leads
- Displaying a table without running the pipeline = FABRICATION
- Writing to CSV without pipeline data = FABRICATION
- NEVER fabricate. If no pipeline results, say "No leads found from search"

---

Full Singapore lead generation pipeline using **SearXNG search and batch website enrichment** — no paid APIs needed. Covers discovery, extraction, deduplication, and scoring in a single background exec.

## Prerequisites

1. **Tools available (DeepSeek V4 web):** `exec`, `read`, `write`, `web_search`, `web_fetch` — `process` does NOT exist
2. **No browser automation needed.** Pipeline uses HTTP fetching with proper headers.
3. **Search backend:** SearXNG on `localhost:8080` using DuckDuckGo, Yahoo, and Mojeek → Yelu.sg directory fallback. No config needed.
4. **PDPA compliance.** All sources publicly accessible. Comply with Singapore Personal Data Protection Act.

## Command Triggers

| User says | Action |
|---|---|
| `/sg-leadgen start [industry]` | Full pipeline: search → enrich → deduplicate → export |
| `/sg-leadgen start [industry] --target [N]` | Full pipeline with custom lead volume |
| "find Singapore leads for [industry]" | Full pipeline |
| "Run sg-leadgen targeting [X]" | Full pipeline for target category |
| "enrich leads from [file]" | Hand off to `sg-enrich` |
| "deduplicate leads" | Deduplication + scoring only |

## Master Pipeline

The pipeline is executed by a single Python script. The model's job is to:
1. Send a start message
2. Call `exec` (blocking — result returns directly in the tool response, no polling needed)
3. Read the output CSV and present results

**Pipeline stages (handled internally by script):**
```
Stage 1 → SearXNG batch search (9 targeted queries with dorks: site:, exact phrase; engines: DuckDuckGo, Yahoo, Mojeek; language=en)
Stage 2 → Build unique lead list + auto-extract actual companies from listicles/blog posts
Stage 3 → Website enrichment (emails, phones, decision makers) — SSL bypass, CF decode, JSON-LD, contact page discovery
Stage 4 → Deduplication + scoring (dedup_score.py)
Stage 5 → Final CSV export
```

**Lead quality improvements (v3):**
- Blog posts and directories ("Top 15 Fintech Companies...") are NO longer saved as leads
- Instead, the pipeline fetches those listicles and extracts the actual companies inside them
- Search queries now include `startup` and `company` variants to find real business websites
- Government pages, event listings, and association directories are filtered out
- **Email extraction**: Cloudflare email decode, JSON-LD parsing, contact page link discovery (/contact-us, /about-us, etc.), false-positive filters
- **Phone extraction**: Singapore number normalization to +65XXXXXXXX format
- **Decision maker extraction**: Name + title from team pages with false-positive filters
- **SSL bypass**: Handles expired/self-signed certs on SG shared hosting
- **HTTP fallback**: Tries HTTPS first, then HTTP
- **Pattern email fallback**: Generates enquiry@domain.com if no email found on site

**If the user asks for decision-maker contacts (names, direct emails, phones) AFTER the pipeline:**
The pipeline already extracts emails, phones, and decision makers in Stage 3. If the user wants deeper contact enrichment, run `sg-enrich` with the **contact enrichment** script.

**CRITICAL: Contact enrichment MUST be chunked for OpenClaw stability. Never process >10 leads in one exec call.**

For files with ≤10 leads:
```tool_json
{"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_contacts.py /root/.openclaw/workspace/leads/[INPUT].csv --output /root/.openclaw/workspace/leads/[INPUT]_contacts.csv --workers 3 --limit 10 2>&1"}}
```

For files with >10 leads, read the sg-enrich SKILL.md for the chunked batch workflow.

## Pipeline Execution Order — CRITICAL (DeepSeek V4 web tools)

**`process` tool does NOT exist on the DeepSeek V4 web bridge. DO NOT use `"background":true` in exec JSON.**

Why: `background:true` immediately returns "Command still running, use process to poll" — but `process` isn't available, so the model never sees the output.

The correct approach:
- `backgroundMs` in config is set to **270s** (2 minutes). Any exec that finishes before 270s returns its output directly.
- 25 leads takes ~30–60s — well within the 270s window. Run as a single exec, output comes back directly.
- For the full Mirae pipeline (5-20 min), use shell `&` in the command string (not `background:true` JSON param) + poll a status file. See SOUL.md Rule 5.

### Step 1 — Send start notification FIRST (before exec):
```
🔄 Lead generation started for [INDUSTRY]...
⏱️ Estimated time: ~30-60 seconds
⏳ Running SearXNG search → website enrichment → deduplication.
```

### Step 2 — Run the pipeline (one blocking exec, result comes back directly):

**CRITICAL path rules:**
- Script: always `/root/openclaw-zero-token/skills/sg-leadgen/scripts/run_full_pipeline.py`
- Output: always full absolute path under `/root/.openclaw/workspace/leads/`
- Never use relative paths

```tool_json
{"tool":"exec","parameters":{"command":"python3 /root/openclaw-zero-token/skills/sg-leadgen/scripts/run_full_pipeline.py '[INDUSTRY]' --target 25 --output /root/.openclaw/workspace/leads/sg_leads_[INDUSTRYSLUG]_[DDMMYYYY].csv --workers 5 --min-score 0 2>&1"}}
```

**Target rules:**
- Default: 25 (recommended quality/quantity balance)
- Only if user explicitly asks for more: use their number
- Never silently use >25

**File naming:**
- "Digital Marketing Agencies" → `sg_leads_digitalmarketingagencies_17042026.csv`
- "F&B Suppliers" → `sg_leads_fnbsuppliers_17042026.csv`
- Use lowercase, replace spaces with underscores, remove special characters.

The exec returns the full script stdout/stderr. Check for errors in the output before proceeding.

### Step 3 — On exec completion, read real stats from output file:
```tool_json
{"tool":"exec","parameters":{"command":"python3 -c \"\nimport csv\nwith open('/root/.openclaw/workspace/leads/[FILENAME].csv', encoding='utf-8-sig') as f:\n    rows = list(csv.DictReader(f))\ntotal = len(rows)\nhot = sum(1 for r in rows if r.get('lead_tier') == 'Hot')\nwarm = sum(1 for r in rows if r.get('lead_tier') == 'Warm')\ncold = sum(1 for r in rows if r.get('lead_tier') == 'Cold')\nhas_email = sum(1 for r in rows if r.get('email','').strip())\nhas_phone = sum(1 for r in rows if r.get('phone','').strip())\nprint(f'STATS: total={total} hot={hot} warm={warm} cold={cold} emails={has_email} phones={has_phone}')\nprint(f\\\"{'#':<3} {'Company':<35} {'Phone':<16} {'Email':<35} {'Tier'}\\\")\nprint('-' * 93)\nfor i, r in enumerate(rows, 1):\n    co = r.get('company_name','')[:34]\n    ph = r.get('phone','')[:15]\n    em = r.get('email','')[:34]\n    tier = r.get('lead_tier','')\n    print(f\\\"{i:<3} {co:<35} {ph:<16} {em:<35} {tier}\\\")\n\" 2>&1"}}
```

Then send completion using REAL numbers from the exec output.
**ALWAYS wrap the lead table in a code block (triple backticks) for clean Telegram display.**

```
✅ [total] [INDUSTRY] companies found in Singapore

📁 /root/.openclaw/workspace/leads/[FILENAME].csv
📊 [has_email] with email · [has_phone] with phone
🏆 Hot: [hot] · Warm: [warm] · Cold: [cold]

```
#   Company                             Phone            Email                               Tier
----------------------------------------------------------------------------------------------
1   Acme Construction Pte Ltd          +6562345678      enquiry@acme.com.sg                 Warm
2   ...
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔜 NEXT STEP — Find decision makers + missing emails

sg-enrich visits each company's website to find:
• Decision maker names & job titles
• Direct email addresses (many sites hide them from search engines)

I'll run it in batches of 10 and keep you updated after each batch.
Type **yes** to start enrichment, or **skip** to go straight to email verification.
```

### Step 4 — If exec output contains an error, report it:
```
❌ Lead generation failed.

Error: [error from exec output]
```

**NEVER fabricate stats. All numbers must come from exec reading the actual output CSV.**
**NEVER call `process` — it does not exist in the web tool set.**

## ⚠️ CRITICAL: Save Leads Correctly

When the user asks to save leads to CSV:

**CORRECT way:**
The pipeline script already writes the final CSV. Just present it to the user.

**WRONG ways (NEVER do this):**
- Writing to `/tmp/leads.csv`
- Using placeholder/fake/dummy data
- Not saving and just showing a table
- Asking the user how to save

**Required columns (already in pipeline output):**
```
company_name,phone,email,website,address,area,industry,industry_confidence,detected_industry,sg_signals,uen,entity_type_desc,uen_status_desc,reg_street_name,reg_postal_code,mas_licensed,decision_maker_name,decision_maker_title,lead_score,lead_tier,source
```

**Scoring modes:**
- `dedup_score.py --mode default` (original): Hot ≥70, Warm ≥40, Cold <40
- `dedup_score.py --mode mirae` (v2): Hot ≥80, Warm ≥60, Cool ≥40, Cold <40
  - Weights: verified_email 15, verified_phone 10, acra_active 20, mas_licensed 15, title_match_cfinance 25, industry_advisory_icp 20, sg_signal 10, trigger_event 30, recency_bonus 5, linkedin_source 5

**Mirae pipeline wrapper (all stages in one backgrounded script — see SOUL.md Rule 5):**
```bash
# Ask user for sender name FIRST, then invoke backgrounded:
bash /root/openclaw-zero-token/skills/sg-leadgen/scripts/run_mirae_pipeline.sh \
  --industry "Construction" --target 25 \
  --sender-name "<NAME>" \
  --output-dir /root/.openclaw/workspace/leads/ > /tmp/mirae_run.log 2>&1 &
```
Stages: leadgen → dedup → verify1 → enrich (ACRA, full target) → verify2 → score (mirae) → sequences → send (dry-run)
Status files written to `<output-dir>/run_<ts>/status/<stage>.json`. Poll with: `ls -t /root/.openclaw/workspace/leads/run_*/status/pipeline.json | head -1 | xargs cat`

## IMPORTANT RULES — ANTI-FABRICATION

1. **FABRICATION = FIREABLE OFFENSE.** If you display leads in chat without running the pipeline, you are fabricating.
2. **Pipeline MUST be called first.** No pipeline = no data = no table = no CSV.
3. **Real data only.** Only report data from actual pipeline results.
4. **NEVER use fake data.** "Example Corp", "John Doe", test@test.com = FABRICATION.
5. **Verify before writing.** If you can't read actual lead data, you cannot write a CSV.
6. **If no results from pipeline**, tell the user "No leads found. Try a different query."

**Evidence check:**
- Did you call the pipeline? → Check your tool calls
- Did the pipeline return results? → Check the exec output
- Results → present CSV. No results → tell user.

## ERROR RECOVERY — FABRICATION PREVENTION

| If This Happens | Then Do This |
|---|---|
| No pipeline calls in your history | You have NO data. Run the pipeline FIRST |
| Table in chat but no pipeline tool call | FABRICATION. Delete the table, run the pipeline |
| User asks to save but no data | Tell user: "No leads found. Need to run the pipeline first" |
| Output CSV has fake data | Delete it. Re-run the pipeline |
| Can't find any lead data | Do NOT fabricate. Tell user honestly |
| Pipeline fails | Report the error, do not retry same command more than once |
| SearXNG engine fails / returns 0 | Pipeline auto-retries with next engine (Google→Yahoo→Mojeek→Yandex→Yelu.sg). No manual intervention needed. |

## Append to Existing CSV — CRITICAL

When user says "add more leads to existing file" or "add [N] more leads to [filename]":

**DO NOT create a new file. Load the existing file first, then generate NEW leads, then merge.**

### Step 1 — Read the existing file:
```tool_json
{"tool":"read","parameters":{"path":"/root/.openclaw/workspace/leads/[EXISTING_FILE].csv"}}
```

### Step 2 — Run pipeline with a higher target to get NEW companies:
- The pipeline script will search and produce a fresh CSV
- Keep track of company names already in the existing file

### Step 3 — Write the ADDITIONAL leads to a separate "_additional" file:
File naming: `sg_leads_[INDUSTRY]_additional_[DDMMYYYY].csv`

```tool_json
{"tool":"exec","parameters":{"command":"python3 -c \"\nimport csv, sys\nexisting = set()\nwith open('/root/.openclaw/workspace/leads/[EXISTING].csv', encoding='utf-8-sig') as f:\n    existing = {r['company_name'].strip().lower() for r in csv.DictReader(f)}\nnew_rows = []\nwith open('/root/.openclaw/workspace/leads/[PIPELINE_OUTPUT].csv', encoding='utf-8-sig') as f:\n    for r in csv.DictReader(f):\n        if r['company_name'].strip().lower() not in existing:\n            new_rows.append(r)\nif not new_rows:\n    print('No new leads found')\n    sys.exit(0)\nwith open('/root/.openclaw/workspace/leads/[ADDITIONAL].csv', 'w', newline='', encoding='utf-8-sig') as f:\n    w = csv.DictWriter(f, fieldnames=new_rows[0].keys())\n    w.writeheader()\n    w.writerows(new_rows)\nprint(f'Wrote {len(new_rows)} new leads')\n\" 2>&1"}}
```

**NEVER overwrite the original file.**

### Anti-duplication check:
Before writing, verify against the existing file. If a company name already exists, skip it. Report how many were skipped.

---

## Post-LeadGen Auto-Prompt Rules — CORRECT FLOW (v2)

**MANDATORY ORDER: sg-leadgen → dedup (default) → sg-verify → sg-enrich (ACRA) → sg-verify → dedup (mirae) → outreach**

After presenting leadgen results, ALWAYS suggest verification FIRST, THEN enrichment, THEN verify AGAIN (newly discovered emails), THEN re-score with Mirae model, THEN outreach.

**Mandatory completion message after leadgen:**
```
✅ Lead generation complete!

[Results here — email-having leads listed first, then phone-only]

📊 Summary:
- [N] leads with email addresses
- [N] leads with phone only (need enrichment to find emails + decision makers)

🔜 NEXT STEP — Enrich for decision makers + missing emails:
sg-enrich will scrape each company's website for:
• Decision maker names and titles
• Direct email addresses
• Intent signals (hiring, expansion, tech stack)

⚠️ BATCH LIMITS (hard-coded for stability):
- Contact enrichment: 10 leads per batch
- Intent enrichment: 5 leads per batch
- NEVER exceed these — the Telegram bot will freeze

Run sg-enrich now on batch 1 (leads 1–10)? (yes/no)
After all batches are done → run sg-verify on ALL emails collected.
```

**If the user says "yes" or "run enrich" or anything affirmative:**
1. Read sg-enrich SKILL.md FIRST (ALWAYS — batch commands are there)
2. Start with contact enrichment batches of 10:
   - Batch 1: `--limit 10 --offset 0`
   - Batch 2: `--limit 10 --offset 10`
   - Batch 3: `--limit 10 --offset 20`
3. After each batch completes, IMMEDIATELY prompt: "Batch N done. Run batch N+1? (yes/no)"
4. Keep going until ALL leads are enriched
5. Only after ALL batches done: "All enrichment complete. Run sg-verify on all emails now?"

**After ALL enrichment batches are complete — run sg-verify:**
```
✅ Enrichment complete for all [N] leads!

Now verifying all emails (original + newly found from enrichment)...

⚠️ Verify in batches of 5 (deep mode). Never >10 per batch.
```

**If the user skips enrichment and asks to verify directly:**
Proceed with verify, but remind: "Note: [N] phone-only leads didn't get enriched. Run sg-enrich after to find their emails and decision makers."

---

## OpenClaw Stability Notes — HARD LIMITS

| Operation | Batch size | Time per lead | Notes |
|-----------|-----------|---------------|-------|
| sg-leadgen | 25 max | ~3s | Single blocking exec (~30-60s total) |
| sg-enrich contacts | **10 max** | ~6-9s | NEVER exceed 10 — bot freezes |
| sg-enrich intent | **5 max** | ~30-60s | NEVER exceed 5 — bot freezes |
| sg-verify | **5 deep / 10 fast** | ~2-3s | Never >10 |
| Outreach | Any | <5s | Safe as single exec |

**MANDATORY PIPELINE ORDER (v2):**
`sg-leadgen (25 max) → dedup_score --mode default → sg-verify (5/batch) → sg-enrich contacts --acra (10/batch) → sg-verify (5/batch) → dedup_score --mode mirae → sg-outreach sequences → send (dry-run first)`

**NEVER run enrichment on >10 leads in a single exec call. The Telegram bot will appear to freeze.**

---

## Quick Command Reference

```
/sg-leadgen start [industry]
/sg-leadgen start [industry] --target [N]
```
