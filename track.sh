#!/bin/bash
# Fetch latest Oura data for fasting tracker

OURA_TOKEN=$(op item get "Oura Token" --format json | jq -r '.fields[] | select(.label=="notesPlain" or .id=="notesPlain") | .value')

if [ -z "$OURA_TOKEN" ]; then
  echo "Error: Could not get Oura token from 1Password"
  exit 1
fi

# Default to last 7 days if no args
START_DATE=${1:-$(date -v-7d +%Y-%m-%d)}
END_DATE=${2:-$(date +%Y-%m-%d)}

echo "=== Oura Data: $START_DATE to $END_DATE ==="
echo

echo "--- Sleep ---"
curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/daily_sleep?start_date=$START_DATE&end_date=$END_DATE" | jq '.data[] | {day, score, contributors}'

echo
echo "--- Readiness ---"
curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/daily_readiness?start_date=$START_DATE&end_date=$END_DATE" | jq '.data[] | {day, score, temperature_deviation, contributors}'

echo
echo "--- Activity ---"
curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/daily_activity?start_date=$START_DATE&end_date=$END_DATE" | jq '.data[] | {day, score, steps, active_calories}'
