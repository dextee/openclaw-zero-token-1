# Mirae OpenClaw Zero-Token — Full Deployment Guide for Kimi

> **For:** Kimi Code CLI on secondary VPS  
> **Date:** 2026-04-24  
> **Source VPS:** Ubuntu 24.04, XRDP, Node v22.22.2, Python 3.12  
> **GitHub Backup:** `https://github.com/dextee/Mirae` (force-pushed today)  
> **Bot:** @miraeclawbot

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [SearXNG Setup & Configuration](#2-searxng-setup--configuration)
3. [sg-leadgen (Singapore Lead Generation)](#3-sg-leadgen)
4. [sg-enrich (Lead Enrichment)](#4-sg-enrich)
5. [sg-verify (Email Verification)](#5-sg-verify)
6. [sg-outreach (Email Sequences & Sender)](#6-sg-outreach)
7. [OpenClaw Zero-Token Configuration](#7-openclaw-zero-token-configuration)
8. [Chrome CDP & Browser Auth](#8-chrome-cdp--browser-auth)
9. [Tool Calling Architecture](#9-tool-calling-architecture)
10. [Deployment Checklist](#10-deployment-checklist)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Executive Summary

This guide documents the **complete production setup** of the Mirae Advisory OpenClaw zero-token Telegram bot. It includes all skills, configurations, and fixes applied across multiple patching sessions by Claude Code, Kimi Code CLI, and manual tuning.

### What's Different from Stock OpenClaw

| Component | Stock | Mirae Production |
|-----------|-------|------------------|
| Search | None | SearXNG + Mojeek + yelu.sg fallback |
| Lead Generation | None | `sg-leadgen` — full pipeline with dedup/scoring |
| Lead Enrichment | None | `sg-enrich` — contacts, intent signals, WhatsApp |
| Email Verification | None | `sg-verify` — DNS+SMTP zero-cost verification |
| Outreach | None | `sg-outreach` — Gmail/Workspace SMTP sequences |
| Tool Calling | Basic | Multi-step chains, Qwen native tool rules, re-injection fix |
| Timeout | 600s | 1800s agent timeout, 360s poll stall threshold |

### Critical Files Map

```
/root/openclaw-zero-token/
├── .env                              # Environment variables
├── .openclaw-upstream-state/
│   ├── openclaw.json                 # ACTIVE config (NOT ~/.openclaw/openclaw.json)
│   └── agents/main/agent/
│       └── auth-profiles.json        # Browser auth cookies (zero-token)
├── src/zero-token/tool-calling/
│   ├── web-stream-middleware.ts      # Core tool detection + multi-step chaining
│   ├── web-tool-prompt.ts            # Injected tool prompt per model
│   └── web-tool-defs.ts              # Tool definitions JSON
├── skills/
│   ├── sg-leadgen/                   # Lead generation pipeline
│   ├── sg-enrich/                    # Lead enrichment
│   ├── sg-verify/                    # Email verification
│   └── sg-outreach/                  # Email sequences + sender
└── server.sh                         # Gateway management (loads .env)
```

---

## 2. SearXNG Setup & Configuration

### Installation

SearXNG is installed at `/opt/searxng` (venv-based, NOT Docker).

```bash
# If reinstalling on new VPS:
cd /opt
sudo git clone https://github.com/searxng/searxng.git
sudo python3 -m venv searxng/venv
sudo searxng/venv/bin/pip install -e searxng

# Create settings.yml (see config below)
# Then start:
sudo searxng/venv/bin/python -m searx.webapp &
```

### Current Working Engine Config

**File:** `/opt/searxng/settings.yml`

**Enabled engines:**
- `google` — primary, most reliable for SG business
- `yahoo` — good secondary
- `yandex` — useful for non-English content
- `qwant` — European privacy engine
- `mojeek` — independent, no CAPTCHA
- `startpage` — Google proxy, occasional CAPTCHA

**Disabled engines:**
- `bing` — returns garbage (zhihu.com, foreign gov sites) for SG queries
- `duckduckgo` — returns 0 results via SearXNG

**Key settings.yml excerpt:**

```yaml
search:
  safe_search: 0
  ban_time_on_fail: 5
  max_ban_time_on_fail: 120
  suspended_times:
    SearxEngineAccessDenied: 180
    SearxEngineCaptcha: 3600
    SearxEngineTooManyRequests: 180
    cf_SearxEngineCaptcha: 1296000
    cf_SearxEngineAccessDenied: 86400
    recaptcha_SearxEngineCaptcha: 604800

server:
  port: 8080
  bind_address: "127.0.0.1"

engines:
  - name: google
    engine: google
    shortcut: go
    disabled: false

  - name: yahoo
    engine: yahoo
    shortcut: yh
    disabled: false

  - name: yandex
    engine: yandex
    shortcut: yd
    disabled: false

  - name: qwant
    engine: qwant
    shortcut: qw
    disabled: false

  - name: mojeek
    engine: mojeek
    shortcut: mjk
    disabled: false

  - name: startpage
    engine: startpage
    shortcut: sp
    # no disabled line = enabled by default

  - name: bing
    engine: bing
    shortcut: bi
    disabled: true          # ← DISABLED: garbage results

  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg
    disabled: true          # ← DISABLED: returns 0 results
```

### Verify SearXNG Health

```bash
# Should return JSON with results from google/yahoo/etc.
curl -s "http://localhost:8080/search?q=construction+companies+Singapore&format=json" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('Results:', len(d.get('results',[]))); print('Engines:', list(set(r.get('engine','') for r in d.get('results',[]))))"
```

**Expected output:**
```
Results: 10+
Engines: ['google', 'yahoo', 'yandex', ...]
```

### Process Management

```bash
# Check if running
ps aux | grep searx.webapp | grep -v grep

# Restart
kill $(pgrep -f searx.webapp)
cd /opt/searxng && nohup venv/bin/python -m searx.webapp > /tmp/searxng.log 2>&1 &
```

---

## 3. sg-leadgen

### Purpose
Singapore B2B lead generation. Search → extract → enrich → dedup → score → CSV.

### Location
`/root/openclaw-zero-token/skills/sg-leadgen/`

### Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/run_full_pipeline.py` | One-shot pipeline (search → enrich → dedup → CSV) |
| `scripts/dedup_score.py` | Deduplicate + score leads |
| `scripts/run_mirae_pipeline.sh` | FULL wrapper: leadgen → verify → enrich → verify → score → sequences → send |

### Pipeline Flow

```
Stage 1: Search (SearXNG → Mojeek → DuckDuckGo → yelu.sg → Startpage)
Stage 2: Build leads + expand listicles
Stage 3: Website enrichment (emails, phones, decision makers)
Stage 4: Deduplication + scoring
Stage 5: Final CSV export
```

### Search Query Strategy

Current queries (7 total, limit=30 each):
```python
queries = [
    f"{industry} Pte Ltd Singapore",
    f"top {industry} companies Singapore",
    f"best {industry} companies Singapore",
    f"{industry} company Singapore email contact",
    f"list of {industry} companies Singapore",
    f"{industry} Singapore SME",
    f"{industry} contractors Singapore -directory -blog -news",
]
```

### Critical Code Fixes Applied (v4, 2026-04-21)

1. **Mojeek search added** — `_mojeek_search()` function, inserted into fallback chain
2. **yelu.sg baseline** — always fetched directly in `main()`, merged with search results
3. **Dedup bug fixed** — `DIRECTORY_DOMAINS` in `dedup_score.py` prevents merging yelu.sg profile URLs
4. **Email fallback fixed** — no longer generates `enquiry@yelu.sg` for directory domains
5. **Tagline rejection** — listicle extractor skips "9 years of experience", "Modern and unique designs", etc.
6. **Junk domain blocking** — bizvibe.com, smergers.com, smehorizon.com, etc.
7. **Limit increased** — 15 → 30 results per query

### Known Limitations

- DuckDuckGo HTML is CAPTCHA-blocked on this IP
- Startpage is intermittently CAPTCHA-blocked
- yelu.sg returns ~20 results per category, many without real websites
- Without SearXNG, max yield is ~15-20 leads per run
- With SearXNG, yield is 25-40+ leads per run

### Usage

```bash
# Basic pipeline
python3 /root/openclaw-zero-token/skills/sg-leadgen/scripts/run_full_pipeline.py \
  "construction companies" \
  --target 25 \
  --output /root/.openclaw/workspace/leads/sg_leads_construction_24042026.csv \
  --workers 5 \
  --min-score 0

# Full Mirae pipeline (leadgen → verify → enrich → verify → score → sequences)
/root/openclaw-zero-token/skills/sg-leadgen/scripts/run_mirae_pipeline.sh \
  --industry "Construction" \
  --target 25 \
  --sender-name "Tom Lee"
```

---

## 4. sg-enrich

### Purpose
Lead enrichment: decision makers, intent signals, tech stack, WhatsApp numbers.

### Location
`/root/openclaw-zero-token/skills/sg-enrich/`

### Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/enrich_contacts.py` | Contact/DM extraction from websites |
| `scripts/enrich_leads.py` | General enrichment (ACRA, LinkedIn) |
| `scripts/intent_signals.py` | Tech stack, hiring signals, news |
| `scripts/tech_stack.py` | Website technology detection |
| `scripts/whatsapp_finder.py` | WhatsApp number extraction |

### Critical Fix: `--offset` Parameter

Added 2026-04-21. Enables chunked batch processing:

```bash
# Batch 1: rows 0-9
python3 enrich_contacts.py input.csv --output out1.csv --limit 10 --offset 0

# Batch 2: rows 10-19
python3 enrich_contacts.py input.csv --output out2.csv --limit 10 --offset 10
```

### Batch Size Limits (CRITICAL)

| Task | Max/Batch | Duration | Safe? |
|------|-----------|----------|-------|
| Contact enrichment | 10 | 40-80s | ✅ |
| Intent signals | 10 | 60-90s | ✅ |
| Tech stack | 10 | 30-60s | ✅ |
| WhatsApp finder | 10 | 20-40s | ✅ |

**Never exceed 10 per batch.** Gateway hard kill is 300s. Keep batches under 240s.

### Workers Capped

```python
workers = min(args.workers, 4)  # Max 4 concurrent HTTP requests
```

---

## 5. sg-verify

### Purpose
Zero-cost email verification. DNS MX lookup + SMTP RCPT TO handshake. No APIs, no credits.

### Location
`/root/openclaw-zero-token/skills/sg-verify/`

### Key Script

`scripts/verify_emails.py`

### How It Works

1. Parses input CSV for email/website columns
2. For leads without email: generates pattern guesses (`enquiry@`, `info@`, `sales@`, etc.)
3. DNS MX lookup on domain
4. SMTP connection + `RCPT TO:` handshake (no actual email sent)
5. Detects catch-all, Google Workspace, Microsoft 365
6. Outputs 6 new columns: `email_verified`, `email_confidence`, `email_source`, `email_status_detail`, `mx_provider`, `is_catch_all`

### Batch Size Limits

| Mode | Batch Size | Duration |
|------|------------|----------|
| Deep (recommended) | 5 | 15-30s per batch |
| Fast | 10 | 30-60s per batch |
| Absolute max | 10 | — |

### Usage

```bash
python3 /root/openclaw-zero-token/skills/sg-verify/scripts/verify_emails.py \
  /root/.openclaw/workspace/leads/input.csv \
  --output /root/.openclaw/workspace/leads/verified.csv
```

---

## 6. sg-outreach

### Purpose
Personalized email sequence generation and sending. Gong.io/Josh Braun/Alex Berman optimized copy.

### Location
`/root/openclaw-zero-token/skills/sg-outreach/`

### Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/generate_sequences.py` | Generate 3-7 email sequences per lead tier |
| `scripts/workspace_smtp_sender.py` | Send via Google Workspace SMTP (never expires) |
| `scripts/gmail_sender.py` | Send via Gmail API (OAuth2, expires every 7 days) |
| `scripts/workspace_imap_tracker.py` | Track replies via IMAP (never expires) |
| `scripts/outreach_tracker.py` | Reply/bounce tracking (Gmail API) |
| `scripts/deliverability_check.py` | SPF/DKIM/DMARC validator |
| `scripts/domain_throttle.py` | Domain warmup + rate limiting |

### Auth Methods

| Method | Expiry | Best For |
|--------|--------|----------|
| **Workspace SMTP** | Never | Production (admin@miraeadvisory.com) |
| **Gmail API OAuth2** | 7 days | Personal Gmail (requires re-auth) |

### Compliance

PDPA/SCA footer auto-appended from `/root/.openclaw/workspace/compliance/COMPLIANCE.json`.

---

## 7. OpenClaw Zero-Token Configuration

### Active Config File

**ONLY this config is active:**
`/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json`

**NOT active (stale duplicate):**
`~/.openclaw/openclaw.json` ← DO NOT USE

### Current Model Chain

```json
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "deepseek-web/deepseek-v4",
        "fallbacks": [
          "deepseek-web/deepseek-chat",
          "deepseek-web/deepseek-reasoner",
          "qwen-web/qwen3.5-plus",
          "qwen-web/qwen3.6-plus"
        ]
      }
    }
  }
}
```

### Tool Configuration

```json
{
  "tools": {
    "profile": "full",
    "allow": ["exec", "read", "write", "edit", "web_search", "web_fetch", "message",
              "sessions_list", "sessions_history", "sessions_send", "session_status"],
    "exec": {
      "backgroundMs": 270000,
      "timeoutSec": 300
    },
    "fs": {
      "workspaceOnly": false
    }
  }
}
```

### Environment Variables

```bash
# /root/openclaw-zero-token/.env
TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_BOT_TOKEN>
OPENCLAW_CONFIG_PATH=/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json
OPENCLAW_STATE_DIR=/root/openclaw-zero-token/.openclaw-upstream-state
OPENCLAW_GATEWAY_PORT=3001
```

### Gateway Management

```bash
cd /root/openclaw-zero-token
./server.sh start    # Loads .env, sets correct config path
./server.sh stop
./server.sh restart
./server.sh status
```

**Never run `node openclaw.mjs gateway` directly** — it misses env vars and reads stale `~/.openclaw/openclaw.json`.

---

## 8. Chrome CDP & Browser Auth

### Correct Launch Command

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

### Hard Rules

- Profile MUST be `/root/.config/chrome-openclaw-debug`
- NEVER use `/tmp/chrome-debug-profile` (throwaway, no cookies)
- ALWAYS set `DISPLAY=:10 XAUTHORITY=/root/.Xauthority`
- Desktop shortcut at `/root/Desktop/Chrome-Debug.desktop` has correct flags

### Check Status

```bash
curl -s http://127.0.0.1:9222/json/version
pgrep -f "chrome.*remote-debugging-port=9222"
```

### Auth Onboarding

1. Launch Chrome (above command)
2. Log into AI provider websites in the browser:
   - Qwen: https://chat.qwen.ai
   - DeepSeek: https://chat.deepseek.com
3. Run:
   ```bash
   cd /root/openclaw-zero-token && ./onboard.sh webauth
   ```
4. Select provider → captures cookies to `auth-profiles.json`

**Cannot be automated.** Needs human in XRDP session.

---

## 9. Tool Calling Architecture

### How It Works (DeepSeek / Claude Web Models)

1. User sends Telegram message
2. `web-stream-middleware.ts` prepends `IDENTITY_PREFIX + tool_prompt` to user message
3. Model responds with `tool_json` block (bare JSON, no markdown fence)
4. Middleware detects JSON, executes tool (`exec`, `read`, `write`, etc.)
5. Result is fed back: `Tool <name> returned: <result>\nContinue the task...`
6. Tool re-injection applied on tool result feedback (`isToolResult = true`)
7. Multi-step chains work: `read SKILL.md → exec pipeline → read CSV → final answer`

### Tool Format

```json
{"tool":"exec","parameters":{"command":"python3 /path/to/script.py","background":true}}
{"tool":"read","parameters":{"path":"/absolute/path/to/file"}}
{"tool":"write","parameters":{"path":"/absolute/path","content":"..."}}
```

### Qwen Web vs DeepSeek Web — CRITICAL DIFFERENCE

| Feature | Qwen Web | DeepSeek Web |
|---------|----------|--------------|
| Native tools | `web_search`, `code_interpreter`, `web_extractor`, `image_search` | None |
| Injected tools | Fails with "Tool X does not exists" | Works correctly |
| Read files | Use `code_interpreter` with `open('/path').read()` | Use `{"tool":"read"}` |
| Run commands | Use `code_interpreter` with `subprocess.run([...])` | Use `{"tool":"exec"}` |
| Web search | Use native `web_search` | Use `{"tool":"web_search"}` |

### Key Source Files

| File | Purpose |
|------|---------|
| `src/zero-token/tool-calling/web-stream-middleware.ts` | Detects + executes tool calls, feeds results back |
| `src/zero-token/tool-calling/web-tool-prompt.ts` | Builds injected tool prompt per model |
| `src/zero-token/tool-calling/web-tool-defs.ts` | Tool definitions JSON |

### After Any TypeScript Change

```bash
cd /root/openclaw-zero-token
pnpm build
./server.sh restart
```

---

## 10. Deployment Checklist

### New VPS Setup

```bash
# 1. Prerequisites
apt update && apt install -y python3-pip python3-venv git curl nodejs npm
npm install -g pnpm

# 2. Clone repo
git clone https://github.com/dextee/Mirae.git /root/openclaw-zero-token
cd /root/openclaw-zero-token
pnpm install

# 3. Install Python deps for skills
pip install dnspython tqdm colorama requests bs4 lxml

# 4. Install SearXNG
sudo python3 -m venv /opt/searxng/venv
sudo git clone https://github.com/searxng/searxng.git /opt/searxng/src
sudo /opt/searxng/venv/bin/pip install -e /opt/searxng/src
# Copy settings.yml from this guide
sudo /opt/searxng/venv/bin/python -m searx.webapp &

# 5. Create .env
cat > /root/openclaw-zero-token/.env << 'EOF'
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
OPENCLAW_CONFIG_PATH=/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json
OPENCLAW_STATE_DIR=/root/openclaw-zero-token/.openclaw-upstream-state
OPENCLAW_GATEWAY_PORT=3001
EOF

# 6. Create workspace dirs
mkdir -p /root/.openclaw/workspace/leads
mkdir -p /root/.openclaw/workspace/compliance

# 7. Build OpenClaw
pnpm build

# 8. Start Chrome (with correct profile)
DISPLAY=:10 XAUTHORITY=/root/.Xauthority /opt/google/chrome/google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/root/.config/chrome-openclaw-debug \
  --no-first-run --no-default-browser-check \
  --disable-background-networking --disable-sync \
  --no-sandbox --disable-dev-shm-usage --disable-gpu \
  --remote-allow-origins='*' > /tmp/chrome-debug.log 2>&1 &

# 9. Start gateway
./server.sh start

# 10. Verify
curl -s http://127.0.0.1:9222/json/version
curl -s http://127.0.0.1:3001/healthz 2>/dev/null || echo "Gateway up"
curl -s "http://localhost:8080/search?q=test&format=json" | head -c 100
```

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Pipeline returns <15 leads | SearXNG down or engines blocked | Check `curl localhost:8080`, restart SearXNG, verify engine health |
| `enquiry@yelu.sg` emails | Old dedup bug or missing directory domain filter | Update `dedup_score.py` with `DIRECTORY_DOMAINS` |
| Gateway uses wrong model | Started without `.env` | Use `./server.sh start`, never `node openclaw.mjs gateway` directly |
| Raw JSON in Telegram | `web-stream-middleware.ts` bypass bug | Ensure toolResult path re-wraps with tool detection (see patch v4) |
| Bot silent on long exec | DeepSeek sync exec, no start message | SKILL.md rules: ALWAYS send start message BEFORE exec |
| Chrome dies silently | Missing `DISPLAY=:10` | Set `DISPLAY=:10 XAUTHORITY=/root/.Xauthority` |
| DuckDuckGo 0 results | CAPTCHA block | Expected — Mojeek and SearXNG are primary sources now |
| Startpage captcha | IP blocked | Wait 1h or use Mojeek fallback |
| Email verify timeouts | Port 25 blocked | Check `telnet gmail-smtp-in.l.google.com 25` |

---

## Appendix: Patch History

### 2026-04-24 — v5 (Current)
- Added Mojeek as fallback search backend
- yelu.sg always fetched as baseline
- Strengthened listicle/domain filters
- Fixed email fallback for directory domains
- GitHub backup pushed to `dextee/Mirae`

### 2026-04-21 — v4
- `enrich_contacts.py`: `--offset` parameter for chunked batches
- Worker cap: 4 max, default 3
- Contact paths reduced: 8 → 5 standard paths
- Discovered contact page cap: 6 → 4

### 2026-04-21 — v3
- Non-.sg domain support: default `return True` for neutral TLDs
- Blocked additional junk sources (job boards, directories, research firms)
- Company name whitespace collapse, URL-as-name rejection, phone-number-as-name rejection

### 2026-04-21 — v2
- Strip domain-in-parentheses from names
- Reject semicolons in names
- Added `certified firms`, `registered firms`, `member companies` to low-quality patterns

### 2026-04-21 — v1
- DM extraction: min word count 1 → 2, max 3 → 4
- Expanded `DM_REJECT_WORDS` with garbage words
- Path cleanup: all leads output to `/root/.openclaw/workspace/leads/`

### 2026-04-20
- Multi-step tool calling fix: merged toolResult path into main flow
- `dedup_score.py`: utf-8-sig encoding fix, `re.sub` fix
- sg-leadgen: SearXNG → Yellow Pages SG → Startpage fallback chain
- Workspace consolidated to single canonical path `~/.openclaw/workspace`

### 2026-04-16
- Timeout: 600s → 1800s
- Poll stall threshold: 180s → 360s
- sg-enrich SKILL.md: DeepSeek-specific execution order
- sg-leadgen SKILL.md: Append to existing CSV workflow
- AGENTS.md + SOUL.md: DeepSeek V4 model guidance

---

*End of guide. For questions, check `AGENTS.md` in repo root or ask Kimi on source VPS.*
