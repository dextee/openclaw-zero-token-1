# Troubleshooting Guide — Mirae OpenClaw Zero-Token

> Quick fixes for common production issues.
> For complete setup, see `00-DEPLOYMENT.md`.

---

## Gateway Issues

### Symptom: Gateway CPU at 120%+

**Cause:** Bonjour/mDNS advertising loop on VPS (multicast doesn't work in cloud environments).
**Fix:** Add to `openclaw.json`:

```json
{
  "discovery": {
    "mdns": {
      "mode": "off"
    }
  }
}
```

Then `./server.sh restart`.

### Symptom: Gateway uses wrong model / can't find config

**Cause:** Started without `.env` — stale `~/.openclaw/openclaw.json` takes precedence.
**Fix:** Always use `./server.sh start` (loads `.env`). Never run `node openclaw.mjs gateway` directly.

### Symptom: Raw JSON appearing in Telegram

**Cause:** Old `web-stream-middleware.ts` bug where toolResult bypassed detection.
**Fix:** Already fixed in code. Pull latest from repo.

### Symptom: Gateway won't start — "Port 3001 already in use"

**Cause:** Old gateway process still running.
**Fix:**

```bash
kill $(pgrep -f openclaw-gateway)
./server.sh start
```

---

## Lead Generation Issues

### Symptom: Pipeline returns <15 leads

**Cause:** SearXNG down or all engines blocked.
**Fix:**

```bash
# Check SearXNG
curl -s "http://localhost:8080/search?q=test&format=json" | head -c 100

# Restart SearXNG
cd /opt/searxng && kill $(pgrep -f searx.webapp)
nohup venv/bin/python -m searx.webapp > /tmp/searxng.log 2>&1 &
```

### Symptom: `enquiry@yelu.sg` emails in results

**Cause:** Old dedup bug or missing directory domain filter.
**Fix:** Already fixed in code. `DIRECTORY_DOMAINS` in `dedup_score.py` prevents this.

---

## Model / Auth Issues

### Symptom: DeepSeek says "Tool X does not exist"

**Cause:** Using Qwen-style tool prompt on DeepSeek.
**Fix:** DeepSeek uses `{"tool":"read"}` NOT `code_interpreter`. See `01-SOUL.md` Rule 1.

### Symptom: Qwen says "Tool X does not exist"

**Cause:** Using DeepSeek-style tool prompt on Qwen.
**Fix:** Qwen uses `code_interpreter` with `open('/path').read()`. See `01-SOUL.md` Rule 1.

### Symptom: Model auth expired — "Not authenticated"

**Cause:** Browser cookies expired.
**Fix:**

1. Launch Chrome with correct profile (see `00-DEPLOYMENT.md` Section 10)
2. Log into provider website (Qwen/DeepSeek)
3. Run `./onboard.sh webauth`
4. Select provider — interactive, needs XRDP session

---

## Chrome CDP Issues

### Symptom: Chrome dies silently

**Cause:** Missing `DISPLAY=:10` — terminal shells don't inherit display.
**Fix:**

```bash
DISPLAY=:10 XAUTHORITY=/root/.Xauthority /opt/google/chrome/google-chrome \
  --remote-debugging-port=9222 ...
```

### Symptom: Chrome CDP returns 404 or connection refused

**Cause:** Wrong profile or Chrome not running.
**Fix:**

```bash
# Check
pgrep -f "chrome.*remote-debugging-port=9222"
curl -s http://127.0.0.1:9222/json/version
```

---

## Email / Outreach Issues

### Symptom: Bot silent on long exec (>5 min)

**Cause:** Foreground exec hit gateway 300s timeout.
**Fix:** Use shell `&` in command string for long pipelines. See `01-SOUL.md` Rule 5 (Path B).

### Symptom: Email went to spam

**Cause:** Missing DKIM, spammy subject, generic body.
**Fix:**

1. Enable DKIM in Google Workspace Admin
2. Add `include:_spf.google.com` to SPF
3. Add DMARC: `v=DMARC1; p=quarantine; rua=mailto:admin@yourdomain.com`
4. Use `generate_sequences.py` — NEVER compose email yourself

### Symptom: "Skipped (already contacted)" — can't resend

**Cause:** Email in global outreach history.
**Fix:**

```bash
python3 -c "import json; data=json.load(open('skills/sg-outreach/.outreach_history.json')); data.pop('EMAIL_HERE', None); json.dump(data, open('skills/sg-outreach/.outreach_history.json','w'), indent=2)"
```

---

## Email Verification Issues

### Symptom: verify_emails.py timeouts

**Cause:** Port 25 blocked by VPS provider.
**Fix:**

```bash
telnet gmail-smtp-in.l.google.com 25
```

If connection refused, your VPS blocks port 25. Use fast mode only (`--fast`) or switch VPS.

---

## System Issues

### Symptom: Disk full

**Cause:** Log files accumulating.
**Fix:**

```bash
# Check
df -h /

# Clean old logs
find /tmp/openclaw -name "*.log" -mtime +7 -delete
find /root/.openclaw/workspace/leads -name "*.csv" -mtime +30 -delete
```

### Symptom: Zombie Python processes

**Cause:** Scripts killed by gateway timeout but process didn't clean up.
**Fix:**

```bash
ps aux | grep -E "verify_emails|enrich_contacts|run_full_pipeline" | grep -v grep
kill -9 <PID>
```

---

_For complete setup instructions, see `00-DEPLOYMENT.md`._
