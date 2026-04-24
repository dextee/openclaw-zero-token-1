#!/usr/bin/env bash
# telegram_notify.sh — Shared Telegram notification library for MiraeAdvisory pipelines.
#
# Usage: source /root/openclaw-zero-token/lib/telegram_notify.sh
#
# Required env (or auto-loaded):
#   TELEGRAM_BOT_TOKEN  — read from /root/openclaw-zero-token/.env if unset
#   NOTIFY_IDS          — space-separated chat IDs; falls back to TELEGRAM_CHAT_ID env
#                         then to telegram-default-allowFrom.json broadcast
#
# Optional env:
#   TELEGRAM_ALLOWFROM  — path to allowlist JSON (default:
#                         /root/.openclaw/credentials/telegram-default-allowFrom.json)
#   RUN_DIR             — if set, audit logs are written to $RUN_DIR/telegram.log
#   QUIET               — if "true", all notifications are silently skipped
#   NOTIFY_STAGE_TOTAL  — default stage total for notify_stage_done/start (default: 8)

set -uo pipefail

OPENCLAW_ENV="${OPENCLAW_ENV:-/root/openclaw-zero-token/.env}"
TELEGRAM_ALLOWFROM="${TELEGRAM_ALLOWFROM:-/root/.openclaw/credentials/telegram-default-allowFrom.json}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
NOTIFY_IDS="${NOTIFY_IDS:-}"

# ── Config loader ─────────────────────────────────────────────────────────────
load_notify_config() {
  if [[ -z "$TELEGRAM_BOT_TOKEN" && -f "$OPENCLAW_ENV" ]]; then
    TELEGRAM_BOT_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$OPENCLAW_ENV" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
  fi

  # Precedence: explicit NOTIFY_IDS > $NOTIFY_CHAT_ID env > $TELEGRAM_CHAT_ID env > allowFrom broadcast
  if [[ -z "$NOTIFY_IDS" ]]; then
    if [[ -n "${NOTIFY_CHAT_ID:-}" ]]; then
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
  fi
}

# Low-level Telegram send with retries. Returns HTTP code (200 = ok).
# Handles 429 (rate limit) with exponential backoff, 5xx with 2 retries.
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
    return 0
  done
  echo "$http_code"
  return 0
}

# Primary send — always tries to deliver. If user's specific chat_id fails
# (blocked / chat not started / invalid), falls back to the admin broadcast
# so we NEVER silently lose an alert.
# Writes audit log to $RUN_DIR/telegram.log.
notify_telegram() {
  local msg="$1"
  [[ "${QUIET:-}" == "true" ]] && return 0
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
  [[ "${QUIET:-}" == "true" ]] && return 0
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
  [[ "${QUIET:-}" == "true" ]] && return 0
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

# Stage completion notification
notify_stage_done() {
  local num="$1" name="$2" summary="$3" extra="${4:-}"
  local total="${NOTIFY_STAGE_TOTAL:-8}"
  local msg="✅ *[${num}/${total}] ${name}* — ${summary}"
  [[ -n "$extra" ]] && msg="${msg} (${extra})"
  notify_telegram "$msg"
}

# Stage start notification
notify_stage_start() {
  local num="$1" title="$2"
  local total="${NOTIFY_STAGE_TOTAL:-8}"
  notify_telegram "🔍 *[${num}/${total}]* ${title}"
}

# Auto-load config when sourced
load_notify_config
