# Claude Code Brief — OpenClaw Zero Token Setup

> **READ THIS ENTIRE DOCUMENT BEFORE DOING ANYTHING.** I have already done the full audit. You just need to execute the tasks. No discovery, no research needed.

---

## 📋 CURRENT STATE (Already Audited)

### Project: `/root/openclaw-zero-token`
- **Version:** OpenClaw 2026.3.28
- **Node:** v22.22.2
- **Build:** Fully built (dist/ has 5,255 files, node_modules present)
- **pnpm-lock.yaml:** Present (14,855 lines)

### Config (active): `.openclaw-upstream-state/openclaw.json`
```json
{
  "browser": {
    "attachOnly": true,
    "defaultProfile": "openclaw",
    "profiles": {
      "openclaw": {
        "cdpUrl": "http://127.0.0.1:9222",
        "color": "#4285F4"
      }
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "botToken": "<REDACTED_TELEGRAM_BOT_TOKEN>",
      "dmPolicy": "open",
      "allowFrom": ["*"],
      "groups": { "*": { "requireMention": true } }
    }
  },
  "models": { "mode": "merge", "providers": {} },
  "gateway": {
    "port": 3001, "mode": "local", "bind": "loopback",
    "auth": { "mode": "token", "token": "62b791625fa441be036acd3c206b7e14e2bb13c803355823" }
  }
}
```

### Environment (active): `.env`
```
TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_BOT_TOKEN>
OPENCLAW_CONFIG_PATH=/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json
OPENCLAW_STATE_DIR=/root/openclaw-zero-token/.openclaw-upstream-state
OPENCLAW_GATEWAY_PORT=3001
```

### Key Scripts (all working):
- `./server.sh start|stop|restart|status` — Gateway management
- `./start-chrome-debug.sh` — Launches Chrome with CDP on port 9222
- `./onboard.sh webauth` — Captures browser session credentials
- `node openclaw.mjs gateway --port 3001` — Direct gateway start

### GitHub: ✅ Authenticated as `dextee` (token valid, full scopes)

### Skills Installed:
- ✅ `sg-leadgen` (Singapore B2B lead generation) — SKILL.md + Python scripts present
- ✅ `sg-enrich` (lead enrichment) — SKILL.md + 4 Python scripts present
- ✅ `sg-verify` (email verification) — SKILL.md + Python script present

### Telegram Bot:
- Bot: @miraeclawbot
- Token: `<REDACTED_TELEGRAM_BOT_TOKEN>`
- Config: ✅ Correct in both config file AND .env
- DM Policy: `open` (no pairing needed)
- User 280451401 (@sgmining) is whitelisted in `~/.openclaw/credentials/telegram-default-allowFrom.json`

---

## 🚨 PROBLEMS (All identified)

### Issue 1: SERVICES STATUS (updated 2026-04-08)
- Chrome CDP (port 9222): **RUNNING** — profile: `~/.config/chrome-openclaw-debug`
- Gateway (port 3001): **RUNNING** — started via `./server.sh start`
- `auth-profiles.json`: **DOES NOT EXIST** — webauth not completed yet

### Issue 2: NO AI MODEL PROVIDERS AUTHENTICATED
- `models.providers: {}` is EMPTY but this is CORRECT for zero-token mode
- Web providers are auto-discovered from browser cookies via CDP
- `onboard.sh webauth` has NEVER been run
- Chrome profile at `/tmp/chrome-debug-profile/` has cookies but they're partial:
  - Qwen: Has `token` cookie at `.qwen.ai` (may be valid, may be stale)
  - DeepSeek: Has `ds_session_id` but likely incomplete auth
  - Claude: NO `sessionKey` cookie — not logged in
  - Google/ChatGPT: Has some Google cookies but not ChatGPT session

### Issue 3: CONFIG FILE DUPLICATION
- `~/.openclaw/openclaw.json` exists with DIFFERENT token and paths
- `.env` correctly points to `.openclaw-upstream-state/openclaw.json` (the active one)
- The `~/.openclaw/` config is a leftover from earlier experimentation — it's stale

### Issue 4: STARTUP SEQUENCE NEVER COMPLETED
The correct sequence is:
1. `./start-chrome-debug.sh` → Chrome opens with login tabs
2. User logs into AI platforms in browser
3. `./onboard.sh webauth` → Captures browser session credentials
4. `./server.sh start` → Starts gateway with Telegram + AI providers

Steps 2 and 3 were never completed successfully.

---

## ✅ TASKS FOR CLAUDE CODE

**Execute these in order. Each task is self-contained.**

### Task 1: Start Chrome with CDP Debug
**STATUS: DONE** — Chrome is running on port 9222 with profile `~/.config/chrome-openclaw-debug`.

If Chrome ever needs to be restarted, use EXACTLY this command (the `./start-chrome-debug.sh` script needs `DISPLAY` exported first):
```bash
pkill -f "chrome.*remote-debugging-port=9222" 2>/dev/null; sleep 2
DISPLAY=:10 XAUTHORITY=/root/.Xauthority /opt/google/chrome/google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/root/.config/chrome-openclaw-debug \
  --no-first-run --no-default-browser-check \
  --disable-background-networking --disable-sync \
  --no-sandbox --disable-dev-shm-usage --disable-gpu \
  --remote-allow-origins='*' \
  > /tmp/chrome-debug.log 2>&1 &
sleep 6 && curl -s http://127.0.0.1:9222/json/version
```

