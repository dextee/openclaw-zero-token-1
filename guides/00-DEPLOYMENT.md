# Mirae OpenClaw Zero-Token — Full Deployment Guide for Kimi

> **For:** Kimi Code CLI on secondary VPS  
> **Date:** 2026-04-24  
> **Source VPS:** Ubuntu 24.04, XRDP, Node v22.22.2, Python 3.12  
> **GitHub Backup:** `https://github.com/dextee/Mirae`  
> **Bot:** @miraeclawbot

---

## Table of Contents

1. [Quick Start for Another Kimi](#1-quick-start-for-another-kimi)
2. [What to Replace for Your Own Bot/Server](#2-what-to-replace-for-your-own-botserver)
3. [SearXNG Setup & Configuration](#3-searxng-setup--configuration)
4. [sg-leadgen (Singapore Lead Generation)](#4-sg-leadgen)
5. [sg-enrich (Lead Enrichment)](#5-sg-enrich)
6. [sg-verify (Email Verification)](#6-sg-verify)
7. [sg-outreach (Email Sequences & Sender)](#7-sg-outreach)
8. [OpenClaw Zero-Token Configuration](#8-openclaw-zero-token-configuration)
9. [Workspace Files — SOUL.md & AGENTS.md](#9-workspace-files--soulmd--agentsmd)
10. [Chrome CDP & Browser Auth](#10-chrome-cdp--browser-auth)
11. [Tool Calling Architecture](#11-tool-calling-architecture)
12. [Complete Patch History](#12-complete-patch-history)
13. [Deployment Checklist](#13-deployment-checklist)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Quick Start for Another Kimi

```bash
# 1. Prerequisites
apt update && apt install -y python3-pip python3-venv git curl nodejs npm
npm install -g pnpm

# 2. Clone repo
git clone https://github.com/dextee/Mirae.git /root/openclaw-zero-token
cd /root/openclaw-zero-token
pnpm install

# 3. Install Python deps for skills
pip install dnspython tqdm colorama requests bs4 lxml openpyxl

# 4. Install SearXNG (see Section 3)
# 5. Create .env (see Section 8)
# 6. Create workspace dirs
mkdir -p /root/.openclaw/workspace/leads
mkdir -p /root/.openclaw/workspace/compliance
mkdir -p /root/.openclaw/credentials

# 7. Build OpenClaw
pnpm build

# 8. Start Chrome (see Section 10)
# 9. Start gateway
./server.sh start
```

---

## 2. What to Replace for Your Own Bot/Server

**CRITICAL:** The repo contains hardcoded paths and names for the Mirae deployment. You MUST replace these for your own bot:

### 2.1 Bot Name & Identity

| File                                                     | What to Replace                                     | Example                            |
| -------------------------------------------------------- | --------------------------------------------------- | ---------------------------------- |
| `~/.openclaw/workspace/SOUL.md`                          | "Mirae Advisory" → Your company name                | "Acme Corp"                        |
| `~/.openclaw/workspace/SOUL.md`                          | "OpenClaw ready. What do you need?" → Your greeting | "AcmeBot ready. What do you need?" |
| `~/.openclaw/workspace/SOUL.md`                          | `admin@miraeadvisory.com` → Your sender email       | `sender@yourdomain.com`            |
| `~/.openclaw/workspace/SOUL.md`                          | "Business Development" → Default sender title       | "Sales Manager"                    |
| `skills/sg-outreach/references/sequence_templates.py`    | `admin@miraeadvisory.com` → Your email              | `sender@yourdomain.com`            |
| `skills/sg-outreach/references/sequence_templates.py`    | "Mirae Advisory" → Your company                     | "Acme Corp"                        |
| `skills/sg-outreach/.workspace_smtp_config.json.example` | SMTP credentials → Your SMTP                        | See Section 7                      |

### 2.2 Paths That May Differ

| Path in Repo                           | Purpose              | Change If...                       |
| -------------------------------------- | -------------------- | ---------------------------------- |
| `/root/openclaw-zero-token/`           | Project root         | You cloned to a different path     |
| `/root/.openclaw/workspace/`           | Bot workspace        | OpenClaw default — usually correct |
| `/root/.openclaw/workspace/leads/`     | Lead output          | Usually correct                    |
| `/opt/searxng/`                        | SearXNG installation | You installed elsewhere            |
| `/root/.config/chrome-openclaw-debug/` | Chrome profile       | You use a different profile path   |

**If you change the project root path**, update ALL absolute paths in:

- `~/.openclaw/workspace/SOUL.md` (skill paths, script paths)
- `~/.openclaw/workspace/AGENTS.md` (skill paths)
- `skills/*/SKILL.md` (script paths, output paths)
- `src/zero-token/tool-calling/web-tool-prompt.ts` (leads output path)
- `.openclaw-upstream-state/openclaw.json` (`skills.load.extraDirs`)

### 2.3 Telegram Bot

```bash
# 1. Create your own bot with @BotFather, get token
# 2. Edit .env
cat > /root/openclaw-zero-token/.env << 'EOF'
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_HERE
OPENCLAW_CONFIG_PATH=/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json
OPENCLAW_STATE_DIR=/root/openclaw-zero-token/.openclaw-upstream-state
OPENCLAW_GATEWAY_PORT=3001
EOF

# 3. Edit whitelist
cat > /root/.openclaw/credentials/telegram-default-allowFrom.json << 'EOF'
["YOUR_TELEGRAM_USER_ID"]
EOF
```

---

## 3. SearXNG Setup & Configuration

### Installation

```bash
sudo mkdir -p /opt/searxng
cd /opt/searxng
sudo git clone https://github.com/searxng/searxng.git src
sudo python3 -m venv venv
sudo venv/bin/pip install -e src
```

### settings.yml

Create `/opt/searxng/settings.yml`:

```yaml
use_default_settings: true

server:
  port: 8080
  bind_address: "127.0.0.1"
  secret_key: "your_random_secret_key_here"

search:
  safe_search: 0
  autocomplete: ""
  ban_time_on_fail: 5
  max_ban_time_on_fail: 120
  suspended_times:
    SearxEngineAccessDenied: 180
    SearxEngineCaptcha: 3600
    SearxEngineTooManyRequests: 180
    cf_SearxEngineCaptcha: 1296000
    cf_SearxEngineAccessDenied: 86400
    recaptcha_SearxEngineCaptcha: 604800

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

  - name: bing
    engine: bing
    shortcut: bi
    disabled: true

  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg
    disabled: true
```

**Engine rules:**

- **Enabled:** `google`, `yahoo`, `yandex`, `qwant`, `mojeek` — these work on VPS IPs
- **Disabled:** `bing`, `duckduckgo` — Bing returns garbage for SG queries; DDG returns 0 via SearXNG

### Start SearXNG

```bash
cd /opt/searxng
nohup venv/bin/python -m searx.webapp > /tmp/searxng.log 2>&1 &

# Verify
curl -s "http://localhost:8080/search?q=construction+Singapore&format=json" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('Results:', len(d.get('results',[])))"
```

---

## 4. sg-leadgen

### Location

`/root/openclaw-zero-token/skills/sg-leadgen/`

### Key Scripts

| Script                          | Purpose                                                                     |
| ------------------------------- | --------------------------------------------------------------------------- |
| `scripts/run_full_pipeline.py`  | One-shot pipeline (search → enrich → dedup → CSV)                           |
| `scripts/dedup_score.py`        | Deduplicate + score leads                                                   |
| `scripts/run_mirae_pipeline.sh` | FULL wrapper: leadgen → verify → enrich → verify → score → sequences → send |

### Production Architecture (v13)

The pipeline has a **pre-flight health check**, **round-robin engine assignment**, and **progressive fallback**:

1. `check_searxng_health()` tests all engines before starting
2. Each query is assigned a primary engine to spread load
3. Failed engines are tracked and skipped for remaining queries
4. If ALL SearXNG engines fail, falls back to direct Mojeek scrape + Yelu.sg

### Current Query Set (optimized for SG companies)

```python
queries = [
    f"site:.sg {industry} company",
    f"site:.sg {industry} Pte Ltd",
    f'{industry} "Pte Ltd" Singapore',
    f"intitle:{industry} Singapore",
]
```

### Critical Fixes Already in Code

- `DIRECTORY_DOMAINS` in `dedup_score.py` prevents yelu.sg profile URLs merging
- `is_likely_sg_company()` defaults `True` for neutral TLDs (.com, .io, .net)
- `has_sg_signals()` scans homepage for +65 phones, SG postal codes, UEN mentions
- Industry keyword verification with `industry_confidence` column
- Pattern email fallback ONLY for .sg domains or domains with SG signals
- Progress delays: 3s between queries, 5s after failures

### Usage

```bash
# Quick list (Path A)
python3 /root/openclaw-zero-token/skills/sg-leadgen/scripts/run_full_pipeline.py \
  "construction" --target 10 --output /root/.openclaw/workspace/leads/quick.csv --qc

# Full campaign (Path B)
bash /root/openclaw-zero-token/skills/sg-leadgen/scripts/run_mirae_pipeline.sh \
  --industry "Construction" --target 25 --skip-sequences --qc
```

---

## 5. sg-enrich

### Location

`/root/openclaw-zero-token/skills/sg-enrich/`

### Key Scripts

| Script                       | Purpose                             |
| ---------------------------- | ----------------------------------- |
| `scripts/enrich_contacts.py` | Contact/DM extraction from websites |
| `scripts/enrich_leads.py`    | General enrichment (ACRA, LinkedIn) |
| `scripts/intent_signals.py`  | Tech stack, hiring signals, news    |

### Critical Fix: `--offset` Parameter

```bash
# Batch 1: rows 0-9
python3 enrich_contacts.py input.csv --output out1.csv --limit 10 --offset 0

# Batch 2: rows 10-19
python3 enrich_contacts.py input.csv --output out2.csv --limit 10 --offset 10
```

### Batch Size Limits

| Task               | Max/Batch | Duration | Safe? |
| ------------------ | --------- | -------- | ----- |
| Contact enrichment | 10        | 40-80s   | ✅    |
| Intent signals     | 10        | 60-90s   | ✅    |
| Tech stack         | 10        | 30-60s   | ✅    |

**Never exceed 10 per batch.** Gateway hard kill is 300s.

---

## 6. sg-verify

### Location

`/root/openclaw-zero-token/skills/sg-verify/`

### Key Script

`scripts/verify_emails.py`

### Batch Size Limits

| Mode               | Batch Size | Duration         |
| ------------------ | ---------- | ---------------- |
| Deep (recommended) | 5          | 15-30s per batch |
| Fast               | 10         | 30-60s per batch |
| Absolute max       | 10         | —                |

### Usage

```bash
python3 /root/openclaw-zero-token/skills/sg-verify/scripts/verify_emails.py \
  /root/.openclaw/workspace/leads/input.csv \
  --output /root/.openclaw/workspace/leads/verified.csv
```

---

## 7. sg-outreach

### Location

`/root/openclaw-zero-token/skills/sg-outreach/`

### Key Scripts

| Script                              | Purpose                                                |
| ----------------------------------- | ------------------------------------------------------ |
| `scripts/generate_sequences.py`     | Generate email sequences (with `--single` for one-off) |
| `scripts/workspace_smtp_sender.py`  | Send via Google Workspace SMTP                         |
| `scripts/gmail_sender.py`           | Send via Gmail API (OAuth2, expires every 7 days)      |
| `scripts/validate_sequences.py`     | Pre-send validator                                     |
| `scripts/deliverability_check.py`   | SPF/DKIM/DMARC validator                               |
| `scripts/domain_throttle.py`        | 45s minimum gap between same-domain sends              |
| `scripts/outreach_history.py`       | Global deduplication + suppression list                |
| `scripts/workspace_imap_tracker.py` | Reply/bounce tracking via IMAP                         |

### Auth Setup

**Workspace SMTP (recommended — never expires):**

```bash
cp skills/sg-outreach/.workspace_smtp_config.json.example \
   skills/sg-outreach/.workspace_smtp_config.json

# Edit with your credentials:
{
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "smtp_user": "your-email@gmail.com",
  "smtp_password": "your-app-password",
  "imap_host": "imap.gmail.com",
  "imap_port": 993
}
```

### Critical Features Already in Code

- **Global history** (`.outreach_history.json`): tracks every contact across campaigns
- **Auto-suppression**: unsubscribe/stop/negative replies → permanent block
- **Domain throttling**: 45s gap between sends to same domain
- **Retry logic**: 3× exponential backoff for temporary errors
- **Email threading**: follow-ups include `In-Reply-To` header
- **Bounce detection**: hard bounces auto-suppress
- **A/B subject tracking**: `subject_variant` column in sequences
- **`--single` flag**: generates ONLY email #1 for one-off sends

---

## 8. OpenClaw Zero-Token Configuration

### Active Config File

**ONLY this config is active:**
`/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json`

### CRITICAL: Disable Bonjour/mDNS

Add this to prevent 120% CPU loop on VPS:

```json
{
  "discovery": {
    "mdns": {
      "mode": "off"
    }
  }
}
```

### Current Model Chain (v15)

```json
{
  "agents": {
    "defaults": {
      "timeoutSeconds": 1800,
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

**Why DeepSeek V4 primary?** DeepSeek web supports OpenClaw's injected `exec`/`read`/`write` tools natively. Qwen web has a conflicting native tool system that intercepts injected tools.

### Tool Configuration

```json
{
  "tools": {
    "profile": "full",
    "allow": [
      "exec",
      "read",
      "write",
      "edit",
      "web_search",
      "web_fetch",
      "message",
      "sessions_list",
      "sessions_history",
      "sessions_send",
      "session_status"
    ],
    "exec": {
      "backgroundMs": 270000,
      "timeoutSec": 300
    }
  }
}
```

### Skills Loading

```json
{
  "skills": {
    "load": {
      "extraDirs": ["/root/openclaw-zero-token/skills"]
    }
  }
}
```

### Environment Variables

```bash
# /root/openclaw-zero-token/.env
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
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

**Never run `node openclaw.mjs gateway` directly** — it misses env vars.

---

## 9. Workspace Files — SOUL.md & AGENTS.md

These files live in `~/.openclaw/workspace/` and are read by the bot on EVERY message. Changes are live immediately.

### 9.1 SOUL.md — Bot Personality + Tool Rules

This file controls:

- **Tool calling rules** (Rule 1: one thing per message)
- **Path A vs Path B routing** (quick list vs full campaign)
- **Pipeline flow** (leadgen → verify → enrich → verify → outreach)
- **Sender name handling** (ask ONLY for sender_name)
- **One-off send workflow** (`--single` flag)
- **File upload handling**
- **Session greeting** ("OpenClaw ready. What do you need?")

**When adapting for your bot, replace in SOUL.md:**

1. Company name: "Mirae Advisory" → "Your Company"
2. Default sender title: "Business Development" → "Your Title"
3. Sender email domain: `miraeadvisory.com` → `yourdomain.com`
4. Greeting text: "OpenClaw ready. What do you need?" → "YourBot ready. What do you need?"
5. All absolute paths if you cloned to a different directory

### 9.2 AGENTS.md — Bot Workflows + Absolute Paths

This file controls:

- System restart procedures
- Chrome CDP launch command
- Gateway management
- Model chain
- Common tasks
- Patch history

**When adapting for your bot, replace in AGENTS.md:**

1. Bot name: `@miraeclawbot` → `@yourbot`
2. Allowed Telegram IDs
3. Model chain if different
4. All absolute paths if different

### 9.3 Creating Workspace Files

```bash
mkdir -p /root/.openclaw/workspace/

# Copy from repo (adapt paths/names first!)
cp /root/openclaw-zero-token/workspace/SOUL.md /root/.openclaw/workspace/SOUL.md
cp /root/openclaw-zero-token/workspace/AGENTS.md /root/.openclaw/workspace/AGENTS.md

# Or create minimal files — see the repo for full content
```

---

## 10. Chrome CDP & Browser Auth

### Launch Command

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
- NEVER use `/tmp/chrome-debug-profile` (no cookies)
- ALWAYS set `DISPLAY=:10 XAUTHORITY=/root/.Xauthority`

### Auth Onboarding (Interactive — Needs XRDP)

1. Launch Chrome (above)
2. Log into AI provider websites:
   - Qwen: https://chat.qwen.ai
   - DeepSeek: https://chat.deepseek.com
3. Run:
   ```bash
   cd /root/openclaw-zero-token && ./onboard.sh webauth
   ```
4. Select provider → captures cookies to `auth-profiles.json`

**Cannot be automated.** Needs human in XRDP session.

---

## 11. Tool Calling Architecture

### How It Works (DeepSeek Web Models)

1. User sends Telegram message
2. `web-stream-middleware.ts` prepends `IDENTITY_PREFIX + tool_prompt` to user message
3. Model responds with `tool_json` block (bare JSON, no markdown fence)
4. Middleware detects JSON, executes tool (`exec`, `read`, `write`, etc.)
5. Result is fed back: `Tool <name> returned: <result>\nContinue the task...`
6. Tool re-injection applied on tool result feedback (`isToolResult = true`)
7. Multi-step chains work: `read SKILL.md → exec pipeline → read CSV → final answer`

### Qwen Web vs DeepSeek Web — CRITICAL DIFFERENCE

| Feature        | Qwen Web                                            | DeepSeek Web          |
| -------------- | --------------------------------------------------- | --------------------- |
| Native tools   | `web_search`, `code_interpreter`, `web_extractor`   | None                  |
| Injected tools | Fails with "Tool X does not exists"                 | Works correctly       |
| Read files     | Use `code_interpreter` with `open('/path').read()`  | Use `{"tool":"read"}` |
| Run commands   | Use `code_interpreter` with `subprocess.run([...])` | Use `{"tool":"exec"}` |

### Key Source Files

| File                                                   | Purpose                                           |
| ------------------------------------------------------ | ------------------------------------------------- |
| `src/zero-token/tool-calling/web-stream-middleware.ts` | Detects + executes tool calls, feeds results back |
| `src/zero-token/tool-calling/web-tool-prompt.ts`       | Builds injected tool prompt per model             |
| `src/zero-token/tool-calling/web-tool-defs.ts`         | Tool definitions JSON                             |

### After Any TypeScript Change

```bash
cd /root/openclaw-zero-token
pnpm build
./server.sh restart
```

---

## 12. Complete Patch History

### 2026-04-22 (v15) — DeepSeek V4 as Primary Model

- `agents.defaults.model.primary` changed to `deepseek-web/deepseek-v4`
- Fallback chain: DeepSeek chat → DeepSeek reasoner → Qwen 3.5 → Qwen 3.6
- Why: DeepSeek supports OpenClaw injected tools; Qwen has conflicting native tools

### 2026-04-22 (v14) — Industry Verification + SG Signals + Bing/DDG Disabled

- `detect_industry_from_html()` scans homepage for industry keywords
- `has_sg_signals()` verifies .com/.io domains via +65 phones, postal codes, UEN
- Pattern email fallback tightened: only for .sg OR domains with SG signals
- Bing + DuckDuckGo disabled in SearXNG settings
- `language=en&safesearch=0` added to all SearXNG API calls

### 2026-04-22 (v13) — Multi-Engine Round-Robin with Auto-Fallback

- Pre-flight `check_searxng_health()` tests all engines
- Round-robin engine assignment per query
- `failed_engines` set tracks failures and skips bad engines
- Progressive delays: 3s between queries, 5s after failures
- SearXNG-down resilience: falls back to Mojeek direct + Yelu.sg
- `QUERY_METRICS` JSON logged per query for troubleshooting
- `_yelu_sg_search()` expanded: 1 page → 3 pages (20 → 60 companies)
- Quality filters: deep-path rejection, academic journal block, conglomerate block

### 2026-04-21 (v11) — DeepSeek V4 Tool Hardening + Single-Email Pipeline

- `web-stream-middleware.ts`: context preservation for short replies (≤40 chars)
- Stronger multi-step continuation prompt
- `web-tool-prompt.ts`: DeepSeek short-reply scenarios mapping
- `needsToolInjection()`: added outreach/email keywords
- `generate_sequences.py`: reads `.workspace_smtp_config.json` for sender_email fallback
- `outreach_history.py`: `pending` entries no longer blocked; `failed` can upgrade to `sent`
- End-to-end single-email send verified working

### 2026-04-21 (v10.2) — `--single` Flag + DeepSeek Native Tool Block

- `generate_sequences.py --single`: generates ONLY email #1, immediate send
- DeepSeek-specific tool prompt forbids native tools
- Built with `pnpm build`, gateway restarted

### 2026-04-21 (v10.1) — Wrong Template Fix + Deliverability

- Banned custom one-off sends in SKILL.md
- `deliverability_check.py`: SPF/DKIM/DMARC/MX validator
- DNS action required: enable DKIM, fix SPF, add DMARC

### 2026-04-21 (v10) — Sender Name Prompt + SMTP Tuple Bug Fix

- Bot asks ONLY for `sender_name` (email/title/company use defaults)
- `generate_sequences.py` hard stop if `--sender-name` empty
- `validate_sequences.py`: pre-send validator
- `workspace_smtp_sender.py` tuple unpacking fix

### 2026-04-21 (v9) — Domain Throttle + Retry + Bounce Detection

- `domain_throttle.py`: 45s minimum gap between same-domain sends
- Exponential backoff: 5s → 15s → 60s for temporary errors
- Auto-backup before sending
- Email threading with `In-Reply-To` / `References` headers
- Bounce detection in both reply trackers
- A/B subject line tracking
- Deliverability health report

### 2026-04-21 (v8) — Global Deduplication + Suppression List

- `outreach_history.py`: central JSON database across campaigns
- `lead_deduplicator.py`: compares new leads against all previous campaigns
- Pre-generation and pre-send duplicate checks
- Auto-suppression on unsubscribe/negative replies

### 2026-04-21 (v7) — Pipeline Workflow Hardening

- Leadgen capped at 25 leads default
- sg-verify batch size: 5 deep / 10 fast (max 10)
- Triple-check analysis after sg-verify with contextual recommendations
- Verify-twice rule: verify after leadgen AND after enrich
- Correct pipeline order: leadgen → verify → enrich → verify → outreach

### 2026-04-21 (v6) — Directory Email Pollution Fix

- `enrich_contacts.py` filters out directory domain emails (yelu.sg, etc.)
- `BLOCKED_EMAIL_PATTERNS`: rejects `user@domain.com`, `email@domain.com`, etc.

### 2026-04-21 (v5) — SearXNG Installation + Quality Fixes

- SearXNG installed at `/opt/searxng` on port 8080
- Chinese sites blocked: baidu, zhihu, runoob, csdn
- Telegram whitelist copied to canonical path

### 2026-04-21 (v4) — Batch Chunking + Performance Limits

- `enrich_contacts.py --offset` parameter
- Workers capped at 4 max, default 3
- Contact paths reduced: 8 → 5
- Discovered page cap: 6 → 4

### 2026-04-21 (v3) — Non-.sg Domain Support + Name Quality

- Neutral TLDs (.com, .io, .net) default to `True`
- Explicit block for non-SG country-code TLDs
- Job boards, directories, research firms blocked
- Whitespace collapse, URL-as-name rejection, year pattern rejection

### 2026-04-21 (v2) — Company Name Quality Fixes

- Strip domain-in-parentheses from names
- Reject semicolons in names
- Added certified/registered/member firms to low-quality patterns

### 2026-04-21 (v1) — DM Extraction Fix

- Min word count: 1 → 2, max: 3 → 4
- Expanded `DM_REJECT_WORDS`
- Path cleanup: all leads to `/root/.openclaw/workspace/leads/`

### 2026-04-20 — Multi-Step Tool Calling Fix

- `web-stream-middleware.ts` toolResult path merged into main flow
- SOUL.md rules strengthened with WRONG/CORRECT examples
- `dedup_score.py`: re.sub fix + utf-8-sig encoding fix
- Workspace consolidated to single canonical path

---

## 13. Deployment Checklist

### New VPS Setup

```bash
# 1. Prerequisites
apt update && apt install -y python3-pip python3-venv git curl nodejs npm
npm install -g pnpm

# 2. Clone repo
git clone https://github.com/dextee/Mirae.git /root/openclaw-zero-token
cd /root/openclaw-zero-token
pnpm install

# 3. Python deps
pip install dnspython tqdm colorama requests bs4 lxml openpyxl

# 4. Install SearXNG (Section 3)
# 5. Create .env (Section 8)
# 6. Create workspace dirs
mkdir -p /root/.openclaw/workspace/leads
mkdir -p /root/.openclaw/workspace/compliance
mkdir -p /root/.openclaw/credentials

# 7. Create workspace files (Section 9)
#    - Copy and adapt SOUL.md
#    - Copy and adapt AGENTS.md

# 8. Configure OpenClaw (Section 8)
#    - Add discovery.mdns.mode = "off"
#    - Set your Telegram bot token
#    - Set your whitelist

# 9. Configure SMTP (Section 7)
#    - Copy .workspace_smtp_config.json.example
#    - Add your credentials

# 10. Build OpenClaw
pnpm build

# 11. Start Chrome (Section 10)

# 12. Start gateway
./server.sh start

# 13. Verify
curl -s http://127.0.0.1:9222/json_version
curl -s http://127.0.0.1:3001/health
curl -s "http://localhost:8080/search?q=test&format=json" | head -c 100
```

---

## 14. Troubleshooting

| Symptom                               | Cause                                | Fix                                                        |
| ------------------------------------- | ------------------------------------ | ---------------------------------------------------------- |
| Gateway CPU at 120%+                  | Bonjour/mDNS loop on VPS             | Add `discovery.mdns.mode: "off"` to openclaw.json          |
| Pipeline returns <15 leads            | SearXNG down or engines blocked      | Check `curl localhost:8080`, restart SearXNG               |
| `enquiry@yelu.sg` emails              | Missing directory domain filter      | Already fixed in code — pull latest                        |
| Gateway uses wrong model              | Started without `.env`               | Use `./server.sh start`, never `node openclaw.mjs gateway` |
| Raw JSON in Telegram                  | Old middleware bug                   | Already fixed in code — pull latest                        |
| Bot silent on long exec               | Background exec returned immediately | Use shell `&` in command string for pipeline               |
| Chrome dies silently                  | Missing `DISPLAY=:10`                | Set `DISPLAY=:10 XAUTHORITY=/root/.Xauthority`             |
| DuckDuckGo 0 results                  | CAPTCHA block                        | Expected — SearXNG + Mojeek are primary                    |
| Email verify timeouts                 | Port 25 blocked                      | Check `telnet gmail-smtp-in.l.google.com 25`               |
| DeepSeek says "Tool X does not exist" | Using Qwen-style tool prompt         | DeepSeek uses `{"tool":"read"}` NOT `code_interpreter`     |
| Qwen says "Tool X does not exist"     | Using DeepSeek-style tool prompt     | Qwen uses `code_interpreter` with `open('/path').read()`   |

---

_End of guide. For questions, check `AGENTS.md` in repo root or ask Kimi on source VPS._
