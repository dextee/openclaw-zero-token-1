# AI Assistant Rules — This Machine

> **READ BEFORE TOUCHING ANYTHING.** Applies to Claude Code, Kimi Code, Qwen Code, and any other AI coding assistant working in this environment.

---

## 1. Environment

- **OS:** Ubuntu 24.04 inside an XRDP remote desktop session
- **Display:** Xorg on `:10` — NOT `:0`, NOT unset
- **Shell `$DISPLAY`:** Terminal shells do NOT inherit `$DISPLAY` — set it explicitly for every GUI command
- **User:** root
- **Node:** v22.22.2, use `pnpm` (NOT `npm`)
- **Python:** python3 — deps managed with `pip install`

---

## 2. Chrome CDP

OpenClaw authenticates AI providers via browser cookies over Chrome DevTools Protocol.

### Correct launch command (from terminal):
```bash
DISPLAY=:10 XAUTHORITY=/root/.Xauthority /opt/google/chrome/google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/root/.config/chrome-openclaw-debug \
  --no-first-run \
  --no-default-browser-check \
  --disable-background-networking \
  --disable-sync \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --remote-allow-origins='*' \
  > /tmp/chrome-debug.log 2>&1 &
```

### Hard rules:
- Profile MUST be `/root/.config/chrome-openclaw-debug` — this has the AI provider cookies
- NEVER use `/tmp/chrome-debug-profile` — throwaway profile, no cookies
- ALWAYS set `DISPLAY=:10 XAUTHORITY=/root/.Xauthority` — no display = Chrome dies silently
- Desktop shortcut `/root/Desktop/Chrome-Debug.desktop` already has correct flags — double-click works in XRDP

### Check status:
```bash
curl -s http://127.0.0.1:9222/json/version      # CDP responding
pgrep -f "chrome.*remote-debugging-port=9222"   # process running
```

---

## 3. OpenClaw Project

**Location:** `/root/openclaw-zero-token`
**Version:** 2026.3.28

### Active config (ONLY this one — not `~/.openclaw/openclaw.json`):
`/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json`

### Gateway management:
```bash
cd /root/openclaw-zero-token
./server.sh start|stop|restart|status
```
- Gateway port: **3001**
- Web UI: `http://127.0.0.1:3001/#token=62b791625fa441be036acd3c206b7e14e2bb13c803355823`
- Startup log: `/tmp/openclaw-upstream-gateway.log`
- Runtime log: `/tmp/openclaw/openclaw-YYYY-MM-DD.log`

### AI models configured:
- Primary: `deepseek-web/deepseek-v4`
- Fallbacks: `deepseek-web/deepseek-chat` → `deepseek-web/deepseek-reasoner` → `qwen-web/qwen3.5-plus` → `qwen-web/qwen3.6-plus`
- Model provider auth: browser cookies via CDP (zero-token mode — no API keys)
- Auth profiles: `.openclaw-upstream-state/agents/main/agent/auth-profiles.json`

### Telegram bot:
- Bot: `@miraeclawbot`
- Token: set in `.env` and config — DO NOT change
- Whitelist: `/root/.openclaw/credentials/telegram-default-allowFrom.json`
- Allowed IDs: 280451401, 498391262, 5996214874, 8667886270

### Skills (all verified working):
| Skill | Path | Purpose |
|-------|------|---------|
| sg-leadgen | `/root/openclaw-zero-token/skills/sg-leadgen/` | SG B2B lead generation |
| sg-enrich | `/root/openclaw-zero-token/skills/sg-enrich/` | Lead enrichment + intent signals |
| sg-verify | `/root/openclaw-zero-token/skills/sg-verify/` | Email DNS+SMTP verification |

- Port 25 is **OPEN** — full SMTP verification works
- All Python deps installed: `requests`, `bs4`, `dnspython`, `tqdm`, `colorama`, `lxml`

### OpenClaw agent workspace:
- **Single canonical path:** `~/.openclaw/workspace` — this is what the gateway reads
- **DO NOT use** `~/.openclaw-zero/workspace` — stale duplicate, no longer in use
- Files: `SOUL.md`, `AGENTS.md`, `USER.md`, `IDENTITY.md`, `HEARTBEAT.md`, `TOOLS.md`, `persona.md`
- Edit files directly here. Changes are live immediately (gateway reads on each request).

### Leads output:
- **Canonical path:** `/root/.openclaw/workspace/leads/`
- All pipeline scripts write here. All SKILL.md files reference this path.

---

## 4. Tool Calling Architecture

### How it works (DeepSeek / Claude web models):
1. User sends Telegram message
2. `web-stream-middleware.ts` prepends `IDENTITY_PREFIX + tool_prompt` to the user message
3. Model responds with a `tool_json` block (bare JSON, no markdown fence needed)
4. Middleware detects the JSON, executes the tool (`exec`, `read`, `write`, etc.)
5. Result is fed back to the model as: `Tool <name> returned: <result>\nContinue the task...`
6. Tool re-injection is always applied on tool result feedback (`isToolResult = true`)
7. Multi-step chains work: `read SKILL.md → exec pipeline → read CSV → final answer`

### Tool format (DeepSeek/Claude injected tools):
```json
{"tool":"exec","parameters":{"command":"python3 /path/to/script.py","background":true}}
{"tool":"read","parameters":{"path":"/absolute/path/to/file"}}
{"tool":"write","parameters":{"path":"/absolute/path","content":"..."}}
```

### Key source files:
- `src/zero-token/tool-calling/web-stream-middleware.ts` — detects + executes tool calls, feeds results back
- `src/zero-token/tool-calling/web-tool-prompt.ts` — builds the injected tool prompt per model
- `src/zero-token/tool-calling/web-tool-defs.ts` — tool definitions JSON

### After any TypeScript change:
```bash
cd /root/openclaw-zero-token && pnpm build && ./server.sh restart
```

---

## 5. Qwen Web vs DeepSeek — Tool Calling Behaviour

This is critical and caused production bugs. Understand before doing anything with the bot.

### Qwen web (`qwen-web/*`) — native tool system:
Qwen's browser interface has its own tools: `web_search`, `web_extractor`, `code_interpreter`, `image_search`.

When OpenClaw injects `exec`/`read`/`write` via prompt, Qwen's runtime intercepts and returns **"Tool X does not exists"**.

**On Qwen web, the agent MUST use:**
- Read files → `code_interpreter` with `open('/path/to/file').read()`
- Run commands → `code_interpreter` with `subprocess.run([...])`
- Web search → `web_search`

### DeepSeek web (`deepseek-web/*`) — OpenClaw injected tools:
DeepSeek does NOT have a conflicting native tool system. OpenClaw's prompt injection works correctly.

**On DeepSeek web, the agent uses:**
- Read files → `{"tool":"read","parameters":{"path":"/absolute/path"}}`
- Run commands → `{"tool":"exec","parameters":{"command":"..."}}`
- Web search → `{"tool":"web_search","parameters":{"query":"..."}}`

---

## 6. Absolute Rules (Never Break)

