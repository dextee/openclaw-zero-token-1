#!/usr/bin/env bash
# run_mirae_pipeline.sh — Mirae Advisory v2 lead-gen pipeline wrapper
#
# Usage:
#   ./run_mirae_pipeline.sh --industry "Construction" --target 25 --sender-name "Tom Lee"
#
# Stages:
#   1. leadgen     → run_full_pipeline.py
#   2. dedup       → dedup_score.py (default scoring)
#   3. verify1     → verify_emails.py (initial emails)
#   4. enrich      → enrich_contacts.py (contacts + decision makers)
#   5. verify2     → verify_emails.py (newly discovered emails)
#   6. score       → dedup_score.py --mode mirae
#   7. sequences   → generate_sequences.py
#   8. send        → workspace_smtp_sender.py (dry-run by default; --live-send for real)
#
# Status files: <output-dir>/run_<ts>/status/<stage>.json
# Retries:      1 retry / 30s backoff on leadgen + verify1 + verify2 (network-flaky stages)
# Notifications: per-stage Telegram pings + failure alert + completion summary

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTREACH_DIR="/root/openclaw-zero-token/skills/sg-outreach/scripts"
VERIFY_DIR="/root/openclaw-zero-token/skills/sg-verify/scripts"
ENRICH_DIR="/root/openclaw-zero-token/skills/sg-enrich/scripts"

# ── Defaults ──────────────────────────────────────────────────────────────────
INDUSTRY=""
TARGET=25
OUTPUT_DIR="/root/.openclaw/workspace/leads"
WORKERS_LEADGEN=5
WORKERS_ENRICH=3
DAILY_LIMIT=450
MODE="mirae"
SKIP_SEND=false
SKIP_SEQUENCES=false
LIVE_SEND=false
SENDER_NAME=""
NOTIFY_CHAT_ID="${NOTIFY_CHAT_ID:-}"
QUIET=false
RESUME_FROM=""
# QC defaults to ON (AI junk filter). Pass --no-qc to disable for debugging.
QC=true

# ── Arg parsing ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --industry)        INDUSTRY="$2";        shift 2 ;;
    --target)          TARGET="$2";          shift 2 ;;
    --output-dir)      OUTPUT_DIR="$2";      shift 2 ;;
    --workers-leadgen) WORKERS_LEADGEN="$2"; shift 2 ;;
    --workers-enrich)  WORKERS_ENRICH="$2";  shift 2 ;;
    --daily-limit)     DAILY_LIMIT="$2";     shift 2 ;;
    --mode)            MODE="$2";            shift 2 ;;
    --skip-send)       SKIP_SEND=true;       shift ;;
    --skip-sequences)  SKIP_SEQUENCES=true;  shift ;;
    --live-send)       LIVE_SEND=true;       shift ;;
    --sender-name)     SENDER_NAME="$2";     shift 2 ;;
    --notify-chat-id)  NOTIFY_CHAT_ID="$2";  shift 2 ;;
    --quiet)           QUIET=true;           shift ;;
    --resume-from)     RESUME_FROM="$2";     shift 2 ;;
    --qc)              QC=true;              shift ;;
    --no-qc)           QC=false;             shift ;;
    *)                 echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$INDUSTRY" ]]; then
  echo "Error: --industry is required"
  exit 1
fi

# ── Stage ordering (for --resume-from) ────────────────────────────────────────
declare -A STAGE_IDX=([leadgen]=1 [dedup]=2 [verify1]=3 [enrich]=4 [verify2]=5 [score]=6 [sequences]=7 [send]=8)
RESUME_IDX=0
if [[ -n "$RESUME_FROM" ]]; then
  RESUME_IDX=${STAGE_IDX[$RESUME_FROM]:-0}
  if [[ $RESUME_IDX -eq 0 ]]; then
    echo "Error: unknown --resume-from stage '$RESUME_FROM'."
    echo "Valid stages: leadgen dedup verify1 enrich verify2 score sequences send"
    exit 1
  fi
fi

skip_stage() {
  local stage="$1"
  [[ $RESUME_IDX -eq 0 ]] && return 1       # not resuming → never skip
  local idx=${STAGE_IDX[$stage]:-0}
  [[ $idx -lt $RESUME_IDX ]] && return 0    # before resume point → skip
  return 1
}

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# ── RUN_DIR setup ─────────────────────────────────────────────────────────────
if [[ -n "$RESUME_FROM" ]]; then
  LATEST_RUN=$(ls -td "$OUTPUT_DIR"/run_* 2>/dev/null | head -1 || true)
  if [[ -z "$LATEST_RUN" ]]; then
    echo "Error: --resume-from set but no previous runs found in $OUTPUT_DIR"
    exit 1
  fi
  RUN_DIR="$LATEST_RUN"
  STATUS_DIR="$RUN_DIR/status"
  mkdir -p "$STATUS_DIR"
  echo "Resuming: $RUN_DIR (from stage: $RESUME_FROM)"
else
  RUN_DIR="$OUTPUT_DIR/run_$TIMESTAMP"
  STATUS_DIR="$RUN_DIR/status"
  mkdir -p "$STATUS_DIR"
fi

# ── CSV paths (glob-based for resume, new paths otherwise) ────────────────────
if [[ -n "$RESUME_FROM" ]]; then
  _f() { ls -t "$RUN_DIR"/$1 2>/dev/null | head -1 || true; }
  RAW_CSV=$(_f "sg_leads_raw_*.csv");        RAW_CSV="${RAW_CSV:-$RUN_DIR/sg_leads_raw_${TIMESTAMP}.csv}"
  DEDUP_CSV=$(_f "sg_leads_dedup_*.csv");    DEDUP_CSV="${DEDUP_CSV:-$RUN_DIR/sg_leads_dedup_${TIMESTAMP}.csv}"
  VERIFY1_CSV=$(_f "sg_leads_verify1_*.csv"); VERIFY1_CSV="${VERIFY1_CSV:-$RUN_DIR/sg_leads_verify1_${TIMESTAMP}.csv}"
  ENRICH_CSV=$(_f "sg_leads_enriched_*.csv"); ENRICH_CSV="${ENRICH_CSV:-$RUN_DIR/sg_leads_enriched_${TIMESTAMP}.csv}"
  VERIFY2_CSV=$(_f "sg_leads_verify2_*.csv"); VERIFY2_CSV="${VERIFY2_CSV:-$RUN_DIR/sg_leads_verify2_${TIMESTAMP}.csv}"
  SCORED_CSV=$(_f "sg_leads_scored_*.csv");  SCORED_CSV="${SCORED_CSV:-$RUN_DIR/sg_leads_scored_${TIMESTAMP}.csv}"
  SEQ_CSV=$(_f "sg_sequences_*.csv");        SEQ_CSV="${SEQ_CSV:-$RUN_DIR/sg_sequences_${TIMESTAMP}.csv}"
