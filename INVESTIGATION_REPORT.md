# Deep Investigation Report — Gateway Not Responding

## ROOT CAUSE IDENTIFIED

### The Problem
The gateway (PID 90218) IS running and IS polling Telegram. But it responds to messages with
the default model `anthropic/claude-opus-4-6` which has NO API key configured, so it silently
fails.

### WHY It Uses the Wrong Model
The gateway process has **NO `OPENCLAW_CONFIG_PATH` or `OPENCLAW_STATE_DIR` env vars**, so it
falls back to the DEFAULT config path: `~/.openclaw/openclaw.json`.

That config is a **STALE version** from earlier experimentation that has:
- ❌ No `agents.defaults.model` (no model configured)
- ❌ No `tools` section (no tools configured)
- ❌ No `skills` section (no skills loaded)
- ❌ Falls back to default: `anthropic/claude-opus-4-6` (needs API key we don't have)

The **CORRECT** config is at `.openclaw-upstream-state/openclaw.json` which has:
- ✅ `agents.defaults.model.primary: "qwen-web/qwen3.5-plus"`
- ✅ `agents.defaults.model.fallbacks: ["qwen-web/qwen3.6-plus", "deepseek-web/deepseek-chat"]`
- ✅ `tools.profile: "full"` with all tools allowed
- ✅ `tools.fs.workspaceOnly: false`
- ✅ `skills.load.extraDirs: ["/root/openclaw-zero-token/skills"]`
- ✅ Full Telegram config with streaming enabled

### Process Environment Comparison

| Variable | Current Gateway (PID 90218) | What It Should Be |
|----------|---------------------------|-------------------|
| `OPENCLAW_CONFIG_PATH` | NOT SET | `.openclaw-upstream-state/openclaw.json` |
| `OPENCLAW_STATE_DIR` | NOT SET | `.openclaw-upstream-state` |
| `OPENCLAW_GATEWAY_PORT` | NOT SET | `3001` |
| `TELEGRAM_BOT_TOKEN` | ✅ Set correctly | ✅ Set correctly |

### Evidence
```
# Gateway log shows wrong model:
[11:53:26] [gateway] agent model: anthropic/claude-opus-4-6

# Correct config has:
"agents.defaults.model.primary": "qwen-web/qwen3.5-plus"

# Telegram IS polling (getUpdates returns 0 pending = gateway consumed them):
[11:53:27] [telegram] [default] starting provider (@miraeclawbot)

# But model can't respond (no Anthropic API key):
[agents/model-providers] [xai-auth] bootstrap config fallback: no config-backed key found
```

## WHAT CAUSED THIS

When I restarted the gateway earlier, I used:
```bash
setsid node openclaw.mjs gateway --port 3001
```
This started the gateway as a daemon (PPID=1) but WITHOUT the env vars that `server.sh`
normally sets. The `server.sh` script sets:
```bash
export OPENCLAW_CONFIG_PATH="$CONFIG_FILE"
export OPENCLAW_STATE_DIR="$STATE_DIR"
export OPENCLAW_GATEWAY_PORT="$PORT"
export TELEGRAM_BOT_TOKEN="..."
```

But `setsid` doesn't carry these forward.

## THE SIGTERM HISTORY

38 SIGTERM events in logs — ALL from my own restart attempts:
- `./server.sh restart` sends SIGTERM to old PID before starting new
- `./server.sh stop` sends SIGTERM
- `timeout` commands send SIGTERM
- No external watchdog, cron, or systemd service is killing it

## CURRENT STATE (at time of investigation)

| Component | Status | Details |
|-----------|--------|---------|
| Gateway PID 90218 | ✅ Running | Port 3001 listening |
| Telegram channel | ✅ Polling | Consuming updates (0 pending) |
| Chrome CDP | ✅ Running | Port 9222, 16 Chrome processes |
| Qwen auth | ✅ Valid | Token in auth-profiles.json |
| DeepSeek auth | ✅ Valid | Token in auth-profiles.json |
| Model config | ❌ WRONG | Reading stale `~/.openclaw/openclaw.json` |
| Active model | ❌ `anthropic/claude-opus-4-6` | Should be `qwen-web/qwen3.5-plus` |
| Tools config | ❌ Missing | Not loaded from correct config |
| Skills config | ❌ Missing | Not loaded from correct config |

## THE FIX (No code changes needed)

Just restart the gateway WITH the correct environment variables:

```bash
# Kill current gateway
kill 90218 90211

# Start with correct env vars
cd /root/openclaw-zero-token
OPENCLAW_CONFIG_PATH=/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json \
OPENCLAW_STATE_DIR=/root/openclaw-zero-token/.openclaw-upstream-state \
OPENCLAW_GATEWAY_PORT=3001 \
TELEGRAM_BOT_TOKEN="8686771791:AAFMmAvxxSd3m2aqX1vmD-DICo36L0T6Zes" \
node openclaw.mjs gateway --port 3001 &
```

Or better, use `server.sh` which already handles this:
```bash
cd /root/openclaw-zero-token
./server.sh start
```

After restart, verify with:
```bash
# Should show qwen-web/qwen3.5-plus, NOT anthropic/claude-opus-4-6
tail -5 /tmp/openclaw/openclaw-2026-04-09.log | grep "agent model"

# Should show tool injection when message is sent
tail -20 /tmp/openclaw/openclaw-2026-04-09.log | grep "WebStreamMiddleware"
```
