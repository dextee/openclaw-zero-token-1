#!/bin/bash
# Auto-refresh OpenAI Codex OAuth token
# Runs via cron to keep the session alive indefinitely

set -e

AUTH_FILE="/root/openclaw-zero-token/.openclaw-upstream-state/agents/main/agent/auth-profiles.json"
TOKEN_URL="https://auth.openai.com/oauth/token"
CLIENT_ID="app_EMoamEEZ73f0CkXaXp7hrann"
LOG_FILE="/var/log/openai-codex-refresh.log"

if [ ! -f "$AUTH_FILE" ]; then
    echo "$(date): Auth file not found: $AUTH_FILE" >> "$LOG_FILE"
    exit 1
fi

# Extract refresh token
REFRESH_TOKEN=$(python3 -c "
import json, sys
with open('$AUTH_FILE') as f:
    data = json.load(f)
profile = data.get('profiles', {}).get('openai-codex:default')
if not profile or profile.get('type') != 'oauth':
    sys.exit(1)
print(profile.get('refresh', ''))
")

if [ -z "$REFRESH_TOKEN" ]; then
    echo "$(date): No refresh token found for openai-codex" >> "$LOG_FILE"
    exit 1
fi

# Call refresh endpoint
RESPONSE=$(curl -s -X POST "$TOKEN_URL" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=refresh_token" \
    -d "client_id=$CLIENT_ID" \
    -d "refresh_token=$REFRESH_TOKEN")

if echo "$RESPONSE" | grep -q '"error"'; then
    echo "$(date): Refresh failed: $RESPONSE" >> "$LOG_FILE"
    exit 1
fi

# Extract new tokens
ACCESS_TOKEN=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))")
NEW_REFRESH_TOKEN=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('refresh_token',''))")
EXPIRES_IN=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('expires_in',''))")

if [ -z "$ACCESS_TOKEN" ] || [ -z "$NEW_REFRESH_TOKEN" ] || [ -z "$EXPIRES_IN" ]; then
    echo "$(date): Invalid response: $RESPONSE" >> "$LOG_FILE"
    exit 1
fi

EXPIRES_TS=$(python3 -c "import time; print(int((time.time() + $EXPIRES_IN) * 1000))")

# Update auth file
python3 << PYEOF
import json
with open('$AUTH_FILE') as f:
    data = json.load(f)

profile = data.get('profiles', {}).get('openai-codex:default')
if profile and profile.get('type') == 'oauth':
    profile['access'] = '$ACCESS_TOKEN'
    profile['refresh'] = '$NEW_REFRESH_TOKEN'
    profile['expires'] = $EXPIRES_TS
    with open('$AUTH_FILE', 'w') as f:
        json.dump(data, f, indent=4)
    print('OK')
else:
    print('PROFILE_NOT_FOUND')
    exit(1)
PYEOF

EXPIRES_HUMAN=$(date -d "@${EXPIRES_TS:0:-3}" "+%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "in ${EXPIRES_IN} seconds")
echo "$(date): Token refreshed. Expires: $EXPIRES_HUMAN" >> "$LOG_FILE"
