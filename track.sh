#!/bin/bash
# Fetch latest Oura data for fasting tracker

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOKEN_FILE="$SCRIPT_DIR/.oura_token"

if [ ! -f "$TOKEN_FILE" ] || [ "$1" = "--refresh-token" ]; then
  op item get "Oura Token" --format json | jq -r '.fields[] | select(.label=="notesPlain" or .id=="notesPlain") | .value' > "$TOKEN_FILE"
  [ "$1" = "--refresh-token" ] && shift
fi

OURA_TOKEN=$(cat "$TOKEN_FILE")

if [ -z "$OURA_TOKEN" ]; then
  echo "Error: Could not get Oura token. Run with --refresh-token to update."
  exit 1
fi

# Default to last 7 days if no args
START_DATE=${1:-$(date -v-7d +%Y-%m-%d)}
END_DATE=${2:-$(date +%Y-%m-%d)}

echo "=== Oura Data: $START_DATE to $END_DATE ==="
echo

echo "--- Sleep (Summary) ---"
curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/daily_sleep?start_date=$START_DATE&end_date=$END_DATE" | jq '.data[] | {day, score, contributors}'

echo
echo "--- Sleep (Detailed) ---"
curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/sleep?start_date=$START_DATE&end_date=$END_DATE" | jq '.data[] | {day, type, bedtime_start, bedtime_end, total_sleep_hrs: (.total_sleep_duration/3600 | floor * 100 + (. % 3600 / 60) | . / 100), deep_sleep_mins: (.deep_sleep_duration/60), rem_sleep_mins: (.rem_sleep_duration/60), efficiency, lowest_heart_rate, average_hrv}'

echo
echo "--- Readiness ---"
curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/daily_readiness?start_date=$START_DATE&end_date=$END_DATE" | jq '.data[] | {day, score, temperature_deviation, contributors}'

echo
echo "--- Activity ---"
curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/daily_activity?start_date=$START_DATE&end_date=$END_DATE" | jq '.data[] | {day, score, steps, active_calories}'

echo
echo "--- Stress ---"
curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/daily_stress?start_date=$START_DATE&end_date=$END_DATE" | jq '.data[] | {day, day_summary, stress_high_mins: (.stress_high/60), recovery_high_mins: (.recovery_high/60)}'