1. **NEVER run `openclaw doctor --fix`** — destroys config
2. **NEVER change the Telegram bot token or channel config** — already correct
3. **NEVER use `/tmp/chrome-debug-profile`** for Chrome — no cookies, wrong profile
4. **NEVER use `~/.openclaw/openclaw.json`** as active config — it's stale
5. **NEVER automate `onboard.sh webauth`** — interactive wizard, needs a human in the XRDP session
6. **NEVER launch Chrome without `DISPLAY=:10`** — no other display exists
7. **NEVER manually add entries to `models.providers`** — providers are auto-discovered from browser auth
8. **NEVER read Chrome cookies via CDP websocket from terminal** — times out, use `onboard.sh webauth`
9. **NEVER run `npm`** — this project uses `pnpm`
10. **NEVER use `npx openclaw`** — use `node openclaw.mjs <args>`
11. **NEVER run `node openclaw.mjs gateway` directly** — always use `./server.sh start` (loads `.env` and correct state dir)
12. **NEVER write leads to `/tmp/` or any path other than `/root/.openclaw/workspace/leads/`**
13. **NEVER edit workspace files in `~/.openclaw-zero/workspace/`** — that directory is a stale duplicate

---

## 7. Current State (verified 2026-04-21)

| Component | Status |
|-----------|--------|
| Chrome CDP (port 9222) | Running — profile: `/root/.config/chrome-openclaw-debug` |
| Gateway (port 3001) | Running — `deepseek-web/deepseek-v4` as primary model |
| Telegram bot @miraeclawbot | Live — 4 users whitelisted |
| Qwen auth | Authenticated — `qwen-web:default` in auth-profiles.json |
| DeepSeek auth | Authenticated — `deepseek-web:default` in auth-profiles.json |
| sg-leadgen | Working — search fallback: Yellow Pages SG + Startpage (SearXNG not installed) |
| sg-enrich | Working — DM extraction fixed (2-word minimum, expanded reject list) |
| sg-verify | Working — port 25 open, full SMTP verification |
| GitHub CLI | Authenticated as `dextee` |
| Desktop shortcut | Working — `/root/Desktop/Chrome-Debug.desktop` |
| SearXNG | Installed from source on :8080 — Bing, DDG, Startpage, Brave, Qwant active |
| Workspace | Single canonical path: `~/.openclaw/workspace` |
| Leads output | `/root/.openclaw/workspace/leads/` |

---

## 8. Key File Map

| File | Purpose |
|------|---------|
| `/root/CLAUDE.md` | This file — rules for Claude Code and all AI coding assistants |
| `/root/AGENTS.md` | Identical copy — for Kimi Code, Qwen Code, etc. |
| `/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json` | Active OpenClaw config |
| `/root/openclaw-zero-token/.env` | Environment variables (Telegram token, etc.) |
| `/root/openclaw-zero-token/.openclaw-upstream-state/agents/main/agent/auth-profiles.json` | Browser auth credentials |
| `/root/.openclaw/credentials/telegram-default-allowFrom.json` | Telegram user allowlist |
| `/root/.openclaw/workspace/SOUL.md` | Bot personality + tool rules per model |
| `/root/.openclaw/workspace/AGENTS.md` | Bot workflows + absolute paths (read by bot) |
| `/root/.openclaw/workspace/USER.md` | User profile |
| `/root/.openclaw/workspace/leads/` | All lead CSV output files |
| `/root/openclaw-zero-token/src/zero-token/tool-calling/web-stream-middleware.ts` | Core tool call detection + multi-step chaining |
| `/root/openclaw-zero-token/src/zero-token/tool-calling/web-tool-prompt.ts` | Tool prompt injected into each bot message |
| `/root/openclaw-zero-token/skills/sg-leadgen/scripts/run_full_pipeline.py` | Lead generation pipeline |
| `/root/openclaw-zero-token/skills/sg-leadgen/scripts/dedup_score.py` | Deduplication + scoring |
| `/root/openclaw-zero-token/skills/sg-enrich/scripts/enrich_contacts.py` | Contact/DM enrichment |
| `/root/openclaw-zero-token/skills/sg-verify/scripts/verify_emails.py` | Email verification |
| `/root/Desktop/Chrome-Debug.desktop` | Chrome launcher shortcut (correct flags) |
| `/tmp/openclaw-upstream-gateway.log` | Gateway startup log |
| `/tmp/openclaw/openclaw-YYYY-MM-DD.log` | Gateway runtime log |
| `/root/openclaw-zero-token/server.sh` | Gateway management script |
| `/root/openclaw-zero-token/onboard.sh` | Auth onboarding (interactive — needs XRDP session) |

---

## 9. Common Tasks

### Restart everything after a reboot:
```bash
# 1. Start Chrome with correct profile and display
DISPLAY=:10 XAUTHORITY=/root/.Xauthority /opt/google/chrome/google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/root/.config/chrome-openclaw-debug \
  --no-first-run --no-default-browser-check \
  --disable-background-networking --disable-sync \
  --no-sandbox --disable-dev-shm-usage --disable-gpu \
  --remote-allow-origins='*' > /tmp/chrome-debug.log 2>&1 &

# 2. Wait and verify CDP is responding
sleep 6 && curl -s http://127.0.0.1:9222/json/version

# 3. Start gateway
cd /root/openclaw-zero-token && ./server.sh start
```

### Add a new model to the fallback chain:
Edit `.openclaw-upstream-state/openclaw.json` → `agents.defaults.model.fallbacks` array, then `./server.sh restart`.

### Add a Telegram user to allowlist:
Edit `/root/.openclaw/credentials/telegram-default-allowFrom.json`, add user ID as a string, then `./server.sh restart`.

### Capture new browser auth (when model expires):
Open XRDP session → Chrome should be running → log into provider's website → run:
```bash
cd /root/openclaw-zero-token && ./onboard.sh webauth
```
Select the provider. This is interactive — cannot be automated.

### Edit bot workspace files:
```bash
# Edit directly — no syncing needed
nano ~/.openclaw/workspace/SOUL.md
nano ~/.openclaw/workspace/AGENTS.md
# Changes are live immediately
```

### After any TypeScript source change:
```bash
cd /root/openclaw-zero-token
pnpm build
./server.sh restart
```

---

## 10. Patch Notes

### 2026-04-21 (v10) — Sender name prompt + SMTP tuple bug fix

**Sender name prompt hardening**

Root cause: The bot was asking for sender_email, sender_title, and sender_company even though these are always the same for this deployment. Users found it repetitive. Also, there was no validation that sender_name was actually filled before sending, leading to emails with missing signatures or raw `{{sender_name}}` placeholders.

Fixes:
1. **Bot now asks ONLY for `sender_name`** — email, title, and company use hardcoded defaults
   - `sender_title` default: `"Business Development"`
   - `sender_company` default: `"Mirae Advisory"`
   - `sender_email` falls back to sender script config automatically
2. **`generate_sequences.py` hard stop** — exits with code 1 if `--sender-name` is empty
3. **`validate_sequences.py` (new)** — pre-send validator checks for empty sender_name and unfilled `{{placeholders}}`
4. **Both senders have pre-send validation gate** — blocks send if sender_name is empty or placeholders remain
5. **SKILL.md + SOUL.md updated** — bot instructions now say "ask for sender_name ONLY"

