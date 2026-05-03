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

# Resolve sender list. New schema (preferred): senders array in active_campaign.json.
# Legacy: single global SMTP config + global state file. We always normalise to a list.
SENDERS_JSON=$(python3 -c "
import json
c = json.load(open('$CAMPAIGN'))
senders = c.get('senders')
if not senders:
    senders = [{
        'email': c.get('sender_email','admin@miraeadvisory.com'),
        'config_file': '$USER_DIR/.workspace_smtp_config.json' if __import__('os').path.exists('$USER_DIR/.workspace_smtp_config.json') else '',
        'state_file': '$USER_DIR/.outreach_state.json',
        'daily_limit': c.get('daily_limit', 25),
    }]
print(json.dumps(senders))
")
NUM_SENDERS=$(python3 -c "import json; print(len(json.loads('$SENDERS_JSON')))")
TODAY=$(TZ=Asia/Singapore date +%Y%m%d)
BACKUP_DIR="$USER_DIR/backups/$TODAY"
mkdir -p "$BACKUP_DIR"
cp "$SEQ_CSV" "$BACKUP_DIR/sequences.csv"

export TELEGRAM_CHAT_ID="$USER_ID"

# Read notify_chat_ids from campaign JSON; fall back to hardcoded team list
NOTIFY_IDS=$(python3 -c "
import json
c = json.load(open('$CAMPAIGN'))
ids = c.get('notify_chat_ids', ['280451401', '498391262', '5996214874', '8667886270'])
print(' '.join(str(i) for i in ids))
" 2>/dev/null || echo "280451401 498391262 5996214874 8667886270")

notify_all() {
  local msg="$1"
  for notify_id in $NOTIFY_IDS; do
    TELEGRAM_CHAT_ID="$notify_id" notify_telegram "$msg"
  done
}

# Idempotency check via sender's state file
STATE_FILE="$USER_DIR/.outreach_state.json"
if [[ -f "$STATE_FILE" ]]; then
  LAST_DATE=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('last_send_date',''))" 2>/dev/null || true)
  SENT_TODAY=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('sent_today',0))" 2>/dev/null || true)
  if [[ "$LAST_DATE" == "$(TZ=Asia/Singapore date +%Y-%m-%d)" && "${SENT_TODAY:-0}" -gt 0 && "$TRIGGER" != "retry" ]]; then
    notify_all "✅ Already sent $SENT_TODAY emails today. Skipping to avoid duplicates."
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
    notify_all "🚨 Sanity cap triggered: $FAIL_COUNT consecutive failures with $PENDING pending. Pausing outreach. Reply 'resume outreach' when fixed."
    touch "$USER_DIR/paused.flag"
    # Comment out crontab line
    python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_control.py --pause --user-id "$USER_ID" --confirm
    exit 1
  fi
fi

notify_all "📬 Daily outreach started — *$NUM_SENDERS senders*, up to *$LIMIT emails total* today."

START=$(date +%s)
ACCUM_LOG="$USER_DIR/last_run.log"
: > "$ACCUM_LOG"  # truncate for fresh run

TOTAL_SENT=0
TOTAL_FAILED=0
TOTAL_SKIPPED=0
RC=0
PER_SENDER_RESULTS=""