else
  RAW_CSV="$RUN_DIR/sg_leads_raw_${TIMESTAMP}.csv"
  DEDUP_CSV="$RUN_DIR/sg_leads_dedup_${TIMESTAMP}.csv"
  VERIFY1_CSV="$RUN_DIR/sg_leads_verify1_${TIMESTAMP}.csv"
  ENRICH_CSV="$RUN_DIR/sg_leads_enriched_${TIMESTAMP}.csv"
  VERIFY2_CSV="$RUN_DIR/sg_leads_verify2_${TIMESTAMP}.csv"
  SCORED_CSV="$RUN_DIR/sg_leads_scored_${TIMESTAMP}.csv"
  SEQ_CSV="$RUN_DIR/sg_sequences_${TIMESTAMP}.csv"
fi

STAGE_LOG="$RUN_DIR/pipeline.log"
exec > >(tee -a "$STAGE_LOG")
exec 2> >(tee -a "$STAGE_LOG" >&2)

START_TS=$(date +%s)
STAGE="init"

write_status() {
  local stage="$1" status="$2" msg="${3:-}"
  printf '{"stage":"%s","status":"%s","msg":"%s","ts":"%s"}\n' \
    "$stage" "$status" "$msg" "$(date -Iseconds)" > "$STATUS_DIR/${stage}.json"
}

# ── Telegram helpers ──────────────────────────────────────────────────────────
OPENCLAW_ENV="/root/openclaw-zero-token/.env"
TELEGRAM_ALLOWFROM="/root/.openclaw/credentials/telegram-default-allowFrom.json"
TELEGRAM_BOT_TOKEN=""
NOTIFY_IDS=""