**`workspace_smtp_sender.py` tuple unpacking bug**

Root cause: `create_message()` returned `(msg, msg_id)` — a tuple — but `send_email_smtp()` assigned the return value to a single variable `msg`, then called `msg.as_bytes()` on the tuple. This caused `AttributeError: 'tuple' object has no attribute 'as_bytes'`.

Additionally, `send_email_smtp()` signature only accepted 6 arguments, but `send_sequences_from_csv()` called it with 7 arguments (`parent_message_id`), which would cause `TypeError`.

Fix:
- `send_email_smtp()` now unpacks: `msg, msg_id = create_message(...)`
- Added `parent_message_id: str = ""` parameter to `send_email_smtp()`
- Return value now uses the unpacked `msg_id` instead of `msg["X-SG-Outreach-Id"]`

Files changed:
- `skills/sg-outreach/scripts/generate_sequences.py` — sender_name required, other fields default
- `skills/sg-outreach/scripts/validate_sequences.py` — new pre-send validator
- `skills/sg-outreach/scripts/workspace_smtp_sender.py` — tuple unpack fix, pre-send validation
- `skills/sg-outreach/scripts/gmail_sender.py` — pre-send validation
- `skills/sg-outreach/SKILL.md` — sender prompt workflow simplified, one-off sends banned
- `~/.openclaw/workspace/SOUL.md` — bot behavior rule updated

---

### 2026-04-21 (v10.1) — Wrong template sent + deliverability fix

**Root cause 1: Bot composed its own email instead of using the financing template**

When the user asked to "send an email to design@dexterng.asia", the bot asked for sender_name ("Vincent"), then composed its own subject/body instead of using `generate_sequences.py`:
- Subject: "Quick question about design financing" (spammy, not from template)
- Body: "Hi,\n\nI noticed your design work..." (generic AI-generated copy, not the financing template)

This happened because SKILL.md had a `--to --subject --body` one-off send example that allowed the bot to write custom copy. DeepSeek V4 "helpfully" wrote its own email.

Fix:
- **Banned custom one-off sends** in SKILL.md. The bot must ALWAYS create a mini CSV → run `generate_sequences.py` → send from sequences.
- Added explicit WRONG/CORRECT examples showing `--to --subject --body` is forbidden.
- Added hard rule in SOUL.md: "NEVER compose email subject or body yourself."

**Root cause 2: Email went to spam**

Multiple factors:
1. **Missing DKIM** for miraeadvisory.com — no cryptographic signature, Gmail treats as unauthenticated
2. **Spammy subject line** — "Quick question about design financing" triggers filters ("Quick question" is a known spam opener)
3. **Generic body** — short, no first name, no value prop depth, no calendar link
4. **DMARC policy p=none** — tells receivers to ignore auth failures

Fix:
- `deliverability_check.py` (new) — checks SPF/DKIM/DMARC/MX and gives actionable fixes
- Updated SKILL.md with deliverability section

**DNS action required by user:**
1. Enable DKIM in Google Workspace Admin: Admin → Apps → Google Workspace → Gmail → Authenticate email → Generate new record
2. Add `include:_spf.google.com` to SPF record (or switch to `include:_spf.google.com ~all`)
3. Add DMARC reporting: `v=DMARC1; p=quarantine; rua=mailto:admin@miraeadvisory.com`

Files changed:
- `skills/sg-outreach/SKILL.md` — banned custom one-off sends, added deliverability section
- `skills/sg-outreach/scripts/deliverability_check.py` — new
- `~/.openclaw/workspace/SOUL.md` — NEVER compose email copy rule

---

### 2026-04-21 (v10.2) — One-off send fix + DeepSeek native tool block

**Root cause 1: One-off sends generated full sequences**

When the user said "send an email" (singular), the bot generated a full multi-email sequence (3-5-7 emails depending on tier) with staggered `send_delay_days`. The sender then reported "No emails due today" because follow-ups were scheduled for future dates. The user only wanted to send Email #1 (the financing template with 2 rotating subjects).

Fix:
- Added `--single` flag to `generate_sequences.py` — generates ONLY email #1, sets `send_delay_days=0`
- Updated SKILL.md and SOUL.md to use `--single` for one-off sends
- No follow-ups, no scheduling delays — sends immediately

**Root cause 2: DeepSeek V4 using native tools instead of OpenClaw tools**

DeepSeek V4 has native `code_interpreter`, `web_search`, and `web_extractor` tools. When the user asked for the email template, DeepSeek used its native `code_interpreter` to list workspace files, didn't find a template there (templates are in the skill directory), and then asked the user for template content — completely bypassing the OpenClaw `read` tool and sg-outreach/SKILL.md workflow.

Fix:
- Added DeepSeek-specific tool prompt (`DEEPSEEK_TEMPLATE`) in `web-tool-prompt.ts`
- Explicitly forbids native DeepSeek tools: "Do NOT use DeepSeek native tools. They cannot access the local filesystem."
- Forces DeepSeek to use ONLY OpenClaw injected tools: read, exec, write
- Built with `pnpm build`, gateway restarted

Files changed:
- `skills/sg-outreach/scripts/generate_sequences.py` — `--single` flag
- `skills/sg-outreach/SKILL.md` — one-off send workflow updated
- `~/.openclaw/workspace/SOUL.md` — Rule 4 added (never answer conversationally about emails)
- `src/zero-token/tool-calling/web-tool-prompt.ts` — DeepSeek template
- `src/zero-token/tool-calling/web-stream-middleware.ts` — built into dist

---

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

### 2026-04-21 (v8) — sg-outreach global deduplication + suppression list

**Root cause:** The outreach system had no memory across campaigns. Each `sg_sequences_*.csv` was isolated. Users could accidentally re-contact the same leads, and unsubscribed prospects had no permanent protection.

**Fixes implemented:**

1. **Global outreach history** (`outreach_history.py`)
   - Central JSON database: `.outreach_history.json`
   - Tracks every email contacted: first_sent_at, last_sent_at, campaigns[], status, email_count, reply_sentiment
   - Permanent suppression for: `unsubscribed`, `bounced`, `blacklisted`

2. **Pre-generation duplicate check** (`generate_sequences.py`)
   - Before generating sequences, checks global history
   - Skips already-contacted leads with warning
   - Skips suppressed leads with red alert
   - Records new leads as `pending` in history
   - New flags: `--campaign-name`, `--skip-history-check`

3. **Pre-send duplicate check** (both `workspace_smtp_sender.py` and `gmail_sender.py`)
   - Before sending each email, checks if already sent in history
   - Alerts user with count of skipped duplicates and suppressed emails
   - Updates history to `sent` or `failed` after each attempt

4. **Auto-suppression on reply tracking** (`outreach_tracker.py`, `workspace_imap_tracker.py`)
   - "unsubscribe", "stop", "remove me" replies → permanent suppression
   - Negative sentiment replies → permanent suppression
   - No manual intervention needed

5. **Lead deduplicator script** (`lead_deduplicator.py`)
   - Previously referenced in SKILL.md but did not exist
   - Compares new leads CSV against all previous `sg_sequences_*.csv` files
   - Also checks global history and suppression list
   - Reports: suppressed, in-history, duplicate-email, duplicate-company