# Loop through every configured sender
for i in $(seq 0 $((NUM_SENDERS-1))); do
  SENDER_EMAIL=$(python3 -c "import json; s=json.loads('$SENDERS_JSON')[$i]; print(s.get('email',''))")
  SENDER_CFG=$(python3 -c "import json; s=json.loads('$SENDERS_JSON')[$i]; print(s.get('config_file',''))")
  SENDER_STATE=$(python3 -c "import json; s=json.loads('$SENDERS_JSON')[$i]; print(s.get('state_file',''))")
  SENDER_LIMIT=$(python3 -c "import json; s=json.loads('$SENDERS_JSON')[$i]; print(s.get('daily_limit', 25))")

  CONFIG_ARG=""
  [[ -n "$SENDER_CFG" && -f "$SENDER_CFG" ]] && CONFIG_ARG="--config-file $SENDER_CFG"

  notify_all "📨 Sending up to *$SENDER_LIMIT* from \`$SENDER_EMAIL\`..."

  SENDER_LOG="$USER_DIR/last_run_${i}.log"
  set +o pipefail
  python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_smtp_sender.py \
    --sequences "$SEQ_CSV" --daily-limit "$SENDER_LIMIT" \
    --sender-name "Mirae Advisory" \
    --inter-send-delay-min 30 --inter-send-delay-max 180 \
    --state-file "$SENDER_STATE" $CONFIG_ARG 2>&1 | tee "$SENDER_LOG"
  SENDER_RC=${PIPESTATUS[0]}
  set -o pipefail

  cat "$SENDER_LOG" >> "$ACCUM_LOG"

  SENDER_SENT=$(python3 -c "
import re
log = open('$SENDER_LOG').read()
m = re.search(r'Sent:\s+(\d+)', log)
print(m.group(1) if m else '0')
" 2>/dev/null || echo "0")
  SENDER_FAILED=$(python3 -c "
import re
log = open('$SENDER_LOG').read()
m = re.search(r'Failed:\s+(\d+)', log)
print(m.group(1) if m else '0')
" 2>/dev/null || echo "0")
  SENDER_SKIPPED=$(python3 -c "
import re
log = open('$SENDER_LOG').read()
m = re.search(r'Skipped \(dup\):\s+(\d+)', log)
print(m.group(1) if m else '0')
" 2>/dev/null || echo "0")

  TOTAL_SENT=$((TOTAL_SENT + SENDER_SENT))
  TOTAL_FAILED=$((TOTAL_FAILED + SENDER_FAILED))
  TOTAL_SKIPPED=$((TOTAL_SKIPPED + SENDER_SKIPPED))
  [[ $SENDER_RC -ne 0 ]] && RC=$SENDER_RC

  PER_SENDER_RESULTS="${PER_SENDER_RESULTS}  • ${SENDER_EMAIL}: ${SENDER_SENT} sent, ${SENDER_FAILED} failed
"
done

DUR=$(( $(date +%s) - START ))
ACTUAL_SENT=$TOTAL_SENT
FAILED=$TOTAL_FAILED
SKIPPED=$TOTAL_SKIPPED

echo "$(date -Iseconds)|trigger=$TRIGGER|senders=$NUM_SENDERS|sent=$ACTUAL_SENT|failed=$FAILED|skipped=$SKIPPED|duration_s=$DUR|rc=$RC" >> "$USER_DIR/runs.log"

if [[ $RC -eq 0 ]]; then
  NEXT_RUN=$(python3 -c "
from datetime import datetime, timedelta
import zoneinfo
tz = zoneinfo.ZoneInfo('Asia/Singapore')
now = datetime.now(tz)
d = now.replace(hour=8, minute=0, second=0, microsecond=0)
if d <= now:
    d += timedelta(days=1)
print(d.strftime('%a %d %b, 8am SGT'))
" 2>/dev/null || echo "tomorrow 8am SGT")

  # Step 1: post code-block list of who received today's emails
  python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/outreach_status.py \
    --sent today --user-id "$USER_ID" --notify-chat-id "$USER_ID" || true

  # Step 2: professional success message + per-sender breakdown + command hints
  notify_all "✅ *Daily outreach delivered!*

📬 *$ACTUAL_SENT emails sent today* across $NUM_SENDERS sender(s)
$PER_SENDER_RESULTS
⏱  Total: ${DUR}s ($FAILED failed, $SKIPPED skipped)
📅 Next run: *$NEXT_RUN*

You can reply:
  • *pause outreach* — stop daily sends
  • *resume outreach* — restart daily sends
  • *skip today* — skip the next run only

Type *menu* for the full command list."
else
  notify_all "⚠️ *Outreach failed* (rc=$RC).
Reply *show failures* to see the reasons or *retry today* to retry.
Type *menu* for the full command list."
fi

# Bounce auto-suppression
python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/suppress_bounces.py \
  --log "$USER_DIR/last_run.log" --user-id "$USER_ID" || true

# IMAP reply tracking — check each sender account that has credentials configured
for i in $(seq 0 $((NUM_SENDERS-1))); do
  SENDER_EMAIL=$(python3 -c "import json; s=json.loads('$SENDERS_JSON')[$i]; print(s.get('email',''))" 2>/dev/null || true)
  [[ -z "$SENDER_EMAIL" ]] && continue
  HAS_IMAP=$(python3 -c "
import sys; sys.path.insert(0, '/root/openclaw-zero-token/skills/sg-outreach/scripts')
import imap_auth
a = imap_auth.get_account('$SENDER_EMAIL')
print('yes' if a else 'no')
" 2>/dev/null || echo "no")
  if [[ "$HAS_IMAP" == "yes" ]]; then
    python3 /root/openclaw-zero-token/skills/sg-outreach/scripts/workspace_imap_tracker.py \
      --sequences "$SEQ_CSV" --account-email "$SENDER_EMAIL" 2>>"$USER_DIR/imap_tracker.log" || true
  fi
done

# Backup retention (30 days)
find "$USER_DIR/backups" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null || true
