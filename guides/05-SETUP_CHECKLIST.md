# Setup Checklist — Mirae OpenClaw Zero-Token

> Copy-paste checklist for deploying on a new VPS.
> For explanations, see `00-DEPLOYMENT.md`.

---

## Prerequisites

```bash
apt update && apt install -y python3-pip python3-venv git curl nodejs npm
npm install -g pnpm
```

## 1. Clone Repo

```bash
git clone https://github.com/dextee/Mirae.git /root/openclaw-zero-token
cd /root/openclaw-zero-token
pnpm install
```

## 2. Install Python Dependencies

```bash
pip install dnspython tqdm colorama requests bs4 lxml openpyxl
```

## 3. Install SearXNG

```bash
sudo mkdir -p /opt/searxng
cd /opt/searxng
sudo git clone https://github.com/searxng/searxng.git src
sudo python3 -m venv venv
sudo venv/bin/pip install -e src

# Create settings.yml (see 00-DEPLOYMENT.md Section 3)
# Then start:
nohup venv/bin/python -m searx.webapp > /tmp/searxng.log 2>&1 &
```

## 4. Create Environment File

```bash
cat > /root/openclaw-zero-token/.env << 'EOF'
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_HERE
OPENCLAW_CONFIG_PATH=/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json
OPENCLAW_STATE_DIR=/root/openclaw-zero-token/.openclaw-upstream-state
OPENCLAW_GATEWAY_PORT=3001
EOF
```

## 5. Create Directories

```bash
mkdir -p /root/.openclaw/workspace/leads
mkdir -p /root/.openclaw/workspace/compliance
mkdir -p /root/.openclaw/credentials
```

## 6. Configure OpenClaw

Edit `/root/openclaw-zero-token/.openclaw-upstream-state/openclaw.json`:

```json
{
  "discovery": {
    "mdns": {
      "mode": "off"
    }
  },
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
  },
  "skills": {
    "load": {
      "extraDirs": ["/root/openclaw-zero-token/skills"]
    }
  }
}
```

## 7. Configure Telegram Whitelist

```bash
cat > /root/.openclaw/credentials/telegram-default-allowFrom.json << 'EOF'
["YOUR_TELEGRAM_USER_ID"]
EOF
```

## 8. Configure SMTP (for sg-outreach)

```bash
cp /root/openclaw-zero-token/skills/sg-outreach/.workspace_smtp_config.json.example \
   /root/openclaw-zero-token/skills/sg-outreach/.workspace_smtp_config.json

# Edit with your credentials
```

## 9. Copy Workspace Files

```bash
cp /root/openclaw-zero-token/workspace/SOUL.md /root/.openclaw/workspace/SOUL.md
cp /root/openclaw-zero-token/workspace/AGENTS.md /root/.openclaw/workspace/AGENTS.md

# IMPORTANT: Adapt paths and names in both files for your setup!
# See 00-DEPLOYMENT.md Section 2
```

## 10. Build OpenClaw

```bash
cd /root/openclaw-zero-token
pnpm build
```

## 11. Start Chrome CDP

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

sleep 6
curl -s http://127.0.0.1:9222/json/version
```

## 12. Start Gateway

```bash
cd /root/openclaw-zero-token
./server.sh start
```

## 13. Verify Everything

```bash
# Chrome CDP
curl -s http://127.0.0.1:9222/json/version

# Gateway
curl -s http://127.0.0.1:3001/health

# SearXNG
curl -s "http://localhost:8080/search?q=test&format=json" | head -c 100

# Telegram bot should be polling — check logs
tail -20 /tmp/openclaw/openclaw-$(date +%Y-%m-%d).log | grep telegram
```

## 14. Browser Auth (Interactive — Needs XRDP)

```bash
# 1. Log into provider websites in Chrome:
#    - Qwen: https://chat.qwen.ai
#    - DeepSeek: https://chat.deepseek.com
#
# 2. Capture cookies:
cd /root/openclaw-zero-token && ./onboard.sh webauth
```

---

## Post-Setup: Test Pipeline

```bash
# Quick leadgen test
python3 /root/openclaw-zero-token/skills/sg-leadgen/scripts/run_full_pipeline.py \
  "construction" --target 5 --output /root/.openclaw/workspace/leads/test.csv --qc
```

---

_For detailed explanations of each step, see `00-DEPLOYMENT.md`._