**Production workflow updated in SKILL.md:**
`deduplicate → generate → dry-run → send → track replies → report`

Files changed:
- `skills/sg-outreach/scripts/outreach_history.py` — new
- `skills/sg-outreach/scripts/lead_deduplicator.py` — new
- `skills/sg-outreach/scripts/generate_sequences.py` — history integration
- `skills/sg-outreach/scripts/workspace_smtp_sender.py` — history integration
- `skills/sg-outreach/scripts/gmail_sender.py` — history integration
- `skills/sg-outreach/scripts/outreach_tracker.py` — auto-suppress
- `skills/sg-outreach/scripts/workspace_imap_tracker.py` — auto-suppress
- `skills/sg-outreach/SKILL.md` — dedupe docs, workflow, suppression rules

---

### 2026-04-21 (v7) — End-to-end pipeline workflow hardening

**Leadgen capped at 25 leads default**

Root cause: The bot was generating large lead lists that became unwieldy to verify and enrich in batches. Users were getting 50+ leads with unverified emails and attempting outreach immediately.

Fix: sg-leadgen SKILL.md now enforces a 25-lead default target. The bot only exceeds 25 if the user explicitly asks for more, and warns about batch processing overhead.

**sg-verify batch size reduced to 5 (deep mode) / 10 (fast mode)**

Root cause: Previous guidance said up to 30 per batch was "safe", but this meant 1-3 minutes of silent processing. Telegram users assumed the bot froze. Large batches also reduced SMTP accuracy due to concurrent connections.

Fix: New batch size standard:
- 5 per batch = deep verification (default, recommended)
- 10 per batch = fast mode (acceptable)
- Absolute max: 10. Never exceed 10.

**Triple-check analysis after sg-verify**

Root cause: After verification, the bot was giving a generic "Next step: run sg-enrich" message. It was not analyzing the actual verification results to give specific guidance (e.g., "60% failed — find better emails first" vs "90% verified — ready for outreach").

Fix: sg-verify SKILL.md now requires the bot to analyze verification stats and write a contextual recommendation:
- ≥60% verified → "Strong list, ready for outreach"
- 30-59% verified → "Moderate quality, consider pattern regeneration or enrichment"
- <30% verified → "Poor quality, do NOT outreach, find better emails first"

**Verify-twice rule introduced**

Root cause: sg-enrich contacts discovers NEW emails from websites and search. These emails were never being verified. Users were adding unverified scraped emails to their outreach lists.

Fix: New mandatory rule in sg-enrich SKILL.md and SOUL.md:
1. Verify after leadgen (initial emails)
2. Verify AGAIN after contact enrichment (newly discovered emails)
The bot MUST suggest the second verify in every enrichment completion message.

**Pipeline order corrected: leadgen → verify → enrich → verify → outreach**

Root cause: SOUL.md and SKILL.md showed `sg-leadgen → sg-enrich → sg-verify` as the pipeline. This encouraged enrichment before verification.

Fix: All docs now show the correct order:
`sg-leadgen → sg-verify → sg-enrich → sg-verify → outreach`

Files changed:
- `skills/sg-leadgen/SKILL.md` — 25-lead cap, verify-first auto-prompt
- `skills/sg-verify/SKILL.md` — 5/10 batch sizes, triple-check analysis, batch slicing helper
- `skills/sg-enrich/SKILL.md` — verify-twice rule, mandatory post-enrichment verify prompt
- `~/.openclaw/workspace/SOUL.md` — mandatory pipeline flow rules

---

### 2026-04-21 (v5) — SearXNG installation + pipeline quality fixes

**SearXNG installed from source**

Root cause: SearXNG was not installed on this VPS. The sg-leadgen pipeline was relying entirely on fallback search backends (Mojeek → DuckDuckGo → Yellow Pages SG → Startpage), yielding ~10–20 raw results per query.

Fix: Cloned official SearXNG repo to `/opt/searxng/src`, installed in Python venv at `/opt/searxng/venv`, created systemd service `searxng.service` on port 8080.

Engine configuration:
- Enabled: Bing, DuckDuckGo, Startpage, Brave, Qwant
- Disabled: Google (CAPTCHA-prone on VPS IPs)
- JSON API format enabled for sg-leadgen pipeline consumption

Result: Pipeline now returns 150–200+ raw results per query.

**Chinese tutorial/Q&A sites blocked from lead results**

Root cause: `baidu.com`, `zhihu.com`, `runoob.com`, `csdn.net` results were passing through `is_low_quality_result()` and becoming saved as companies.

Fix: Added all four domains to `LOW_QUALITY_DOMAIN_PATTERNS` in `run_full_pipeline.py`.

**Telegram whitelist path fixed**

Root cause: `telegram-default-allowFrom.json` only existed in the stale backup directory (`~/.openclaw.stale.backup-20260420-191906/credentials/`).

Fix: Copied to canonical path `/root/.openclaw/credentials/telegram-default-allowFrom.json`.

Files changed:
- `skills/sg-leadgen/scripts/run_full_pipeline.py` — baidu, zhihu, runoob, csdn filters
- `/opt/searxng/settings.yml` — SearXNG engine config
- `/etc/systemd/system/searxng.service` — SearXNG systemd service
- `/root/.openclaw/credentials/telegram-default-allowFrom.json` — whitelist copied to canonical path

---

### 2026-04-21 (v6) — sg-enrich directory email pollution fix

**`enquiry@yelu.sg` was being assigned to unrelated companies**

Root cause: When sg-leadgen could not find an actual company website on yelu.sg, it saved the yelu.sg profile URL as the lead website. When sg-enrich `enrich_contacts.py` later processed these leads, it extracted `enquiry@yelu.sg` from the directory page and assigned it to companies like "Century Awning Industrial" and "Precise Development".

Fix: Two changes to `enrich_contacts.py`:
1. `pick_best_email()` now filters out emails from directory domains (`yelu.sg`, `yellowpages.com.sg`, `kompass.com`, `dnb.com`) before selecting the best email.
2. Pattern email fallback now skips directory domains entirely (same logic already existed in sg-leadgen, but was missing in sg-enrich).

**Placeholder emails blocked**

Added `BLOCKED_EMAIL_PATTERNS` to reject obvious template emails like `user@domain.com`, `email@domain.com`, `test@test.com`.

Files changed:
- `skills/sg-enrich/scripts/enrich_contacts.py` — directory domain filtering + placeholder email rejection

---

### 2026-04-21 (v4) — enrich_contacts.py batch chunking + performance limits

**`--offset` parameter added to enrich_contacts.py**

Root cause: `enrich_contacts.py` had `--limit` but no `--offset`, making it impossible to process rows 11+ in a separate batch call. The bot would re-process the first N rows on every call, wasting time and token budget.

Fix: Added `--offset` parameter (same pattern as `enrich_leads.py`):
```python
parser.add_argument("--offset", type=int, default=0, help="Start at row N (0-based). Use with --limit for chunked batches.")
if args.offset > 0:
    rows = rows[args.offset:]
if args.limit > 0:
    rows = rows[:args.limit]
```

Bot can now process files of any size in safe 10-lead chunks:
- Batch 1: `--limit 10 --offset 0`
- Batch 2: `--limit 10 --offset 10`
- Batch 3: `--limit 10 --offset 20`