**WARNING:** Do NOT use `--user-data-dir=/tmp/chrome-debug-profile` — that profile has no cookies.

### Task 2: Instruct User to Log In
Tell the user: "Open Chrome on your remote desktop (or use the Chrome-Debug.desktop icon), log into at least ONE of these: Claude (claude.ai), Qwen (chat.qwen.ai), DeepSeek (chat.deepseek.com), or ChatGPT (chatgpt.com). Then tell me which ones you logged into."

### Task 3: Run Onboard WebAuth
Once user confirms login:
```bash
cd /root/openclaw-zero-token
./onboard.sh webauth
```
This captures browser session cookies and writes to `.openclaw-upstream-state/agents/main/agent/auth-profiles.json`.

**If `onboard.sh webauth` fails or is interactive**, manually extract cookies:
```bash
# Use OpenClaw's browser CLI to extract cookies
cd /root/openclaw-zero-token
node openclaw.mjs browser cookies --target-id "$(curl -s http://127.0.0.1:9222/json/list 2>/dev/null | python3 -c "
import sys, json
tabs = json.load(sys.stdin)
for t in tabs:
    if 'claude' in t.get('url','').lower():
        print(t.get('id','')); exit()
")"
```

### Task 4: Verify Auth Profiles Created
```bash
cat /root/openclaw-zero-token/.openclaw-upstream-state/agents/main/agent/auth-profiles.json 2>/dev/null | python3 -m json.tool | head -30
```
Should show auth profiles for logged-in providers.

### Task 5: Start Gateway
**STATUS: DONE** — Gateway is running on port 3001 (PID managed by `./server.sh`).

If gateway needs restart:
```bash
cd /root/openclaw-zero-token
./server.sh restart
./server.sh status
```

### Task 6: Verify Telegram Bot
```bash
cd /root/openclaw-zero-token
node openclaw.mjs pairing list telegram
```

Then tell the user: "Send a message to @miraeclawbot on Telegram. It should respond."

### Task 7: Test End-to-End
Wait for user to message the bot, then check logs:
```bash
tail -50 /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try:
        data = json.loads(line)
        time = data.get('time', '')
        msg = str(data.get('0', '')) + str(data.get('1', ''))
        print(f'{time}: {msg[:200]}')
    except: pass
" | tail -20
```

---

## 📁 KEY FILE PATHS

| Path | Purpose |
|------|---------|
| `/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json` | Active config |
| `/root/openclaw-zero-token/.env` | Environment variables |
| `/root/openclaw-zero-token/.openclaw-upstream-state/agents/main/agent/auth-profiles.json` | Browser auth credentials (created by onboard) |
| `/root/.openclaw/credentials/telegram-default-allowFrom.json` | Telegram user allowlist |
| `/root/.openclaw/credentials/telegram-pairing.json` | Telegram pairing store |
| `/tmp/chrome-debug-profile/` | Chrome browser profile (for CDP) |
| `/tmp/openclaw/openclaw-YYYY-MM-DD.log` | Gateway runtime logs |
| `/tmp/openclaw-upstream-gateway.log` | Gateway startup logs |
| `/root/openclaw-zero-token/server.sh` | Gateway management script |
| `/root/openclaw-zero-token/start-chrome-debug.sh` | Chrome launcher |
| `/root/openclaw-zero-token/onboard.sh` | Auth onboarding wizard |

---

## ⚠️ IMPORTANT RULES

1. **NEVER run `openclaw doctor --fix`** — it will break the config
2. **Use `pnpm` not `npm`** for any package operations
3. **Use `node openclaw.mjs`** not `npx openclaw` for CLI commands
4. **The active config** is `.openclaw-upstream-state/openclaw.json` (NOT `~/.openclaw/openclaw.json`)
5. **Chrome CDP port:** 9222
6. **Gateway port:** 3001
7. **Model providers are auto-discovered** from browser auth — DO NOT manually add provider entries to config
8. **Telegram config is correct** — DO NOT change it
9. **Chrome profile** MUST be `/root/.config/chrome-openclaw-debug` — NOT `/tmp/chrome-debug-profile`
10. **Always set `DISPLAY=:10 XAUTHORITY=/root/.Xauthority`** before any GUI/Chrome command — the shell has no display by default
11. **`onboard.sh webauth` is interactive** — do NOT try to run it non-interactively or background it; it requires the user to interact with a wizard
12. **Do NOT try to read Chrome cookies via CDP websocket from terminal** — it times out; use `onboard.sh webauth` instead
13. **See `/root/CLAUDE.md`** for full environment rules (applies to all work on this machine)

---

## 🎯 END STATE

When all tasks are complete, the user should be able to:
1. Message @miraeclawbot on Telegram
2. Bot responds with AI-generated replies (using browser-auth'd providers)
3. Skills (sg-leadgen, sg-enrich, sg-verify) are available for use
4. Gateway is running on port 3001 with Web UI accessible
5. Chrome is running on port 9222 for ongoing browser auth
