# 🤖 MiraeClaw Bot - Quick Reference Card

## Bot Information
- **Username**: @miraeclawbot
- **Link**: https://t.me/miraeclawbot
- **Token**: `8686771791:AAFMmAvxxSd3m2aqX1vmD-DICo36L0T6Zes` ✅
- **Status**: Configured and ready to activate

---

## 🚀 Quick Start (3 Steps)

### 1️⃣ Start Chrome Debug
```bash
cd /root/openclaw-zero-token
./start-chrome-debug.sh
```
⚠️ **Keep this terminal open!**

### 2️⃣ Start Gateway
```bash
cd /root/openclaw-zero-token
./server.sh start
```

### 3️⃣ Test Bot
- Message **@miraeclawbot** on Telegram
- Send `/start`
- Approve pairing: `node openclaw.mjs pairing approve telegram <CODE>`

---

## 📋 Essential Commands

| Command | Purpose |
|---------|---------|
| `./server.sh start` | Start gateway server |
| `./server.sh stop` | Stop gateway server |
| `./server.sh restart` | Restart gateway server |
| `./server.sh status` | Check server status |
| `node openclaw.mjs pairing list telegram` | View pending pairing requests |
| `node openclaw.mjs pairing approve telegram <CODE>` | Approve user access |
| `node openclaw.mjs pairing reject telegram <CODE>` | Reject user access |

---

## 🔧 Management

### View Logs
```bash
tail -f .openclaw-upstream-state/logs/*.json
```

### Web UI
```
http://127.0.0.1:3001/#token=62b791625fa441be036acd3c206b7e14e2bb13c803355823
```

### Verify Chrome CDP
```bash
curl http://127.0.0.1:9222/json/version
```

---

## ⚙️ Current Configuration

```json5
{
  "telegram": {
    "enabled": true,
    "botToken": "8686771791:AAFMmAvxxSd3m2aqX1vmD-DICo36L0T6Zes",
    "dmPolicy": "pairing",           // Users must be approved
    "groups": {
      "*": {
        "requireMention": true        // Bot responds when @mentioned
      }
    }
  }
}
```

---

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| Bot not responding | `./server.sh restart` |
| Chrome not connecting | Restart `./start-chrome-debug.sh` |
| Pairing expired | User sends `/start` again |
| Check server | `./server.sh status` |

---

## 📝 BotFather Setup (Recommended)

Message **@BotFather**:
1. `/setdescription` - Set bot description
2. `/setabouttext` - Set about section
3. `/setuserpic` - Upload profile picture
4. `/setjoingroups` - Allow adding to groups

---

**Full Documentation**: See `TELEGRAM_SETUP.md` in project directory