**Worker and page fetch limits tightened**

- Default workers: 4 → 3 (reduces concurrent HTTP load; stays well inside 300s gateway timeout)
- Workers capped at 4 max: `workers = min(args.workers, 4)`
- Standard contact paths probed per lead: 8 → 5 (`/contact`, `/contact-us`, `/about-us`, `/team`, `/leadership`)
- Discovered contact page cap: 6 → 4 pages per lead
- Per-lead worst-case time: ~60s (1 homepage + 5 standard + 4 discovered); with 3 workers, 10 leads ≈ 40–80s

**sg-enrich SKILL.md updated**

- Updated HARD BATCH SIZE LIMITS table with accurate timing
- Contact batch commands now use `--offset` instead of the old slicing workaround
- Added note: "Gateway hard kill: 300s. Keep all batches well under 240s to be safe."
- Per-lead timing breakdown documented

Files changed:
- `skills/sg-enrich/scripts/enrich_contacts.py` — `--offset` added, workers capped, paths reduced
- `skills/sg-enrich/SKILL.md` — batch commands and timing table updated

---

### 2026-04-21 (v3) — sg-leadgen non-.sg domain support + additional name quality fixes

**Non-.sg Singapore companies were being rejected**

Root cause: `is_likely_sg_company()` returned `False` as the default for any non-.sg domain unless name contained "Singapore" or "Pte Ltd". Many real SG companies use `.com`, `.net`, `.io`, `.co` etc.

Fix: Changed default to `return True` for neutral TLDs (`.com`, `.net`, `.io`, `.co`, `.biz`).
Added explicit block for non-SG country-code TLDs: `.in`, `.my`, `.ph`, `.id`, `.vn`, `.th`, `.au`, `.nz`, `.uk`, `.co.uk`, `.cn`, `.hk`, `.tw`, `.jp`, `.kr`, `.ca`, `.de`, `.fr`, `.nl`, `.se`, `.no`, `.dk`.
Result: Berjaya Buildcon (`.com`), CHH Construction (`.com`), Wee Hur (`.com`) now correctly included.

**Additional junk sources blocked**

Added to `LOW_QUALITY_DOMAIN_PATTERNS`:
- Job boards: `foundit.sg`, `jobstreet.com`, `jobscentral.com.sg`, `indeed.com`, `glassdoor.com`, `careerjet.sg`
- SG directories: `asiabuilders.com.sg`, `sgprocessindustries.com`, `scal.com.sg`, `timesdirectories.com`, `kompass.com`
- Research firms: `analysysmason.com`, `gartner.com`, `forrester.com`, `idc.com`
- Social/platforms: `twitter.com`, `x.com`, `facebook.com`, `instagram.com`, `youtube.com`, `tiktok.com`, `grab.com`
Added to `SOCIAL_DOMAINS`: `wa.link`, `wa.me`, `x.com`, `t.me`
Updated `is_valid_company_url()` to also block job boards/directories inline.

**Company name noise filters**

- Added whitespace collapse (`re.sub(r'\s+', ' ', ...)`) to catch tab/newline garbage from HTML
- Added URL-as-name rejection (`if text.startswith("http")`) — prevents bare URLs used as anchor text
- Added phone-number-as-name rejection (wa.link/wa.me style `+65 6977 9849` links)
- Added year pattern rejection: names containing `20XX` are article/report titles
- Added `"survey"`, `"whitepaper"`, `"case study"`, `"webinar"` to article keyword filter
- Extended `nav_titles` with: "Board of Directors", "Management Team", "Tweet", "Share", "Follow", "Login", "Sign In"
- Added `r"certified\s+firms?\b"`, `r"registered\s+firms?\b"`, `r"member\s+companies\b"` to LOW_QUALITY_TITLE_PATTERNS
- Added generic service noun phrase filter (3–6 words, all industry terms, no company identifier): catches "Digital Marketing Services", "IT Support Solutions", "Construction Management Services" while keeping 2-word brands like "Cloud Telecom"

All fixes applied to both the direct search results section and `extract_companies_from_listicle()`.

---

### 2026-04-21 (v2) — sg-leadgen company name quality fixes (initial pass)

**Bad company names and wrong website URLs — fixed in run_full_pipeline.py**

Issues found in production test (construction leads run):
1. `Holden (holden.com.sg)` / `Eurobuild (eurobuild.com.sg)` — domain appended in parentheses from page title
2. `Building capabilities; managing rentals` — page subtitle used as company name (semicolon = description)
3. `GGBS-Certified Firms (SCAL)` — association category entry, not a company
4. `China Communications Construction Co` with website `foundit.sg` — job board URL used as company website
5. `Singland` with `asiabuilders.com.sg` / `San-Q` with `sgprocessindustries.com` — directory URLs as company websites

Fixes applied to `skills/sg-leadgen/scripts/run_full_pipeline.py`:
- Strip domain-in-parentheses from company names: `re.sub(r'\s*\([a-z0-9][\w.-]*\.[a-z]{2,}\)', '', name)`
- Reject names containing semicolons (always a description, never a company name)
- Added `r"certified\s+firms?\b"`, `r"registered\s+firms?\b"`, `r"member\s+companies\b"` to `LOW_QUALITY_TITLE_PATTERNS`
- Added job boards to `LOW_QUALITY_DOMAIN_PATTERNS`: `foundit.sg`, `jobstreet.com`, `jobscentral.com.sg`, `indeed.com`, `linkedin.com`, `glassdoor.com`, `monster.com`, `careerjet.sg`
- Added SG industry directories to `LOW_QUALITY_DOMAIN_PATTERNS`: `asiabuilders.com.sg`, `sgprocessindustries.com`, `scal.com.sg`, `bca.gov.sg`, `kompass.com`
- Updated `is_valid_company_url()` to also block job boards and directories (prevents their profile URLs from becoming lead websites)
- Applied same domain-in-parentheses stripping and semicolon rejection in both loops of `extract_companies_from_listicle()`

---

### 2026-04-21 (v1) — enrich_contacts.py DM extraction fix + path cleanup

**Decision maker name garbage ("Appliances", "Honesty", "Staying") — fixed in enrich_contacts.py**

Root cause: `extract_decision_makers()` accepted single-word "names" (min word count was 1). HTML text lines containing title keywords were split on separators, and single words like "Appliances" or value statement words like "Honesty"/"Staying" passed the name validation because they started with a capital letter.

Fixes applied to `skills/sg-enrich/scripts/enrich_contacts.py`:
- Raised minimum word count from 1 → 2 in all three extraction paths (text, HTML pattern, JSON-LD)
- Raised maximum word count from 3 → 4 (allows "Mary Ann Lee Tan" style names)
- Expanded `DM_REJECT_WORDS` with garbage words seen in production: "appliances", "honesty", "staying", "integrity", "excellence", "innovation", "quality", "reliability", "transparency", "professionalism", "commitment", "beamp", "headquartered", "singapore", "academy", "institute", "university", "association", "chamber", "federation", "society", "council", "board", "redefining", "leading", "trusted", "award", "certified", "accredited", "established", "founded", "incorporated", "registered", "licensed"

