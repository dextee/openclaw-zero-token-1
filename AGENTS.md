# AI Assistant Rules — This Machine

> **READ BEFORE TOUCHING ANYTHING.** Applies to Claude Code, Qwen Code, and any other AI coding assistant working in this environment.

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
- NEVER use `/tmp/chrome-debug-profile` — throwaway, no cookies
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
- Primary: `qwen-web/qwen3.5-plus`
- Fallbacks: `qwen-web/qwen3.6-plus` → `deepseek-web/deepseek-v4` → `deepseek-web/deepseek-chat` → `deepseek-web/deepseek-reasoner`
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
- Config path: `~/.openclaw-zero/workspace` (what the gateway reads)
- Mirror: `~/.openclaw/workspace` (keep in sync manually with `cp`)
- Files: `SOUL.md`, `AGENTS.md`, `USER.md`, `IDENTITY.md`, `HEARTBEAT.md`, `TOOLS.md`
- **Both dirs must match** — edit in one, copy to the other

### State directories (CRITICAL):
- **Active state dir:** `/root/openclaw-zero-token/.openclaw-upstream-state/` — contains live config, auth, canvas
- **Stale state dir:** `~/.openclaw/` — contains OLD config from upstream OpenClaw install. DO NOT USE.
- The gateway MUST use `.openclaw-upstream-state/`. If it uses `~/.openclaw/`, it will load empty providers and fall back to `anthropic/claude-opus-4-6` (which has no API key), breaking the bot.

---

## 4. Qwen Web vs DeepSeek — Tool Calling Behaviour

This is critical and caused production bugs. Understand before doing anything with the bot.

### Qwen web (`qwen-web/*`) — native tool system:
Qwen's browser interface has its own tools: `web_search`, `web_extractor`, `code_interpreter`, `image_search`.

When OpenClaw injects `exec`/`read`/`write` via prompt, Qwen's runtime intercepts the call and returns **"Tool X does not exists"** — these are not Qwen native tools.

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

## 5. Absolute Rules (Never Break)

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
11. **NEVER run `node openclaw.mjs gateway` directly** — ALWAYS use `./server.sh start` (or `restart`). Direct invocation skips `.env` loading and can cause the gateway to use the stale `~/.openclaw/` state dir, breaking the bot.

---

## 6. Current State (verified 2026-04-09)

| Component | Status |
|-----------|--------|
| Chrome CDP (port 9222) | Running — profile: `/root/.config/chrome-openclaw-debug` |
| Gateway (port 3001) | Running — `qwen-web/qwen3.5-plus` as primary model |
| Telegram bot @miraeclawbot | Live — 4 users whitelisted |
| Qwen auth | Authenticated — `qwen-web:default` in auth-profiles.json |
| DeepSeek auth | Authenticated — `deepseek-web:default` in auth-profiles.json |
| sg-leadgen | Installed, verified, ready |
| sg-enrich | Installed, verified, ready |
| sg-verify | Installed, verified, ready — port 25 open |
| GitHub CLI | Authenticated as `dextee` |
| Desktop shortcut | Fixed — `/root/Desktop/Chrome-Debug.desktop` |

---

## 7. Key File Map

| File | Purpose |
|------|---------|
|  This file — rules for Claude Code| This file — rules for Claude Code |
| `/root/AGENTS.md` | This file — rules for Qwen Code (identical content) |
| `/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json` | Active OpenClaw config |
| `/root/openclaw-zero-token/.env` | Environment variables |
| `/root/openclaw-zero-token/.openclaw-upstream-state/agents/main/agent/auth-profiles.json` | Browser auth credentials |
| `/root/.openclaw/credentials/telegram-default-allowFrom.json` | Telegram user allowlist |
| `/root/.openclaw-zero/workspace/SOUL.md` | Bot personality + tool rules per model |
| `/root/.openclaw-zero/workspace/AGENTS.md` | Bot workflows + absolute paths |
| `/root/.openclaw-zero/workspace/USER.md` | User profile |
| `/root/Desktop/Chrome-Debug.desktop` | Chrome launcher shortcut (correct flags) |
| `/tmp/openclaw-upstream-gateway.log` | Gateway startup log |
| `/tmp/openclaw/openclaw-YYYY-MM-DD.log` | Gateway runtime log |
| `/root/openclaw-zero-token/server.sh` | Gateway management |
| `/root/openclaw-zero-token/start-chrome-debug.sh` | Chrome launcher (set DISPLAY=:10 first) |
| `/root/openclaw-zero-token/onboard.sh` | Auth onboarding (interactive only) |
| `/root/openclaw-zero-token/CLAUDE_CODE_BRIEF.md` | Full audit brief |

---

## 8. Common Tasks

### Restart everything after a reboot:
```bash
# 1. Start Chrome
DISPLAY=:10 XAUTHORITY=/root/.Xauthority /opt/google/chrome/google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/root/.config/chrome-openclaw-debug \
  --no-first-run --no-default-browser-check \
  --disable-background-networking --disable-sync \
  --no-sandbox --disable-dev-shm-usage --disable-gpu \
  --remote-allow-origins='*' > /tmp/chrome-debug.log 2>&1 &

# 2. Wait and verify
sleep 6 && curl -s http://127.0.0.1:9222/json/version

# 3. Start gateway
cd /root/openclaw-zero-token && ./server.sh start
```

### Add a new model to the fallback chain:
Edit `.openclaw-upstream-state/openclaw.json` → `agents.defaults.model.fallbacks` array, then `./server.sh restart`.

### Add a Telegram user to allowlist:
Edit `/root/.openclaw/credentials/telegram-default-allowFrom.json`, add ID as a string, then `./server.sh restart`.

### Capture DeepSeek auth (when needed):
Open XRDP session → Chrome should be open → log into `chat.deepseek.com` → run `cd /root/openclaw-zero-token && ./onboard.sh webauth` in a terminal → select DeepSeek → done.

### Sync bot workspace files after editing:
```bash
# Always edit in .openclaw-zero/workspace, then mirror to .openclaw/workspace
cp /root/.openclaw-zero/workspace/SOUL.md /root/.openclaw/workspace/SOUL.md
cp /root/.openclaw-zero/workspace/AGENTS.md /root/.openclaw/workspace/AGENTS.md
cp /root/.openclaw-zero/workspace/USER.md /root/.openclaw/workspace/USER.md
```
