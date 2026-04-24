#!/bin/bash
# daily_outreach.sh — Daily 8am outreach wrapper for a single user.
#
# Usage:
#   bash daily_outreach.sh --user-id <chat_id> [--trigger scheduled|manual|retry]

set -euo pipefail
source /root/openclaw-zero-token/lib/telegram_notify.sh

USER_ID=""; TRIGGER="scheduled"
while [[ $# -gt 0 ]]; do case "$1" in
  --user-id) USER_ID="$2"; shift 2;;
  --trigger) TRIGGER="$2"; shift 2;;
  *) shift;;
esac; done

[[ -z "$USER_ID" ]] && { echo "FATAL: --user-id required"; exit 2; }

USER_DIR="/root/.openclaw/workspace/outreach/user_${USER_ID}"
LOCK="/tmp/mirae_outreach_${USER_ID}.lock"
exec 9>"$LOCK"
flock -n 9 || { echo "Another run in progress"; exit 3; }

CAMPAIGN="$USER_DIR/active_campaign.json"
[[ ! -f "$CAMPAIGN" ]] && { export TELEGRAM_CHAT_ID="$USER_ID"; notify_telegram "❌ No active campaign. Run 'setup outreach' first."; exit 4; }
[[ -f "$USER_DIR/paused.flag" ]] && { export TELEGRAM_CHAT_ID="$USER_ID"; notify_telegram "⏸ Outreach paused. Today skipped."; exit 0; }

SEQ_CSV=$(python3 -c "import json; print(json.load(open('$CAMPAIGN'))['sequences_csv'])")
LIMIT=$(python3 -c "import json; print(json.load(open('$CAMPAIGN'))['daily_limit'])")
TODAY=$(TZ=Asia/Singapore date +%Y%m%d)
BACKUP_DIR="$USER_DIR/backups/$TODAY"
mkdir -p "$BACKUP_DIR"
cp "$SEQ_CSV" "$BACKUP_DIR/sequences.csv"

export TELEGRAM_CHAT_ID="$USER_ID"

# Idempotency check via sender's state file
STATE_FILE="$USER_DIR/.outreach_state.json"
if [[ -f "$STATE_FILE" ]]; then
  LAST_DATE=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('last_send_date',''))" 2>/dev/null || true)
  SENT_TODAY=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('sent_today',0))" 2>/dev/null || true)
  if [[ "$LAST_DATE" == "$(TZ=Asia/Singapore date +%Y-%m-%d)" && "${SENT_TODAY:-0}" -gt 0 && "$TRIGGER" != "retry" ]]; then
    notify_telegram "✅ Already sent $SENT_TODAY emails today. Skipping to avoid duplicates."
    exit 0
  fi
fi

# Sanity cap: check last 5 runs for consecutive failures
RUNS_LOG="$USER_DIR/runs.log"
if [[ -f "$RUNS_LOG" ]]; then
  FAIL_COUNT=$(python3 -c "
import sys
lines = open('$RUNS_LOG').read().strip().splitlines()
last5 = lines[-5:]
failures = 0
for line in last5:
    if 'sent=0' in line and 'rc=' in line and 'rc=0' not in line:
        failures += 1
print(failures)
" 2>/dev/null || echo 0)
  PENDING=$(python3 -c "
import csv, sys
rows = list(csv.DictReader(open('$SEQ_CSV', encoding='utf-8-sig')))
pending = [r for r in rows if r.get('status') in ('', 'pending')]
print(len(pending))
" 2>/dev/null || echo 0)
  if [[ "$FAIL_COUNT" -ge 3 && "$PENDING" -gt 0 ]]; then
    notify_telegram "🚨 Sanity cap triggered: $FAIL_COUNT consecutive failures with $PENDING pending. Pausing outreach. Reply 'resume outreach' when fixed."
    touch "$USER_DIR/paused.flag"
    # Comment out crontab line
    python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_control.py --pause --user-id "$USER_ID" --confirm
    exit 1
  fi
fi

notify_telegram "📬 Daily outreach started — sending up to $LIMIT emails."

START=$(date +%s)

# Per-user SMTP config resolution
GLOBAL_CONFIG="/root/openclaw-zero-token/skills/sg-outreach/.workspace_smtp_config.json"
USER_CONFIG="$USER_DIR/.workspace_smtp_config.json"
CONFIG_ARG=""
if [[ -f "$USER_CONFIG" ]]; then
  CONFIG_ARG="--config-file $USER_CONFIG"
fi

# Disable pipefail temporarily so we can capture sender exit code
set +o pipefail
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_smtp_sender.py \
  --sequences "$SEQ_CSV" --daily-limit "$LIMIT" \
  --state-file "$STATE_FILE" $CONFIG_ARG 2>&1 | tee "$USER_DIR/last_run.log"
RC=${PIPESTATUS[0]}
set -o pipefail

DUR=$(( $(date +%s) - START ))

SENT=$(grep -c '^Sent to ' "$USER_DIR/last_run.log" 2>/dev/null || true)
FAILED=$(grep -c '^FAILED: ' "$USER_DIR/last_run.log" 2>/dev/null || true)
SKIPPED=$(grep -c '^Skipped' "$USER_DIR/last_run.log" 2>/dev/null || true)

# Parse actual sent count from sender summary (more reliable than grep)
ACTUAL_SENT=$(python3 -c "
import re, sys
log = open('$USER_DIR/last_run.log').read()
m = re.search(r'Sent:\s+(\d+)', log)
print(m.group(1) if m else '0')
" 2>/dev/null || echo "$SENT")

echo "$(date -Iseconds)|trigger=$TRIGGER|sent=$ACTUAL_SENT|failed=$FAILED|skipped=$SKIPPED|duration_s=$DUR|rc=$RC" >> "$USER_DIR/runs.log"

if [[ $RC -eq 0 ]]; then
  notify_telegram "✅ Daily outreach done: $ACTUAL_SENT sent, $FAILED failed, $SKIPPED skipped (${DUR}s).\nNext run tomorrow 8am SGT."
  # Post next-25 preview
  python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_status.py \
    --user-id "$USER_ID" --preview-next 25 --notify-chat-id "$USER_ID" || true
else
  notify_telegram "⚠️ Outreach failed (rc=$RC). Reply 'show failures' to see details or 'retry today' to retry."
fi

# Bounce auto-suppression
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/suppress_bounces.py \
  --log "$USER_DIR/last_run.log" --user-id "$USER_ID" || true

# Backup retention (30 days)
find "$USER_DIR/backups" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null || true