**Stale path cleanup — all `.openclaw-zero/workspace/leads/` references removed**

All SKILL.md files and workspace files now consistently use the canonical path `/root/.openclaw/workspace/leads/`.

Files fixed:
- `skills/sg-enrich/SKILL.md`
- `skills/sg-verify/SKILL.md`
- `~/.openclaw/workspace/AGENTS.md`
- `~/.openclaw/workspace/persona.md`

**Tool prompt leads path fixed in web-tool-prompt.ts**

`EN_TEMPLATE` and `CN_TEMPLATE` had `Leads output: /root/openclaw-zero-token/leads/` — now correctly points to `/root/.openclaw/workspace/leads/`. Built with `pnpm build`, gateway restarted.

---

### 2026-04-20 — Multi-step tool calling fix + sg-leadgen repair + workspace consolidation

**Critical bug fixed: raw JSON appearing in Telegram**

Root cause: `web-stream-middleware.ts` had an early-return path for `toolResult` messages that called `streamFn()` directly, bypassing the tool call detection wrapper. After a first tool call executed (e.g. `read` SKILL.md), the model's follow-up tool call (e.g. `exec` pipeline) went straight to Telegram as raw text.

Fix: merged the `toolResult` path into the main flow. Tool results now re-inject the tool prompt (`injectTools = true` when `isToolResult`) and go through the same JSON detection + execution logic. Multi-step tool chains (`read → exec → read result → final answer`) now work correctly.

Files changed:
- `src/zero-token/tool-calling/web-stream-middleware.ts` — toolResult path now re-wraps with tool detection
- Built with `pnpm build`, gateway restarted

**SOUL.md rules strengthened**

Bot was outputting text before tool JSON (violating the one-message rule) and doing web searches before using sg-leadgen. Fixed with stronger, example-driven rules in SOUL.md.

Files changed:
- `~/.openclaw/workspace/SOUL.md` — Rules 1/2/3 rewritten with WRONG/CORRECT examples; added "ALWAYS show ALL rows — never truncate"

**sg-leadgen pipeline repaired — three bugs fixed:**

1. `dedup_score.py:normalize_domain` — `re.sub(r'/.*$', '')` was missing the string argument (TypeError at runtime)
2. `dedup_score.py` CSV reader — used `utf-8` encoding but pipeline writes `utf-8-sig` (BOM). First column key became `'\ufeffcompany_name'`, causing all company names to be blank in output
3. SearXNG hard dependency — SearXNG is not installed. Added automatic fallback chain: SearXNG (5s timeout) → Yellow Pages SG → Startpage

Additional improvements to `run_full_pipeline.py`:
- CSS/JS noise stripping from search result titles (Startpage embeds inline CSS)
- `@media` query stripping from company names
- Navigation page title rejection ("About Us", "Contact Us", etc.)
- All-caps promotional title rejection
- DM name minimum raised from 1 → 2 words (same fix as enrich_contacts.py)
- `DM_REJECT_WORDS` expanded with garbage words seen in production
- Phone/address fields now passed through from Yellow Pages search results
- Loan provider domains added to `LOW_QUALITY_DOMAIN_PATTERNS`
- Search queries include `-loan -lender -bank` exclusions to reduce noise

Files changed:
- `skills/sg-leadgen/scripts/dedup_score.py` — re.sub fix + utf-8-sig encoding fix
- `skills/sg-leadgen/scripts/run_full_pipeline.py` — search fallback chain + name cleaning + loan filters
- `skills/sg-leadgen/SKILL.md` — updated prerequisites, paths, all-rows rule

**Workspace consolidated to single canonical path**

Resolved dual-workspace confusion. Canonical path is `~/.openclaw/workspace` (per `src/agents/workspace.ts` default). The `~/.openclaw-zero/workspace` directory was a stale fork-time duplicate.

Files changed:
- `.openclaw-upstream-state/openclaw.json` — `workspace` key set to `~/.openclaw/workspace`
- `src/zero-token/tool-calling/web-tool-prompt.ts` — all path refs updated
- `~/.openclaw/workspace/AGENTS.md` — removed dual-workspace mirror instructions
- `/root/CLAUDE.md` and `/root/AGENTS.md` — updated to reflect single workspace

---

### 2026-04-09 — Initial setup and audit (see CLAUDE_CODE_BRIEF.md)

---

### 2026-04-21 (v11) — DeepSeek V4 tool calling hardening + single-email pipeline production-ready

**End-to-end single-email send verified working**
- Full pipeline test passed: create mini CSV → generate_sequences.py --single → validate → send → history updated correctly
- Email sent successfully to final-test@miraeadvisory.com with correct financing template

**Bug fixes found during audit:**

1. `was_already_sent()` blocked `pending` entries as duplicates
   - Root cause: campaign name check happened before status check. `generate_sequences.py` recorded `pending` with campaign name, then `workspace_smtp_sender.py` saw same campaign and skipped.
   - Fix: `outreach_history.py` now only blocks if status is `sent` or `replied`. `pending`/`failed` are allowed through.

2. `failed` status was permanent — successful retry never upgraded to `sent`
   - Root cause: `record_contact()` only upgraded `pending`→`sent`, not `failed`→`sent`.
   - Fix: `status == "sent"` now upgrades from both `pending` and `failed`.

3. Empty `sender_email` in sequences CSV caused SMTP rejection
   - Root cause: `generate_sequences.py` didn't auto-populate `sender_email` from config. `workspace_smtp_sender.py` used `.get("sender_email", email)` which returned empty string (key existed).
   - Fix: `generate_sequences.py` now reads `.workspace_smtp_config.json` email as fallback. `workspace_smtp_sender.py` uses `.strip() or email` for proper fallback.

**DeepSeek V4 tool calling hardening:**

4. `web-stream-middleware.ts` — context preservation for short replies
   - Problem: Web models see ONLY the last user message. When user replies "Dexter Ng", model has no idea it previously asked for sender name.
   - Fix: For short replies (≤40 chars), middleware prepends the bot's previous message: `Your previous message was: "..." The user replied: ...`

5. `web-stream-middleware.ts` — stronger multi-step continuation
   - Problem: Tool result feedback said "If another tool call is needed... Otherwise answer..." — models often chose "otherwise answer."
   - Fix: Changed to "Check if more steps remain. If yes, make the NEXT tool call immediately. Only answer when every required step is finished."

6. `web-tool-prompt.ts` — DeepSeek short-reply scenarios
   - Added explicit scenario mapping: person's name → sender name answer, yes/ok → confirmation, no → rejection, etc.
   - Added "NEVER stop in the middle of a multi-step workflow" rule.

7. `needsToolInjection()` — added outreach/email keywords
   - Added: `outreach`, `campaign`, `sequence`, `financing`, `template`, `email` to catch more email-related requests.

**Documentation fixes:**

8. `SOUL.md` — strengthened sender_name handling
   - Added explicit rule: "When user replies with just a name, DO NOT ask again. IMMEDIATELY proceed."
   - Added one-off send workflow with exact commands and `--single` emphasis.
   - Added "Always create a FRESH mini CSV. Never reuse existing /tmp/mini_*.csv files."
   - Removed hardcoded "Wei Xian" example.