load_notify_config() {
  if [[ -f "$OPENCLAW_ENV" ]]; then
    TELEGRAM_BOT_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$OPENCLAW_ENV" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
  fi
  # Precedence: --notify-chat-id flag > $NOTIFY_CHAT_ID env > $TELEGRAM_CHAT_ID (injected by gateway) > allowFrom broadcast
  if [[ -n "$NOTIFY_CHAT_ID" ]]; then
    NOTIFY_IDS="$NOTIFY_CHAT_ID"
  elif [[ -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    NOTIFY_IDS="$TELEGRAM_CHAT_ID"
  elif [[ -f "$TELEGRAM_ALLOWFROM" ]]; then
    NOTIFY_IDS=$(python3 -c "
import json,sys
try:
  d=json.load(open('$TELEGRAM_ALLOWFROM'))
  print(' '.join(d.get('allowFrom',[])))
except Exception: sys.exit(0)" 2>/dev/null || true)
  fi
}

# Low-level Telegram send with retries. Returns HTTP code (200 = ok).
# Handles 429 (rate limit) with exponential backoff, 5xx with 2 retries.
# Returns "ok" or the last HTTP code seen.
_tg_send_once() {
  local chat_id="$1" msg="$2" parse_mode="$3"
  local max_attempts=3
  local attempt=1
  local http_code="000"
  while [[ $attempt -le $max_attempts ]]; do
    if [[ -n "$parse_mode" ]]; then
      http_code=$(curl -sS --max-time 10 -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${chat_id}" \
        --data-urlencode "text=${msg}" \
        --data-urlencode "parse_mode=${parse_mode}" \
        -o /dev/null -w "%{http_code}" 2>/dev/null || echo "000")
    else
      http_code=$(curl -sS --max-time 10 -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${chat_id}" \
        --data-urlencode "text=${msg}" \
        -o /dev/null -w "%{http_code}" 2>/dev/null || echo "000")
    fi
    # Success
    [[ "$http_code" == "200" ]] && { echo "200"; return 0; }
    # Retry on 429 or 5xx
    if [[ "$http_code" == "429" || "$http_code" =~ ^5 || "$http_code" == "000" ]]; then
      sleep $((attempt * 2))  # 2s, 4s, 6s backoff
      attempt=$((attempt + 1))
      continue
    fi
    # Hard failure (400, 403 chat_id-blocked etc.) — don't retry
    echo "$http_code"
    return 1
  done
  echo "$http_code"
  return 1
}

# Primary send — always tries to deliver. If user's specific chat_id fails
# (blocked / chat not started / invalid), falls back to the admin broadcast
# so we NEVER silently lose an alert.
# Writes audit log to $RUN_DIR/telegram.log.
notify_telegram() {
  local msg="$1"
  [[ "$QUIET" == true ]] && return 0
  if [[ -z "$TELEGRAM_BOT_TOKEN" ]]; then
    [[ -n "${RUN_DIR:-}" ]] && echo "$(date -Iseconds) SKIP no_token: ${msg:0:80}" >> "$RUN_DIR/telegram.log" 2>/dev/null
    return 0
  fi
  if [[ -z "$NOTIFY_IDS" ]]; then
    [[ -n "${RUN_DIR:-}" ]] && echo "$(date -Iseconds) SKIP no_recipients: ${msg:0:80}" >> "$RUN_DIR/telegram.log" 2>/dev/null
    return 0
  fi
  local all_failed=true
  for chat_id in $NOTIFY_IDS; do
    local http_code
    http_code=$(_tg_send_once "$chat_id" "$msg" "Markdown")
    [[ -n "${RUN_DIR:-}" ]] && echo "$(date -Iseconds) http=${http_code} chat=${chat_id}: ${msg:0:80}" >> "$RUN_DIR/telegram.log" 2>/dev/null
    [[ "$http_code" == "200" ]] && all_failed=false
  done
  # FALLBACK: if targeted delivery failed AND NOTIFY_IDS was a single specific user,
  # broadcast to the admin whitelist so the alert isn't lost.
  if [[ "$all_failed" == "true" ]]; then
    local primary_count
    primary_count=$(echo "$NOTIFY_IDS" | wc -w)
    if [[ $primary_count -eq 1 && -f "$TELEGRAM_ALLOWFROM" ]]; then
      local fallback_ids
      fallback_ids=$(python3 -c "
import json,sys
try:
  d=json.load(open('$TELEGRAM_ALLOWFROM'))
  # Exclude the already-tried chat_id
  tried = '${NOTIFY_IDS}'.strip()
  print(' '.join(x for x in d.get('allowFrom',[]) if x != tried))
except Exception: sys.exit(0)" 2>/dev/null || true)
      if [[ -n "$fallback_ids" ]]; then
        for chat_id in $fallback_ids; do
          local fb_code
          fb_code=$(_tg_send_once "$chat_id" "⚠️ *Fallback delivery* (primary recipient ${NOTIFY_IDS} unreachable): ${msg}" "Markdown")
          [[ -n "${RUN_DIR:-}" ]] && echo "$(date -Iseconds) fallback http=${fb_code} chat=${chat_id}: ${msg:0:80}" >> "$RUN_DIR/telegram.log" 2>/dev/null
        done
      fi
    fi
  fi
  return 0
}

# Plain text version — no Markdown parsing. Safer for lead tables with special chars.
notify_plain() {
  local msg="$1"
  [[ "$QUIET" == true ]] && return 0
  [[ -z "$TELEGRAM_BOT_TOKEN" ]] && return 0
  [[ -z "$NOTIFY_IDS" ]] && return 0
  [[ -n "${RUN_DIR:-}" ]] && echo "$(date -Iseconds) plain chat=${NOTIFY_IDS}: ${msg:0:80}" >> "$RUN_DIR/telegram.log" 2>/dev/null
  for chat_id in $NOTIFY_IDS; do
    curl -sS --max-time 10 -X POST \
      "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${chat_id}" \
      --data-urlencode "text=${msg}" \
      -o /dev/null 2>/dev/null || true
  done
  return 0
}

# Code-block version — wraps message in triple backticks + Markdown parse mode
# so Telegram renders it as a monospace code block. Used for lead tables.
notify_codeblock() {
  local msg="$1"
  [[ "$QUIET" == true ]] && return 0
  [[ -z "$TELEGRAM_BOT_TOKEN" ]] && return 0
  [[ -z "$NOTIFY_IDS" ]] && return 0
  local wrapped=$'```\n'"${msg}"$'\n```'
  for chat_id in $NOTIFY_IDS; do
    curl -sS --max-time 10 -X POST \
      "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${chat_id}" \
      --data-urlencode "text=${wrapped}" \
      --data-urlencode "parse_mode=Markdown" \
      -o /dev/null 2>/dev/null || true
  done
  return 0
}

notify_stage_done() {
  local num="$1" name="$2" summary="$3" extra="${4:-}"
  local total=8
  [[ "$SKIP_SEQUENCES" == true ]] && total=6
  local msg="✅ *[${num}/${total}] ${name}* — ${summary}"
  [[ -n "$extra" ]] && msg="${msg} (${extra})"
  notify_telegram "$msg"
}

notify_stage_start() {
  local num="$1" title="$2"
  local total=8
  [[ "$SKIP_SEQUENCES" == true ]] && total=6
  notify_telegram "🔍 *[${num}/${total}]* ${title}"
}

load_notify_config
echo "$(date -Iseconds) pid=$$ industry='${INDUSTRY}' TELEGRAM_CHAT_ID='${TELEGRAM_CHAT_ID:-UNSET}' NOTIFY_IDS='${NOTIFY_IDS:-UNSET}'" >> /tmp/tg_route_debug.log

# ── Retry helper (1 retry / 30s on network-flaky stages) ─────────────────────
run_with_retry() {
  local stage_name="$1" max_retries="$2" backoff_sec="$3"
  shift 3
  local attempt=0 last_exit=0
  while [[ $attempt -le $max_retries ]]; do
    last_exit=0
    "$@" || last_exit=$?
    if [[ $last_exit -eq 0 ]]; then
      if [[ $attempt -gt 0 ]]; then
        echo "[${stage_name}] succeeded on retry ${attempt}"
        write_status "$stage_name" "retried_ok" "succeeded after ${attempt} retry"
      fi
      return 0
    fi
    attempt=$((attempt + 1))
    if [[ $attempt -gt $max_retries ]]; then
      return $last_exit
    fi
    echo "[${stage_name}] attempt ${attempt} failed (exit ${last_exit}) — retrying in ${backoff_sec}s..."
    sleep "$backoff_sec"
  done
  return $last_exit
}

# ── ERR trap (fires on any unrecovered failure) ───────────────────────────────
on_error() {
  local exit_code=$?
  local failed_stage="${STAGE:-unknown}"
  write_status "pipeline" "failed" "Stage ${failed_stage} exited ${exit_code}"
  local tail_log=""
  if [[ -f "$STAGE_LOG" ]]; then
    tail_log=$(tail -n 12 "$STAGE_LOG" 2>/dev/null | head -c 1200)
  fi
  notify_telegram "🚨 *Mirae Pipeline FAILED*
Industry: \`$INDUSTRY\`
Target: $TARGET
Stage: *${failed_stage}* (exit ${exit_code})
Run: \`$RUN_DIR\`

Last log:
\`\`\`
$tail_log
\`\`\`"
  exit $exit_code
}
trap on_error ERR

# ── Pre-flight checks ─────────────────────────────────────────────────────────
STAGE="preflight"
write_status "$STAGE" "running"
echo "=== Pre-flight checks ==="

# Sender name required only when sequences will actually be generated in this run
if [[ "$SKIP_SEQUENCES" == false && -z "$SENDER_NAME" ]]; then
  echo "Error: --sender-name is required when sequences will be generated (Phase 2 resume or full run)"
  notify_telegram "🚨 *Pre-flight FAILED*: No sender name provided for \`$INDUSTRY\`. Reply with your name (e.g. 'Tom Lee') and the bot will retry."
  exit 1
fi

# Output dir writable
if ! touch "$STATUS_DIR/.writetest" 2>/dev/null; then
  write_status "preflight" "failed" "Status dir not writable: $STATUS_DIR"
  notify_telegram "🚨 *Pre-flight FAILED*: output dir not writable: \`$STATUS_DIR\`"
  exit 1
fi
rm -f "$STATUS_DIR/.writetest"

# Python deps
MISSING_DEPS=$(python3 -c "
missing=[]
for m,pkg in [('requests','requests'),('bs4','beautifulsoup4'),('dns.resolver','dnspython')]:
  try: __import__(m)
  except ImportError: missing.append(pkg)
print(' '.join(missing))" 2>/dev/null || true)
if [[ -n "$MISSING_DEPS" ]]; then
  write_status "preflight" "failed" "Missing deps: $MISSING_DEPS"
  notify_telegram "🚨 *Pre-flight FAILED*
Industry: \`$INDUSTRY\`
Missing Python deps: \`$MISSING_DEPS\`
Fix: \`pip install $MISSING_DEPS\`"
  exit 1
fi

# SearXNG (warn only — pipeline falls back to direct search)
if curl -sI --max-time 3 http://127.0.0.1:8080/search > /dev/null 2>&1; then
  echo "SearXNG: OK"
  SEARXNG_OK=true
else
  echo "Warning: SearXNG not reachable — using Yelu.sg + direct fallbacks"
  SEARXNG_OK=false
fi

# Gateway (needed for DM QC via DeepSeek v4 — warn only, QC fail-open)
if curl -sI --max-time 3 http://127.0.0.1:3001/ > /dev/null 2>&1; then
  GATEWAY_OK=true
else
  echo "Warning: OpenClaw gateway not reachable — AI QC will be skipped"
  GATEWAY_OK=false
fi

# Chrome CDP (needed for DeepSeek auth — warn only)
if curl -sI --max-time 3 http://127.0.0.1:9222/json/version > /dev/null 2>&1; then
  CHROME_OK=true
else
  echo "Warning: Chrome CDP not reachable — AI QC will be skipped"
  CHROME_OK=false
fi

# If QC is on but gateway/chrome is down, notify the user upfront
if [[ "$QC" == "true" && ( "$GATEWAY_OK" == "false" || "$CHROME_OK" == "false" ) ]]; then
  notify_telegram "⚠️ *Pre-flight warning*: AI quality checks disabled this run (gateway or Chrome CDP unreachable). Campaign will use token-level filtering only."
fi

# ── Telegram delivery health check ────────────────────────────────────────────
# Ensure the client WILL receive stage notifications. If the primary chat_id
# is blocked/invalid, fall back to admin broadcast and warn the user.
# NOTE: we send a real message rather than a dry-run because Telegram's
# sendChatAction returns 200 even for invalid chats — only sendMessage reveals
# the true state.
if [[ "$QUIET" != "true" && -n "$TELEGRAM_BOT_TOKEN" && -n "$NOTIFY_IDS" ]]; then
  TG_PRIMARY_OK=false
  for chat_id in $NOTIFY_IDS; do
    TG_TEST_CODE=$(_tg_send_once "$chat_id" "🔔 Connection test — your campaign is starting. You'll get stage updates here." "Markdown")
    echo "Telegram preflight for ${chat_id}: http=${TG_TEST_CODE}"
    [[ -n "${RUN_DIR:-}" ]] && echo "$(date -Iseconds) preflight chat=${chat_id} http=${TG_TEST_CODE}" >> "$RUN_DIR/telegram.log" 2>/dev/null
    [[ "$TG_TEST_CODE" == "200" ]] && TG_PRIMARY_OK=true
  done
  # If primary delivery failed AND we have a whitelist, fall back and alert admin
  if [[ "$TG_PRIMARY_OK" == "false" && -f "$TELEGRAM_ALLOWFROM" ]]; then
    ORIGINAL_IDS="$NOTIFY_IDS"
    NOTIFY_IDS=$(python3 -c "
import json
try:
  d=json.load(open('$TELEGRAM_ALLOWFROM'))
  print(' '.join(x for x in d.get('allowFrom',[]) if x != '$ORIGINAL_IDS'.strip()))
except Exception: pass" 2>/dev/null || true)
    if [[ -n "$NOTIFY_IDS" ]]; then
      echo "⚠️ Primary chat_id ${ORIGINAL_IDS} unreachable (http=${TG_TEST_CODE}). Falling back to admin broadcast: ${NOTIFY_IDS}"
      notify_telegram "⚠️ *Telegram delivery issue*: campaign from chat \`${ORIGINAL_IDS}\` (unreachable — http=${TG_TEST_CODE}). Rerouting alerts to admin broadcast. Please ask client to /start the bot."
    else
      echo "Warning: no fallback recipients available"
    fi
  fi
fi

write_status "preflight" "done" "OK (searxng=$SEARXNG_OK gateway=$GATEWAY_OK chrome=$CHROME_OK tg_primary=${TG_PRIMARY_OK:-n/a})"
echo "Pre-flight: OK"
echo ""

# ── Pipeline start ────────────────────────────────────────────────────────────
echo "=== Mirae Pipeline v2 ==="
echo "Industry:    $INDUSTRY"
echo "Target:      $TARGET"
echo "Output:      $RUN_DIR"
echo "Sender:      ${SENDER_NAME:-<not set>}"
echo "Live send:   $LIVE_SEND"
[[ -n "$RESUME_FROM" ]] && echo "Resume from: $RESUME_FROM"
echo ""

if [[ -n "$RESUME_FROM" ]]; then
  notify_telegram "▶️ *Resuming — Phase 2 (Outreach)*

Industry: *${INDUSTRY}*
Sender: *${SENDER_NAME}*

Generating email sequences and dispatching. ~1–2 min."
elif [[ "$SKIP_SEQUENCES" == true ]]; then
  notify_telegram "🚀 *Campaign Started*

Industry: *${INDUSTRY}*
Target: *${TARGET} leads*
Duration: ~4–6 min

I'll update you at each of the 6 stages. Sit tight."
else
  notify_telegram "🚀 *Campaign Started (full pipeline)*

Industry: *${INDUSTRY}*
Target: *${TARGET} leads*
Sender: *${SENDER_NAME:-<unset>}*
Duration: ~5–9 min

I'll update you at each of the 8 stages. Email dispatch will wait for your final confirmation."
fi

# ── Stage 1: Leadgen ──────────────────────────────────────────────────────────
STAGE="leadgen"
if skip_stage "$STAGE"; then
  echo "Skipping: $STAGE"; write_status "$STAGE" "skipped"
else
  write_status "$STAGE" "running"
  notify_stage_start 1 "Searching 11 search engines + Yelu.sg directory for ${INDUSTRY} companies…"
  QC_FLAG=""
  LEADGEN_TARGET=$TARGET
  if [[ "$QC" == "true" ]]; then
    QC_FLAG="--qc"
    # Over-fetch ~1.8x so after QC removes junk (~30-40% typical) we still meet target
    LEADGEN_TARGET=$(( TARGET * 18 / 10 ))
    [[ $LEADGEN_TARGET -lt $((TARGET + 5)) ]] && LEADGEN_TARGET=$((TARGET + 5))
  fi
  run_with_retry "$STAGE" 1 30 \
    python3 "$SCRIPT_DIR/run_full_pipeline.py" \
      "$INDUSTRY" \
      --target "$LEADGEN_TARGET" \
      --output "$RAW_CSV" \
      --workers "$WORKERS_LEADGEN" \
      --min-score 0 \
      $QC_FLAG
  STAT="stage complete"
  if [[ -s "$RAW_CSV" ]]; then
    STAT=$(python3 -c "
import csv
try:
  rows=list(csv.DictReader(open('$RAW_CSV')))
  n=len(rows)
  # Count AI-filtered junk from sibling _rejected.csv
  import os
  rej_path='$RAW_CSV'.replace('.csv','_rejected.csv')
  junk=0
  if os.path.exists(rej_path):
    junk=max(0, len(list(csv.DictReader(open(rej_path))))-0)
  if junk>0:
    print(f'{n} SG companies found (AI quality filter removed {junk} junk entries)')
  else:
    print(f'{n} SG companies found')
except: print('stage complete')
" 2>/dev/null || echo "stage complete")
  fi
  write_status "$STAGE" "done" "$STAT"
  notify_stage_done 1 "Search + AI quality filter" "$STAT"
fi

# ── Stage 2: Dedup + default score ────────────────────────────────────────────
STAGE="dedup"
if skip_stage "$STAGE"; then
  echo "Skipping: $STAGE"; write_status "$STAGE" "skipped"
else
  write_status "$STAGE" "running"
  python3 "$SCRIPT_DIR/dedup_score.py" \
    "$RAW_CSV" \
    -o "$DEDUP_CSV" \
    --mode default
  STAT="stage complete"
  if [[ -s "$DEDUP_CSV" ]]; then
    STAT=$(python3 -c "
import csv
try:
  rows=list(csv.DictReader(open('$DEDUP_CSV')))
  print(f'{len(rows)} unique companies')
except: print('stage complete')
" 2>/dev/null || echo "stage complete")
  fi
  write_status "$STAGE" "done" "$STAT"
  notify_stage_done 2 "Deduplication" "$STAT"
fi

# ── Stage 3: Verify initial emails ────────────────────────────────────────────
# Note: cross-run seen-companies filtering is done inside run_full_pipeline.py
# (before enrichment), so no need to re-filter here.
STAGE="verify1"
if skip_stage "$STAGE"; then
  echo "Skipping: $STAGE"; write_status "$STAGE" "skipped"
else
  write_status "$STAGE" "running"
  notify_stage_start 3 "Checking domain mail servers…"
  if [[ -s "$DEDUP_CSV" ]]; then
    run_with_retry "$STAGE" 1 30 \
      python3 "$VERIFY_DIR/verify_emails.py" \
        "$DEDUP_CSV" \
        --output "$VERIFY1_CSV" \
        --workers 5
  else
    cp "$DEDUP_CSV" "$VERIFY1_CSV"
  fi
  STAT="stage complete"
  if [[ -s "$VERIFY1_CSV" ]]; then
    STAT=$(python3 -c "
import csv
try:
  rows=list(csv.DictReader(open('$VERIFY1_CSV')))
  with_mx=sum(1 for r in rows if (r.get('mx_provider') or '').strip())
  print(f'{with_mx}/{len(rows)} domains have mail servers')
except: print('stage complete')
" 2>/dev/null || echo "stage complete")
  fi
  write_status "$STAGE" "done" "$STAT"
  notify_stage_done 3 "Domain mail-server check" "$STAT"
fi

# ── Stage 4: Enrich contacts ──────────────────────────────────────────────────
STAGE="enrich"
if skip_stage "$STAGE"; then
  echo "Skipping: $STAGE"; write_status "$STAGE" "skipped"
else
  write_status "$STAGE" "running"
  notify_stage_start 4 "Finding decision makers, direct emails & WhatsApp numbers…"
  if [[ -s "$VERIFY1_CSV" ]]; then
    python3 "$ENRICH_DIR/enrich_contacts.py" \
      "$VERIFY1_CSV" \
      --output "$ENRICH_CSV" \
      --workers "$WORKERS_ENRICH" \
      --limit "$TARGET" \
      --no-acra \
      --no-mas
  else
    cp "$VERIFY1_CSV" "$ENRICH_CSV"
  fi
  STAT="stage complete"
  if [[ -s "$ENRICH_CSV" ]]; then
    STAT=$(python3 -c "
import csv
try:
  rows=list(csv.DictReader(open('$ENRICH_CSV')))
  has_dm=sum(1 for r in rows if (r.get('decision_maker_name') or '').strip())
  has_email=sum(1 for r in rows if (r.get('email') or r.get('direct_email') or '').strip())
  has_wa=sum(1 for r in rows if (r.get('whatsapp') or '').strip())
  parts=[]
  parts.append(f'{has_dm} decision makers')
  parts.append(f'{has_email} emails')
  parts.append(f'{has_wa} WhatsApp')
  print(' · '.join(parts))
except: print('stage complete')
" 2>/dev/null || echo "stage complete")
  fi
  write_status "$STAGE" "done" "$STAT"
  notify_stage_done 4 "Contact enrichment" "$STAT"

  # ── Sub-stage: DM quality check via DeepSeek v4 ─────────────────────────────
  # Catches DM contamination that token-match misses (e.g., global HQ founders
  # like Howard Schultz returned for Starbucks Singapore).
  # ALWAYS runs when QC is on, ALWAYS notifies (success, cleared-N, or failed).
  if [[ "$QC" == "true" ]]; then
    if [[ -s "$ENRICH_CSV" ]]; then
      DM_QC_TMP="$ENRICH_CSV.dmqc.csv"
      DM_QC_REJECTED="$ENRICH_CSV.dmqc_rejected.csv"
      DM_QC_LOG="$RUN_DIR/dm_qc.log"
      DM_CLEARED=0
      DM_QC_OK=false
      if python3 "$SCRIPT_DIR/qc_leads.py" \
           "$ENRICH_CSV" -o "$DM_QC_TMP" \
           --rejected-log "$DM_QC_REJECTED" \
           --mode dm --batch-size 30 --no-codeblock > "$DM_QC_LOG" 2>&1; then
        if [[ -s "$DM_QC_TMP" ]]; then
          mv "$DM_QC_TMP" "$ENRICH_CSV"
          [[ -s "$DM_QC_REJECTED" ]] && DM_CLEARED=$(($(wc -l < "$DM_QC_REJECTED") - 1))
          [[ $DM_CLEARED -lt 0 ]] && DM_CLEARED=0
          DM_QC_OK=true
        fi
      fi
      # ALWAYS notify — success or failure
      if [[ "$DM_QC_OK" == "true" ]]; then
        if [[ $DM_CLEARED -gt 0 ]]; then
          notify_telegram "🧹 *AI decision-maker review:* cleared ${DM_CLEARED} suspicious entr$([ $DM_CLEARED -eq 1 ] && echo y || echo ies) (wrong company/geography/global-HQ)"
        else
          notify_telegram "✓ *AI decision-maker review:* all DMs verified as SG-based"
        fi
      else
        notify_telegram "⚠️ *AI decision-maker review:* skipped (LLM timeout) — proceeding with token-level filter only"
      fi
    else
      notify_telegram "ℹ️ *AI decision-maker review:* no enriched data to check"
    fi
  fi
fi

# ── Stage 5: Verify newly discovered emails ───────────────────────────────────
STAGE="verify2"
if skip_stage "$STAGE"; then
  echo "Skipping: $STAGE"; write_status "$STAGE" "skipped"
else
  write_status "$STAGE" "running"
  notify_stage_start 5 "Verifying email deliverability (SMTP check)…"
  if [[ -s "$ENRICH_CSV" ]]; then
    run_with_retry "$STAGE" 1 30 \
      python3 "$VERIFY_DIR/verify_emails.py" \
        "$ENRICH_CSV" \
        --output "$VERIFY2_CSV" \
        --workers 5
  else
    cp "$ENRICH_CSV" "$VERIFY2_CSV"
  fi
  STAT="stage complete"
  if [[ -s "$VERIFY2_CSV" ]]; then
    STAT=$(python3 -c "
import csv
def status_of(r):
  v=(r.get('email_verified') or r.get('email_status') or '').lower()
  return v
try:
  rows=list(csv.DictReader(open('$VERIFY2_CSV')))
  ok=sum(1 for r in rows if status_of(r) in {'valid','true'})
  ca=sum(1 for r in rows if status_of(r) in {'catch_all','catch-all','risky','unverifiable'})
  bad=sum(1 for r in rows if status_of(r) in {'false','invalid','no_mx'})
  parts=[]
  if ok: parts.append(f'{ok} verified')
  if ca: parts.append(f'{ca} catch-all')
  if bad: parts.append(f'{bad} undeliverable')
  summary=', '.join(parts) if parts else f'{len(rows)} checked'
  print(f'{ok+ca} deliverable ({summary})')
except: print('stage complete')
" 2>/dev/null || echo "stage complete")
  fi
  write_status "$STAGE" "done" "$STAT"
  notify_stage_done 5 "Email deliverability verification" "$STAT"
fi

# ── Stage 6: Mirae scoring ────────────────────────────────────────────────────
STAGE="score"
if skip_stage "$STAGE"; then
  echo "Skipping: $STAGE"; write_status "$STAGE" "skipped"
else
  write_status "$STAGE" "running"
  python3 "$SCRIPT_DIR/dedup_score.py" \
    "$VERIFY2_CSV" \
    -o "$SCORED_CSV" \
    --mode "$MODE"
  STAT="stage complete"
  if [[ -s "$SCORED_CSV" ]]; then
    STAT=$(python3 -c "
import csv
from collections import Counter
try:
  rows=list(csv.DictReader(open('$SCORED_CSV')))
  tiers=Counter((r.get('lead_tier') or '').strip() for r in rows)
  order=['Hot','Warm','Cool','Cold']
  parts=[f'{tiers.get(t,0)} {t}' for t in order if tiers.get(t,0)>0]
  print(f\"{len(rows)} leads ranked — {', '.join(parts) if parts else 'all unranked'}\")
except: print('stage complete')
" 2>/dev/null || echo "stage complete")
  fi
  write_status "$STAGE" "done" "$STAT"
  notify_stage_done 6 "Lead scoring" "$STAT"
fi

# ── Stage 7: Generate sequences ───────────────────────────────────────────────
STAGE="sequences"
if skip_stage "$STAGE" || [[ "$SKIP_SEQUENCES" == true ]]; then
  echo "Skipping: $STAGE"; write_status "$STAGE" "skipped"
else
  write_status "$STAGE" "running"
  if [[ -s "$SCORED_CSV" ]]; then
    python3 "$OUTREACH_DIR/generate_sequences.py" \
      "$SCORED_CSV" \
      --output "$SEQ_CSV" \
      --campaign-name "mirae_${TIMESTAMP}" \
      --sender-name "$SENDER_NAME"
  else
    touch "$SEQ_CSV"
  fi
  STAT="stage complete"
  if [[ -s "$SEQ_CSV" ]]; then
    STAT=$(python3 -c "
import csv
try:
  rows=list(csv.DictReader(open('$SEQ_CSV')))
  print(f'{len(rows)} email drafts ready')
except: print('stage complete')
" 2>/dev/null || echo "stage complete")
  fi
  write_status "$STAGE" "done" "$STAT"
  notify_stage_done 7 "Sequences" "$STAT"
fi

# ── Stage 8: Send ─────────────────────────────────────────────────────────────
STAGE="send"
if skip_stage "$STAGE" || [[ "$SKIP_SEQUENCES" == true ]]; then
  echo "Skipping: $STAGE"; write_status "$STAGE" "skipped"
else
  write_status "$STAGE" "running"
  SEND_STAT="skipped"
  if [[ "$SKIP_SEND" == false && -s "$SEQ_CSV" ]]; then
    if [[ "$LIVE_SEND" == true ]]; then
      echo "Sending live..."
      python3 "$OUTREACH_DIR/workspace_smtp_sender.py" \
        --sequences "$SEQ_CSV" \
        --daily-limit "$DAILY_LIMIT"
      SEND_STAT="LIVE sent"
    else
      echo "Dry-run (pass --live-send to send real emails)..."
      python3 "$OUTREACH_DIR/workspace_smtp_sender.py" \
        --sequences "$SEQ_CSV" \
        --daily-limit "$DAILY_LIMIT" \
        --dry-run
      SEND_STAT="dry-run — say 'send live' to dispatch"
    fi
  fi
  write_status "$STAGE" "done" "Send: $SEND_STAT"
  notify_stage_done 8 "Send" "$SEND_STAT"
fi

write_status "pipeline" "done" "All stages completed. Output: $RUN_DIR"
echo ""
echo "=== Pipeline complete ==="
echo "Run directory: $RUN_DIR"

# ── Completion notification with stats ────────────────────────────────────────
DURATION_SEC=$(($(date +%s) - START_TS))
DURATION_MIN=$((DURATION_SEC / 60))
DURATION_REM=$((DURATION_SEC % 60))

ROW_COUNT=0
DM_COUNT=0
WA_COUNT=0
VERIFIED_EMAILS=0
LEAD_TABLE="(no leads)"

TIER_HOT=0; TIER_WARM=0; TIER_COOL=0; TIER_COLD=0
EMAIL_VERIFIED=0; EMAIL_CATCHALL=0; EMAIL_INVALID=0; EMAIL_NONE=0

if [[ -s "$SCORED_CSV" ]]; then
  ROW_COUNT=$(($(wc -l < "$SCORED_CSV" 2>/dev/null || echo 1) - 1))
  [[ $ROW_COUNT -lt 0 ]] && ROW_COUNT=0

  # Build stats + clean columnar lead table
  STATS_RAW=$(python3 -c "
import csv
VERIFIED={'valid','true'}
CATCHALL={'catch_all','catch-all','risky','unknown_deliverable','unverifiable'}
INVALID={'false','invalid','no_mx'}
def trim(s, n):
    s=s.strip()
    return s if len(s)<=n else s[:n-1]+'…'
def status_of(r):
    return (r.get('email_verified') or r.get('email_status') or '').lower().strip()
try:
    rows=list(csv.DictReader(open('$SCORED_CSV', encoding='utf-8-sig')))
    dm=wa=ok=ca=bad=none=0
    tiers={'Hot':0,'Warm':0,'Cool':0,'Cold':0}
    lines=[]
    for i,r in enumerate(rows,1):
        co=trim(r.get('company_name') or '?', 42)
        nm=(r.get('decision_maker_name') or r.get('contact_1_name') or '').strip()
        ti=(r.get('decision_maker_title') or r.get('contact_1_title') or '').strip()
        em=(r.get('email') or r.get('direct_email') or r.get('contact_email') or '').strip()
        ph=(r.get('phone') or r.get('direct_phone') or '').strip()
        wa_n=(r.get('whatsapp') or r.get('whatsapp_number') or '').strip()
        st=status_of(r)
        tier=(r.get('lead_tier') or '').strip()
        if tier in tiers: tiers[tier]+=1
        if nm: dm+=1
        if wa_n: wa+=1
        if em:
            if st in VERIFIED: ok+=1; tag='✓'
            elif st in CATCHALL: ca+=1; tag='~'
            elif st in INVALID: bad+=1; tag='✗'
            else: tag='?'
        else:
            none+=1; tag='—'
        # Line 1: number · company · tier · email status
        l1=f'{i:>2}. {co:<42}  [{tier or \"—\":<4}] {tag}'
        lines.append(l1)
        # Line 2: decision maker (if found)
        if nm:
            dm_str=trim(nm, 30)
            if ti: dm_str += ' · ' + trim(ti, 26)
            lines.append(f'    👤 {dm_str}')
        # Line 3: contact — email, phone, whatsapp
        contact=[]
        if em: contact.append(trim(em, 38))
        if ph: contact.append(ph)
        if wa_n and wa_n!=ph: contact.append(f'WA {wa_n}')
        if contact:
            lines.append('    ' + ' · '.join(contact))
        lines.append('')  # blank line between leads for readability
    table='\\n'.join(lines).rstrip()
    print(f'DM:{dm}|WA:{wa}|OK:{ok}|CA:{ca}|BAD:{bad}|NONE:{none}|HOT:{tiers[\"Hot\"]}|WARM:{tiers[\"Warm\"]}|COOL:{tiers[\"Cool\"]}|COLD:{tiers[\"Cold\"]}')
    print('---TABLE---')
    print(table)
except Exception as e:
    print('DM:0|WA:0|OK:0|CA:0|BAD:0|NONE:0|HOT:0|WARM:0|COOL:0|COLD:0')
    print('---TABLE---')
    print(f'(error building table: {e})')
" 2>/dev/null)

  HEADER=$(echo "$STATS_RAW" | head -1)
  DM_COUNT=$(echo "$HEADER" | grep -oP 'DM:\K[0-9]+' || echo 0)
  WA_COUNT=$(echo "$HEADER" | grep -oP 'WA:\K[0-9]+' || echo 0)
  EMAIL_VERIFIED=$(echo "$HEADER" | grep -oP 'OK:\K[0-9]+' || echo 0)
  EMAIL_CATCHALL=$(echo "$HEADER" | grep -oP 'CA:\K[0-9]+' || echo 0)
  EMAIL_INVALID=$(echo "$HEADER" | grep -oP 'BAD:\K[0-9]+' || echo 0)
  EMAIL_NONE=$(echo "$HEADER" | grep -oP 'NONE:\K[0-9]+' || echo 0)
  TIER_HOT=$(echo "$HEADER" | grep -oP 'HOT:\K[0-9]+' || echo 0)
  TIER_WARM=$(echo "$HEADER" | grep -oP 'WARM:\K[0-9]+' || echo 0)
  TIER_COOL=$(echo "$HEADER" | grep -oP 'COOL:\K[0-9]+' || echo 0)
  TIER_COLD=$(echo "$HEADER" | grep -oP 'COLD:\K[0-9]+' || echo 0)
  VERIFIED_EMAILS=$EMAIL_VERIFIED  # back-compat
  LEAD_TABLE=$(echo "$STATS_RAW" | tail -n +3)
fi

if [[ "$SKIP_SEQUENCES" == true ]]; then
  # ── Phase 1 completion: summary header ────────────────────────────────────
  # Build tier line (omit zero tiers)
  TIER_PARTS=""
  [[ $TIER_HOT  -gt 0 ]] && TIER_PARTS="${TIER_PARTS}${TIER_HOT} Hot · "
  [[ $TIER_WARM -gt 0 ]] && TIER_PARTS="${TIER_PARTS}${TIER_WARM} Warm · "
  [[ $TIER_COOL -gt 0 ]] && TIER_PARTS="${TIER_PARTS}${TIER_COOL} Cool · "
  [[ $TIER_COLD -gt 0 ]] && TIER_PARTS="${TIER_PARTS}${TIER_COLD} Cold · "
  TIER_PARTS="${TIER_PARTS%· }"  # strip trailing " · "
  [[ -z "$TIER_PARTS" ]] && TIER_PARTS="unranked"

  EMAIL_SENDABLE=$((EMAIL_VERIFIED + EMAIL_CATCHALL))

  notify_telegram "✅ *Campaign Ready — ${INDUSTRY}*

📊 *${ROW_COUNT} qualified leads* (${TIER_PARTS})

📧 Emails:
  • ${EMAIL_VERIFIED} verified deliverable
  • ${EMAIL_CATCHALL} catch-all (usable with caution)
  • ${EMAIL_INVALID} undeliverable
  • ${EMAIL_NONE} without email

👥 ${DM_COUNT} decision makers · 📱 ${WA_COUNT} WhatsApp
⏱️ Duration: ${DURATION_MIN}m ${DURATION_REM}s

Full lead list below 👇"

  # ── Full lead table as Telegram code block (split if >3700 chars) ─────────
  TABLE_LEN=${#LEAD_TABLE}
  if [[ $TABLE_LEN -le 3700 ]]; then
    notify_codeblock "${LEAD_TABLE}"
  else
    HALF=$((ROW_COUNT / 2))
    TABLE_A=$(python3 -c "
lines=open('/dev/stdin').read().split('\n\n')
print('\n\n'.join(lines[:$HALF]))
" <<< "$LEAD_TABLE")
    TABLE_B=$(python3 -c "
lines=open('/dev/stdin').read().split('\n\n')
print('\n\n'.join(lines[$HALF:]))
" <<< "$LEAD_TABLE")
    notify_codeblock "${TABLE_A}"
    notify_codeblock "${TABLE_B}"
  fi
  notify_telegram "─────────────────────
*Legend:*  ✓ verified  ·  ~ catch-all  ·  ✗ invalid  ·  — no email

Reply with your *sender name* (e.g. \"Tom Lee\") to generate outreach emails and dispatch."

else
  # ── Full pipeline completion (Phase 2) ─────────────────────────────────────
  SEND_SUMMARY="skipped"
  if [[ "$SKIP_SEND" == false && -s "$SEQ_CSV" ]]; then
    if [[ "$LIVE_SEND" == true ]]; then
      SEND_SUMMARY="✉️ *emails dispatched live*"
    else
      SEND_SUMMARY="✉️ *dry-run complete* — reply 'send live' to dispatch"
    fi
  fi
  # Tier breakdown (skip zeros)
  TIER_PARTS=""
  [[ $TIER_HOT  -gt 0 ]] && TIER_PARTS="${TIER_PARTS}${TIER_HOT} Hot · "
  [[ $TIER_WARM -gt 0 ]] && TIER_PARTS="${TIER_PARTS}${TIER_WARM} Warm · "
  [[ $TIER_COOL -gt 0 ]] && TIER_PARTS="${TIER_PARTS}${TIER_COOL} Cool · "
  [[ $TIER_COLD -gt 0 ]] && TIER_PARTS="${TIER_PARTS}${TIER_COLD} Cold · "
  TIER_PARTS="${TIER_PARTS%· }"
  [[ -z "$TIER_PARTS" ]] && TIER_PARTS="unranked"

  notify_telegram "✅ *Campaign Complete — ${INDUSTRY}*

📊 *${ROW_COUNT} qualified leads* (${TIER_PARTS})
📧 ${EMAIL_VERIFIED} verified · ${EMAIL_CATCHALL} catch-all · ${EMAIL_INVALID} invalid
👥 ${DM_COUNT} decision makers · 📱 ${WA_COUNT} WhatsApp
⏱️ Duration: ${DURATION_MIN}m ${DURATION_REM}s

${SEND_SUMMARY}"

  TABLE_LEN=${#LEAD_TABLE}
  if [[ $TABLE_LEN -le 3700 ]]; then
    notify_codeblock "${LEAD_TABLE}"
  else
    HALF=$((ROW_COUNT / 2))
    TABLE_A=$(python3 -c "
lines=open('/dev/stdin').read().split('\n\n')
print('\n\n'.join(lines[:$HALF]))
" <<< "$LEAD_TABLE")
    TABLE_B=$(python3 -c "
lines=open('/dev/stdin').read().split('\n\n')
print('\n\n'.join(lines[$HALF:]))
" <<< "$LEAD_TABLE")
    notify_codeblock "${TABLE_A}"
    notify_codeblock "${TABLE_B}"
  fi
  notify_telegram "─────────────────────
*Legend:*  ✓ verified  ·  ~ catch-all  ·  ✗ invalid  ·  — no email"
fi
