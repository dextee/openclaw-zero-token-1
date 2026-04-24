#!/bin/bash
# Background enrichment with Telegram notification

INPUT="$1"
OUTPUT="$2"
CHAT_ID="$3"
BOT_TOKEN="$4"

if [ -z "$INPUT" ]; then
    echo "Usage: $0 <input.csv> [output.csv] [chat_id] [bot_token]"
    exit 1
fi

# Default values
OUTPUT="${OUTPUT:-$INPUT.enriched.csv}"
CHAT_ID="${CHAT_ID:-}"
BOT_TOKEN="${BOT_TOKEN:-}"

# Count rows
ROWS=$(tail -n +2 "$INPUT" | wc -l)
EST_TIME=$((ROWS / 5 + 1))  # ~5 min per 25 leads

echo "Starting enrichment for $ROWS companies..."
echo "Estimated time: ~$EST_TIME minutes"

# Send start notification
if [ -n "$BOT_TOKEN" ] && [ -n "$CHAT_ID" ]; then
    curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
        -d "chat_id=$CHAT_ID" \
        -d "text=🔄 Enrichment started for $ROWS companies...~${EST_TIME}min. I'll notify you when done."
fi

# Run enrichment in background
cd /root/openclaw-zero-token
python3 skills/sg-enrich/scripts/enrich_leads.py "$INPUT" --output "$OUTPUT" 2>&1 | tee /tmp/enrich_$$.log

EXIT_CODE=$?

# Send completion notification
if [ -n "$BOT_TOKEN" ] && [ -n "$CHAT_ID" ]; then
    if [ $EXIT_CODE -eq 0 ]; then
        WHATSAPP=$(grep -c ",+65" "$OUTPUT" 2>/dev/null || echo "0")
        SIZE=$(wc -l < "$OUTPUT")
        curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
            -d "chat_id=$CHAT_ID" \
            -d "text=✅ ENRICHMENT COMPLETE!

📁 File: $OUTPUT
• Companies: $((SIZE - 1))
• With WhatsApp: $WHATSAPP

Ready for outreach when you are."
    else
        curl -s -X POST "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
            -d "chat_id=$CHAT_ID" \
            -d "text=❌ Enrichment failed. Check logs."
    fi
fi

echo "Enrichment finished with exit code: $EXIT_CODE"