9. `SKILL.md` — fixed inconsistencies
   - Fixed line 317: "Bot asks user for sender_name, sender_email, title, company" → corrected to sender_name ONLY.
   - Removed hardcoded "Vincent" and "Wei Xian" examples. Replaced with `<USER_PROVIDED_NAME>`.
   - Made `--single` more prominent in one-off send workflow.

**Build & deploy:**
- `pnpm build` completed successfully (exit 0)
- `./server.sh restart` completed — Gateway PID 547904, port 3001, health check `{"ok":true,"status":"live"}`

---

### 2026-04-22 (v13) — PRODUCTION: SearXNG engine crisis resolved; multi-engine round-robin with auto-fallback

**Problem:** SearXNG was returning only ~23 raw results per pipeline run. Of 13 enabled general engines, only Bing returned results — and Bing produced garbage (Chinese Q&A, foreign government docs) for all Singapore business queries. Startpage, DuckDuckGo, Brave, Qwant, and Karmasearch were all returning CAPTCHA or 403/429. Mojeek was disabled in SearXNG config.

**Root cause:** `searxng_search()` in `run_full_pipeline.py` requested `engines=google,duckduckgo,brave` — but Google was disabled in SearXNG config, DuckDuckGo was CAPTCHA'd, and Brave was rate-limited (429). The pipeline fell back to direct Mojeek scrape, DDG, and Yelu.sg, yielding very few results.

**Startpage status:** Completely IP-blocked on Contabo Asia Private. All endpoints (`startpage.com`, `startpage.de`, mobile) redirect to CAPTCHA. Even Chrome CDP gets CAPTCHA'd. Cannot be automated on this VPS without a proxy/VPN/Tor.

**Production discovery during testing:**
- Google via SearXNG works and supports full dorks (`site:`, `intitle:`, `inurl:`, `"exact phrase"`), BUT rate-limits after ~20-30 rapid queries (HTTP 429)
- Yahoo via SearXNG is the MOST RELIABLE engine — supports `site:`, `intitle:`, exact phrase, and tolerates sustained querying
- Yandex via SearXNG works but produces mixed quality (product pages, directions, placeholder sites)
- Mojeek via SearXNG always works but only returns directory listings
- Yelu.sg direct scrape is the MOST RELIABLE baseline source (always works, real SG companies)

**Fix — SearXNG settings (`/opt/searxng/settings.yml`):**
1. Enabled `google` (was disabled)
2. Enabled `mojeek` (was disabled)
3. Enabled `yahoo` (was disabled)
4. Enabled `yandex` (was disabled)
5. Increased `request_timeout: 3.0 → 10.0`
6. Uncommented `max_request_timeout: 15.0`

**Fix — `run_full_pipeline.py` — PRODUCTION architecture:**
7. **Pre-flight health check** (`check_searxng_health()`): Tests all engines with a ping query before starting. Reports working engines to user.
8. **Round-robin engine assignment** — each query is assigned a primary engine to spread load:
   - Dork queries (`site:.sg`, `intitle:`) → Yahoo primary, Google secondary
   - Standard queries → Yahoo primary, Mojeek fallback
   - `inurl:` dork → Yandex last resort
9. **Engine failure tracking** (`failed_engines` set): If an engine returns 0 results, it's skipped for remaining queries in the run.
10. **Progressive delays**: 3s between successful queries, 5s after failures (possible rate-limit).
11. **SearXNG-down resilience**: If ALL SearXNG engines fail, pipeline falls back to direct Mojeek scrape + Yelu.sg. Tested: produces 14/15 leads even with SearXNG completely stopped.
12. **Per-query logging** (`QUERY_METRICS` JSON): Each query logs engine used, result count, and latency — essential for production troubleshooting.
13. **Query set optimized** for high company-homepage yield (tested 2026-04-21):
    - `site:.sg {industry} company` → 5-7 leads
    - `site:.sg {industry} Pte Ltd` → 5 leads
    - `{industry} "Pte Ltd" Singapore` → 5-6 leads
    - `intitle:{industry} Singapore` → 5-6 leads
    - Removed low-yield listicle queries (`top`, `best`) that only produced 1-2 leads
14. `_yelu_sg_search()` expanded from 1 page → 3 pages (20 → 60 companies per category)
15. **Quality filters tightened** for production:
    - URL path filter: `/archives/`, `/tag/`, `/maps/`, `/directions/`, `/products/`
    - Deep-path filter: URLs with 3+ path segments on non-.sg domains are rejected unless title contains company identifier (Pte Ltd, Ltd, etc.)
    - Blocked academic journals: `academypublishing.org`, `springer.com`, `sciencedirect.com`, etc.
    - Blocked Singapore large conglomerates (not SME targets): `sembcorp.com`, `dbs.com.sg`, `singtel.com`, `keppel.com`, etc.
    - Title keyword expansion: `driving directions`, `under construction`, `temporary noise`, `experienced tilers`, etc.

**Verified dork support (via SearXNG):**
| Dork | Google | Yahoo | Yandex |
|------|--------|-------|--------|
| `site:.sg` | ✅ | ✅ | ✅ |
| `intitle:` | ✅ | ✅ | ⚠️ mixed |
| `inurl:` | ✅ | ❌ | ✅ |
| `"exact phrase"` | ✅ | ✅ | ✅ |

**Pipeline results (production verified across 3 industries):**
| Metric | Before | After (Google available) | After (Google rate-limited) |
|--------|--------|--------------------------|----------------------------|
| Raw results | ~23 | **118-140** | **100-120** |
| Unique leads built | ~15 | **38-43** | **30-50** |
| Final scored leads | ~15 | **21-25** | **21-25** |
| Primary source | Yelu.sg only | **Google + Yelu.sg** | **Yahoo + Yelu.sg** |

**Tested industries:** construction (25/25 leads), engineering (24/25 leads), manufacturing (5/5 leads — niche industry, fewer companies exist).

**SearXNG restart:** `sudo systemctl restart searxng` — confirmed active.

**Client handover notes:**
- Pipeline is fully autonomous — no manual engine selection needed
- If Google rate-limits, pipeline automatically switches to Yahoo/Mojeek/Yandex
- If SearXNG is completely down, Yelu.sg + direct Mojeek still produce leads
- QUERY_METRICS JSON in output enables troubleshooting without SSH access
- For niche industries (manufacturing, niche B2B), expect 5-15 leads instead of 25

---

### 2026-04-22 (v15) — Default model switched to DeepSeek V4 for all Telegram `/new`

**Change:** `agents.defaults.model.primary` in `.openclaw-upstream-state/openclaw.json` flipped from `qwen-web/qwen3.5-plus` to `deepseek-web/deepseek-v4`.

**New fallback chain:**
1. `deepseek-web/deepseek-v4` (primary)
2. `deepseek-web/deepseek-chat`
3. `deepseek-web/deepseek-reasoner`
4. `qwen-web/qwen3.5-plus`
5. `qwen-web/qwen3.6-plus`

**Why:** DeepSeek web supports OpenClaw's injected `exec`/`read`/`write` tool system natively. Qwen web has a conflicting native tool system (`web_search`, `code_interpreter`) that intercepts injected tools and returns "Tool X does not exist." DeepSeek V4 is the most reliable model for multi-step tool chains (read SKILL.md → exec pipeline → read CSV → final answer).

**Impact on `/new`:** When any Telegram user types `/new`, the session resets and the model resolves to the configured primary. It is now permanently `deepseek-web/deepseek-v4` regardless of what model the user was on before.

**Files changed:**
- `.openclaw-upstream-state/openclaw.json` — primary + fallback order
- `AGENTS.md` — Current State table updated

**Gateway restarted:** `./server.sh restart` — confirmed active on port 3001.

---

### 2026-04-22 (v14) — Audit-driven quality fixes: industry verification, SG signals, Bing/DDG disabled

**Audit by Kimi Code CLI identified 5 critical issues. All non-email-template fixes implemented.**

**1. Bing + DuckDuckGo disabled in SearXNG (`/opt/searxng/settings.yml`)**
- Bing was returning Chinese Q&A sites and Australian government pages for all SG business queries
- DuckDuckGo via SearXNG returned 0 results consistently
- Changes: `disabled: true` added to `bing`, `bing images`, `bing news`, `bing videos`, `duckduckgo`, `duckduckgo images`, `duckduckgo videos`, `duckduckgo news`
- Verified: restart `sudo systemctl restart searxng`, Yahoo still returns results

**2. Industry keyword verification added to `run_full_pipeline.py`**
- Root cause: `industry` column was always `args.industry` with zero website-content verification
- Fix: `detect_industry_from_html()` scans homepage HTML for claimed-industry keyword count
  - ≥3 occurrences → `industry_confidence: high`
  - 1-2 occurrences → `industry_confidence: medium`
  - 0 occurrences but alternative industry keywords match → `industry_confidence: medium` (detected_industry updated)
  - Nothing matches → `industry_confidence: low`
- `INDUSTRY_KEYWORDS` mapping covers: construction, engineering, logistics, manufacturing, fintech, IT, software, marketing, accounting, interior design
- New output columns: `industry_confidence` (high/medium/low), `detected_industry` (verified or alternative)

**3. Singapore signals detection for `.com`/`.io` domain verification**
- Root cause: `is_likely_sg_company()` returned `True` for ALL neutral TLDs (.com, .io, .net, .co, .biz) — US/UK startups could slip through
- Fix: `has_sg_signals()` scans homepage HTML for:
  - `+65` phone numbers (regex: `(?:\+65|65)\s*[\s\-]?[689]\d{3}[\s\-]?\d{4}`)
  - Singapore postal codes (`Singapore \d{6}`)
  - UEN/ACRA/BizFile mentions
- New output column: `sg_signals` (yes/no)
- **Pattern email fallback tightened**: `enquiry@domain.com` etc. are ONLY guessed if:
  - Domain ends with `.sg` or `.com.sg`, OR
  - Homepage HTML contains SG signals
  - Otherwise email is left blank (reduces foreign bounce risk)

**4. SearXNG API calls now include `language=en&safesearch=0`**
- Added to all SearXNG URLs in `check_searxng_health()` and `searxng_search()`
- Improves result relevance by requesting English-language results and disabling safe-search filtering

**5. `dedup_score.py` fieldnames updated**
- Added `industry_confidence`, `detected_industry`, `sg_signals` to output CSV schema
- `extrasaction='ignore'` preserved — backward compatible with old raw CSVs

**Files changed:**
- `/opt/searxng/settings.yml` — disable bing/bing-images/bing-news/bing-videos/duckduckgo/DDG-images/DDG-videos/DDG-news
- `skills/sg-leadgen/scripts/run_full_pipeline.py` — industry verification, SG signals, language/safesearch params, tightened email fallback
- `skills/sg-leadgen/scripts/dedup_score.py` — new fieldnames
- `skills/sg-leadgen/SKILL.md` — updated column list and SearXNG engine description

**Outreach template left unchanged** per user instruction.

**End-to-end verification (2026-04-22):**
| Industry | Target | Final | Sources | New Columns |
|---|---|---|---|---|
| Construction | 10 | 10 | Yahoo, Yelu.sg | `industry_confidence=high` on all; `sg_signals=yes/no` correct |
| Engineering | 10 | 10 | Yelu.sg, Mojeek direct | Empty new columns (Yelu leads lack URLs) — expected |
| Fintech | 15 | 5 | Yahoo | Critical: `.com` domains with `sg_signals=no` correctly blocked from pattern email fallback |
| Logistics | 15 | 15 | Yelu.sg, Yahoo | Empty new columns on no-URL Yelu leads — expected |

**Tightened email fallback — verified on live domains:**
| Domain | TLD | SG Signals | Fallback? | Result |
|---|---|---|---|---|
| `capc.com.sg` | .sg | yes | ✅ | `enquiry@capc.com.sg` |
| `ftall.sg` | .sg | yes | ✅ | `enquiry@ftall.sg` |
| `satfintech.com` | .com | no | ❌ | Real email extracted from HTML (not guessed) |
| `broadchainsfintech.com` | .com | no | ❌ | Left blank ✅ |
| `pivotfintech.com` | .com | no | ❌ | Left blank ✅ |

**Known behaviors (not bugs):**
- Yelu.sg leads without website URLs show empty `industry_confidence`/`sg_signals` — enrichment requires fetchable homepage
- SearXNG health check occasionally reports "no engines" on first ping, but engines recover during run — pipeline auto-falls back
- Google via SearXNG returning 0 (VPS IP rate-limit) — Yahoo/Yandex/Mojeek direct cover all queries

---

### 2026-04-22 (v12) — EMAIL_QUICKREF.md + documentation loop fix

**Problem:** Bot got stuck reading documentation files (SOUL.md, SKILL.md, AGENTS.md) instead of executing commands. Each file referenced others, creating an infinite-read loop. DeepSeek PoW added ~1-2s per call, making it feel very slow to the user.

**Root cause:** The DEEPSEEK_TEMPLATE told the model "read SKILL.md before running a skill." SKILL.md is 620 lines and contains cross-references to SOUL.md and AGENTS.md. When the user asked to override a history block, the bot didn't know the exact command, so it started "googling its own docs."

**Fix:**
1. Created `/root/.openclaw/workspace/EMAIL_QUICKREF.md` (1.6KB) — contains ONLY the exact 4 commands for one-off email sends + history override command.
2. Updated `DEEPSEEK_TEMPLATE` in `web-tool-prompt.ts`:
   - Email tasks → read `EMAIL_QUICKREF.md` ONLY, do NOT read SKILL.md/SOUL.md/AGENTS.md
   - Leadgen → read `sg-leadgen/SKILL.md`
   - Enrich → read `sg-enrich/SKILL.md`
   - Verify → read `sg-verify/SKILL.md`
   - Research/strategy → read SOUL.md if needed
3. Updated SHORT REPLY SCENARIOS to point to `EMAIL_QUICKREF.md` instead of `SKILL.md` for sender-name replies.

**Result:** Bot now reads a 1.6KB quick ref and executes immediately. No more documentation loops.

**Verified:** Email sent successfully to `design@dexterng.asia` via OpenClaw zero-token DeepSeek V4.
