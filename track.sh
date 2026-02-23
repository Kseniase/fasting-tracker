#!/bin/bash
# Fetch latest Oura data and update data.json for fasting tracker

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOKEN_FILE="$SCRIPT_DIR/.oura_token"
DATA_FILE="$SCRIPT_DIR/data.json"

usage() {
  cat <<'EOF'
Usage:
  ./track.sh [start_date] [end_date]
  ./track.sh --token <oura_token> [start_date] [end_date]
  OURA_TOKEN=<oura_token> ./track.sh [start_date] [end_date]
  ./track.sh --refresh-token [start_date] [end_date]

Notes:
  - start_date/end_date format: YYYY-MM-DD
  - --refresh-token pulls token from 1Password ("Oura Token" item) if op is available.
  - Without 1Password, run ./setup-oura-token.sh once to create .oura_token.
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: Required command '$1' is not installed."
    exit 1
  fi
}

require_cmd curl
require_cmd jq
require_cmd bc

if [ ! -f "$DATA_FILE" ]; then
  echo "Error: data file not found at $DATA_FILE"
  exit 1
fi

refresh_token=false
token_arg=""
positionals=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --refresh-token)
      refresh_token=true
      shift
      ;;
    --token)
      shift
      if [ -z "${1:-}" ]; then
        echo "Error: --token requires a value."
        exit 1
      fi
      token_arg="$1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      positionals+=("$1")
      shift
      ;;
  esac
done

if [ "${#positionals[@]}" -gt 2 ]; then
  echo "Error: Too many positional arguments."
  usage
  exit 1
fi

if [ -n "$token_arg" ]; then
  OURA_TOKEN="$token_arg"
elif [ -n "${OURA_TOKEN:-}" ]; then
  OURA_TOKEN="${OURA_TOKEN:-}"
elif [ "$refresh_token" = true ] || [ ! -s "$TOKEN_FILE" ]; then
  if command -v op >/dev/null 2>&1 && op whoami >/dev/null 2>&1; then
    op item get "Oura Token" --format json \
      | jq -r '.fields[] | select(.label=="notesPlain" or .id=="notesPlain") | .value' > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE" 2>/dev/null || true
    OURA_TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
  else
    cat <<EOF
Error: Oura token not found.

Choose one:
  1. Run ./setup-oura-token.sh to save a token locally, or
  2. Set OURA_TOKEN in your shell and rerun, or
  3. Sign in to 1Password CLI (op signin) and run ./track.sh --refresh-token
EOF
    exit 1
  fi
else
  OURA_TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
fi

OURA_TOKEN="$(printf '%s' "$OURA_TOKEN" | tr -d '\r\n')"

if [ -z "$OURA_TOKEN" ]; then
  echo "Error: Oura token is empty."
  echo "Run ./setup-oura-token.sh to configure it."
  exit 1
fi

# Validate token before running the heavier data pipeline.
AUTH_TMP="$(mktemp)"
AUTH_HTTP=$(curl -sS -o "$AUTH_TMP" -w "%{http_code}" \
  -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/personal_info")

if [ "$AUTH_HTTP" != "200" ]; then
  AUTH_MESSAGE="$(jq -r '.message // empty' "$AUTH_TMP" 2>/dev/null || true)"
  rm -f "$AUTH_TMP"
  echo "Error: Oura authentication failed (HTTP $AUTH_HTTP)."
  if [ -n "$AUTH_MESSAGE" ]; then
    echo "Oura API message: $AUTH_MESSAGE"
  fi
  echo "Set a fresh token with ./setup-oura-token.sh and try again."
  exit 1
fi

rm -f "$AUTH_TMP"

# Default: fetch entire fast period (from fast start to tomorrow for in-progress data)
FAST_START=$(jq -r '.fast.start' "$DATA_FILE" | cut -d'T' -f1)
START_DATE=${positionals[0]:-$FAST_START}
END_DATE=${positionals[1]:-$(date -v+1d +%Y-%m-%d)}

echo "=== Fetching Oura Data: $START_DATE to $END_DATE ==="
echo

# Fetch all data
SLEEP_SUMMARY=$(curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/daily_sleep?start_date=$START_DATE&end_date=$END_DATE")

SLEEP_DETAIL=$(curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/sleep?start_date=$START_DATE&end_date=$END_DATE")

READINESS=$(curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/daily_readiness?start_date=$START_DATE&end_date=$END_DATE")

ACTIVITY=$(curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/daily_activity?start_date=$START_DATE&end_date=$END_DATE")

STRESS=$(curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/daily_stress?start_date=$START_DATE&end_date=$END_DATE")

# Display fetched data
echo "--- Sleep Summary ---"
echo "$SLEEP_SUMMARY" | jq '.data[] | {day, score, contributors}'

echo
echo "--- Sleep Detail ---"
echo "$SLEEP_DETAIL" | jq '.data[] | select(.type == "long_sleep") | {day, bedtime_start, bedtime_end, total_hrs: (.total_sleep_duration/3600 | . * 10 | floor | . / 10), deep_mins: (.deep_sleep_duration/60 | floor), rem_mins: (.rem_sleep_duration/60 | floor), light_mins: (.light_sleep_duration/60 | floor), efficiency, lowest_heart_rate, average_hrv}'

echo
echo "--- Readiness ---"
echo "$READINESS" | jq '.data[] | {day, score, temperature_deviation, contributors}'

echo
echo "--- Activity ---"
echo "$ACTIVITY" | jq '.data[] | {day, score, steps, active_calories, total_calories}'

echo
echo "--- Stress ---"
echo "$STRESS" | jq '.data[] | {day, day_summary, stress_high_mins: (.stress_high/60 | floor), recovery_high_mins: (.recovery_high/60 | floor)}'

# Update data.json for each day in the response
echo
echo "=== Updating data.json ==="

# Get fast start date to calculate day number
FAST_START=$(jq -r '.fast.start' "$DATA_FILE" | cut -d'T' -f1)
FAST_START_EPOCH=$(date -j -f "%Y-%m-%d" "$FAST_START" +%s 2>/dev/null || date -d "$FAST_START" +%s)

# Process each day from activity (most reliable for having data)
echo "$ACTIVITY" | jq -r '.data[].day' | while read DAY; do
  [ -z "$DAY" ] && continue

  echo "Processing $DAY..."

  # Calculate day number (days since fast start)
  DAY_EPOCH=$(date -j -f "%Y-%m-%d" "$DAY" +%s 2>/dev/null || date -d "$DAY" +%s)
  DAY_NUM=$(( (DAY_EPOCH - FAST_START_EPOCH) / 86400 ))

  # Extract values for this day
  SLEEP_SCORE=$(echo "$SLEEP_SUMMARY" | jq -r ".data[] | select(.day == \"$DAY\") | .score // null")

  READINESS_SCORE=$(echo "$READINESS" | jq -r ".data[] | select(.day == \"$DAY\") | .score // null")
  TEMP_DEV=$(echo "$READINESS" | jq -r ".data[] | select(.day == \"$DAY\") | .temperature_deviation // null")
  HRV_BALANCE=$(echo "$READINESS" | jq -r ".data[] | select(.day == \"$DAY\") | .contributors.hrv_balance // null")

  ACTIVITY_SCORE=$(echo "$ACTIVITY" | jq -r ".data[] | select(.day == \"$DAY\") | .score // null")
  STEPS=$(echo "$ACTIVITY" | jq -r ".data[] | select(.day == \"$DAY\") | .steps // null")
  TOTAL_CAL=$(echo "$ACTIVITY" | jq -r ".data[] | select(.day == \"$DAY\") | .total_calories // null")
  ACTIVE_CAL=$(echo "$ACTIVITY" | jq -r ".data[] | select(.day == \"$DAY\") | .active_calories // null")

  # Get long_sleep data (primary sleep, not naps)
  SLEEP_DATA=$(echo "$SLEEP_DETAIL" | jq ".data[] | select(.day == \"$DAY\" and .type == \"long_sleep\")")
  if [ -n "$SLEEP_DATA" ]; then
    BEDTIME=$(echo "$SLEEP_DATA" | jq -r '.bedtime_start // null')
    WAKETIME=$(echo "$SLEEP_DATA" | jq -r '.bedtime_end // null')
    TOTAL_SLEEP_SEC=$(echo "$SLEEP_DATA" | jq -r '.total_sleep_duration // 0')
    DEEP_SEC=$(echo "$SLEEP_DATA" | jq -r '.deep_sleep_duration // 0')
    REM_SEC=$(echo "$SLEEP_DATA" | jq -r '.rem_sleep_duration // 0')
    LIGHT_SEC=$(echo "$SLEEP_DATA" | jq -r '.light_sleep_duration // 0')
    EFFICIENCY=$(echo "$SLEEP_DATA" | jq -r '.efficiency // null')
    LOWEST_HR=$(echo "$SLEEP_DATA" | jq -r '.lowest_heart_rate // null')
    AVG_HRV=$(echo "$SLEEP_DATA" | jq -r '.average_hrv // null')
  else
    BEDTIME="null"
    WAKETIME="null"
    TOTAL_SLEEP_SEC="0"
    DEEP_SEC="0"
    REM_SEC="0"
    LIGHT_SEC="0"
    EFFICIENCY="null"
    LOWEST_HR="null"
    AVG_HRV="null"
  fi

  # Convert to hours/mins
  TOTAL_HOURS=$(echo "scale=1; $TOTAL_SLEEP_SEC / 3600" | bc)
  DEEP_MINS=$(echo "$DEEP_SEC / 60" | bc)
  REM_MINS=$(echo "$REM_SEC / 60" | bc)
  LIGHT_MINS=$(echo "$LIGHT_SEC / 60" | bc)

  STRESS_SUMMARY=$(echo "$STRESS" | jq -r ".data[] | select(.day == \"$DAY\") | .day_summary // empty" | head -1)
  [ -z "$STRESS_SUMMARY" ] && STRESS_SUMMARY="null"
  STRESS_HIGH=$(echo "$STRESS" | jq -r ".data[] | select(.day == \"$DAY\") | (.stress_high // 0) / 60 | floor" | head -1)
  [ -z "$STRESS_HIGH" ] && STRESS_HIGH="0"
  RECOVERY_HIGH=$(echo "$STRESS" | jq -r ".data[] | select(.day == \"$DAY\") | (.recovery_high // 0) / 60 | floor" | head -1)
  [ -z "$RECOVERY_HIGH" ] && RECOVERY_HIGH="0"

  # Build sleep object if we have sleep data
  if [ "$TOTAL_SLEEP_SEC" != "0" ] && [ -n "$BEDTIME" ] && [ "$BEDTIME" != "null" ]; then
    SLEEP_OBJ=$(jq -n \
      --arg bedtime "$BEDTIME" \
      --arg wake "$WAKETIME" \
      --argjson hours "$TOTAL_HOURS" \
      --argjson deep "$DEEP_MINS" \
      --argjson rem "$REM_MINS" \
      --argjson light "$LIGHT_MINS" \
      --argjson eff "$EFFICIENCY" \
      --argjson hr "$LOWEST_HR" \
      --argjson hrv "$AVG_HRV" \
      '{bedtime: $bedtime, wake_time: $wake, total_hours: $hours, deep_mins: $deep, rem_mins: $rem, light_mins: $light, efficiency: $eff, lowest_hr: $hr, avg_hrv: $hrv}')
  else
    SLEEP_OBJ="null"
  fi

  # Build stress object
  STRESS_OBJ=$(jq -n \
    --arg summary "$STRESS_SUMMARY" \
    --argjson stress "$STRESS_HIGH" \
    --argjson recovery "$RECOVERY_HIGH" \
    '{summary: (if $summary == "null" or $summary == "" then null else $summary end), stress_mins: $stress, recovery_mins: $recovery}')

  # Check if measurement exists for this day
  EXISTS=$(jq -r ".measurements[] | select(.date == \"$DAY\") | .date" "$DATA_FILE")

  if [ -n "$EXISTS" ]; then
    # Update existing measurement
    echo "  Updating existing entry for $DAY (Day $DAY_NUM)"

    jq --arg day "$DAY" \
       --argjson sleep_score "${SLEEP_SCORE:-null}" \
       --argjson readiness "${READINESS_SCORE:-null}" \
       --argjson activity "${ACTIVITY_SCORE:-null}" \
       --argjson steps "${STEPS:-null}" \
       --argjson total_cal "${TOTAL_CAL:-null}" \
       --argjson active_cal "${ACTIVE_CAL:-null}" \
       --argjson hrv "${HRV_BALANCE:-null}" \
       --argjson temp "${TEMP_DEV:-null}" \
       --argjson sleep_obj "$SLEEP_OBJ" \
       --argjson stress_obj "$STRESS_OBJ" \
       '(.measurements[] | select(.date == $day)) |= . + {
         oura: {
           sleep_score: $sleep_score,
           readiness_score: $readiness,
           activity_score: $activity,
           steps: $steps,
           total_calories: $total_cal,
           active_calories: $active_cal,
           hrv_balance: $hrv,
           body_temp_deviation: $temp,
           sleep: $sleep_obj,
           stress: $stress_obj
         }
       }' "$DATA_FILE" > "$DATA_FILE.tmp" && mv "$DATA_FILE.tmp" "$DATA_FILE"
  else
    # Add new measurement
    echo "  Adding new entry for $DAY (Day $DAY_NUM)"

    jq --arg day "$DAY" \
       --argjson day_num "$DAY_NUM" \
       --argjson sleep_score "${SLEEP_SCORE:-null}" \
       --argjson readiness "${READINESS_SCORE:-null}" \
       --argjson activity "${ACTIVITY_SCORE:-null}" \
       --argjson steps "${STEPS:-null}" \
       --argjson total_cal "${TOTAL_CAL:-null}" \
       --argjson active_cal "${ACTIVE_CAL:-null}" \
       --argjson hrv "${HRV_BALANCE:-null}" \
       --argjson temp "${TEMP_DEV:-null}" \
       --argjson sleep_obj "$SLEEP_OBJ" \
       --argjson stress_obj "$STRESS_OBJ" \
       '.measurements += [{
         date: $day,
         day: $day_num,
         weight_kg: null,
         weight_change_kg: null,
         oura: {
           sleep_score: $sleep_score,
           readiness_score: $readiness,
           activity_score: $activity,
           steps: $steps,
           total_calories: $total_cal,
           active_calories: $active_cal,
           hrv_balance: $hrv,
           body_temp_deviation: $temp,
           sleep: $sleep_obj,
           stress: $stress_obj
         },
         notes: ""
       }]' "$DATA_FILE" > "$DATA_FILE.tmp" && mv "$DATA_FILE.tmp" "$DATA_FILE"
  fi
done

# Add sleep log entries
echo
echo "=== Updating Sleep Log Entries ==="

echo "$SLEEP_DETAIL" | jq -c '.data[] | select(.type == "long_sleep")' | while read -r SLEEP_RECORD; do
  DAY=$(echo "$SLEEP_RECORD" | jq -r '.day')
  BEDTIME_RAW=$(echo "$SLEEP_RECORD" | jq -r '.bedtime_start')
  WAKETIME_RAW=$(echo "$SLEEP_RECORD" | jq -r '.bedtime_end')
  TOTAL_SEC=$(echo "$SLEEP_RECORD" | jq -r '.total_sleep_duration // 0')

  [ -z "$DAY" ] || [ "$DAY" = "null" ] && continue

  # Calculate day number
  DAY_EPOCH=$(date -j -f "%Y-%m-%d" "$DAY" +%s 2>/dev/null || date -d "$DAY" +%s)
  DAY_NUM=$(( (DAY_EPOCH - FAST_START_EPOCH) / 86400 ))

  # Format times for display
  BEDTIME_FMT=$(date -j -f "%Y-%m-%dT%H:%M:%S" "${BEDTIME_RAW%%.*}" "+%-I:%M %p" 2>/dev/null || echo "")
  WAKETIME_FMT=$(date -j -f "%Y-%m-%dT%H:%M:%S" "${WAKETIME_RAW%%.*}" "+%-I:%M %p" 2>/dev/null || echo "")
  TOTAL_HRS=$(echo "scale=1; $TOTAL_SEC / 3600" | bc)

  # Get the bedtime date (day before wake day)
  BEDTIME_DATE=$(echo "$BEDTIME_RAW" | cut -d'T' -f1)
  BEDTIME_DAY_EPOCH=$(date -j -f "%Y-%m-%d" "$BEDTIME_DATE" +%s 2>/dev/null || date -d "$BEDTIME_DATE" +%s)
  BEDTIME_DAY_NUM=$(( (BEDTIME_DAY_EPOCH - FAST_START_EPOCH) / 86400 ))

  # Check if bedtime log entry exists
  BEDTIME_EXISTS=$(jq -r ".log[] | select(.date == \"$BEDTIME_DATE\" and .type == \"sleep\" and (.message | contains(\"Bedtime\"))) | .date" "$DATA_FILE")

  if [ -z "$BEDTIME_EXISTS" ] && [ -n "$BEDTIME_FMT" ]; then
    echo "  Adding bedtime entry for $BEDTIME_DATE"
    jq --arg date "$BEDTIME_DATE" \
       --argjson day "$BEDTIME_DAY_NUM" \
       --arg msg "Bedtime: $BEDTIME_FMT" \
       '.log += [{date: $date, day: $day, type: "sleep", message: $msg}]' "$DATA_FILE" > "$DATA_FILE.tmp" && mv "$DATA_FILE.tmp" "$DATA_FILE"
  fi

  # Check if wake log entry exists
  WAKE_EXISTS=$(jq -r ".log[] | select(.date == \"$DAY\" and .type == \"sleep\" and (.message | contains(\"Woke\"))) | .date" "$DATA_FILE")

  if [ -z "$WAKE_EXISTS" ] && [ -n "$WAKETIME_FMT" ]; then
    echo "  Adding wake entry for $DAY"
    jq --arg date "$DAY" \
       --argjson day "$DAY_NUM" \
       --arg msg "Woke up: $WAKETIME_FMT ($TOTAL_HRS hrs sleep)" \
       '.log += [{date: $date, day: $day, type: "sleep", message: $msg}]' "$DATA_FILE" > "$DATA_FILE.tmp" && mv "$DATA_FILE.tmp" "$DATA_FILE"
  fi
done

# Sort log entries by date
jq '.log |= sort_by(.date, .type)' "$DATA_FILE" > "$DATA_FILE.tmp" && mv "$DATA_FILE.tmp" "$DATA_FILE"

# === REFEED PHASE UPDATES ===
# Check if we're in refeed phase (after fast end date)
REFEED_START=$(jq -r '.refeed.start // empty' "$DATA_FILE" | cut -d'T' -f1)

if [ -n "$REFEED_START" ]; then
  REFEED_START_EPOCH=$(date -j -f "%Y-%m-%d" "$REFEED_START" +%s 2>/dev/null || date -d "$REFEED_START" +%s)

  echo
  echo "=== Updating Refeed Measurements ==="

  # Process each day from activity that falls in refeed period
  echo "$ACTIVITY" | jq -r '.data[].day' | while read DAY; do
    [ -z "$DAY" ] && continue

    DAY_EPOCH=$(date -j -f "%Y-%m-%d" "$DAY" +%s 2>/dev/null || date -d "$DAY" +%s)

    # Skip if before refeed start
    [ "$DAY_EPOCH" -lt "$REFEED_START_EPOCH" ] && continue

    REFEED_DAY_NUM=$(( (DAY_EPOCH - REFEED_START_EPOCH) / 86400 + 1 ))

    echo "Processing refeed day $REFEED_DAY_NUM ($DAY)..."

    # Extract values for this day (same as above)
    SLEEP_SCORE=$(echo "$SLEEP_SUMMARY" | jq -r ".data[] | select(.day == \"$DAY\") | .score // null")
    READINESS_SCORE=$(echo "$READINESS" | jq -r ".data[] | select(.day == \"$DAY\") | .score // null")
    TEMP_DEV=$(echo "$READINESS" | jq -r ".data[] | select(.day == \"$DAY\") | .temperature_deviation // null")
    HRV_BALANCE=$(echo "$READINESS" | jq -r ".data[] | select(.day == \"$DAY\") | .contributors.hrv_balance // null")
    ACTIVITY_SCORE=$(echo "$ACTIVITY" | jq -r ".data[] | select(.day == \"$DAY\") | .score // null")
    STEPS=$(echo "$ACTIVITY" | jq -r ".data[] | select(.day == \"$DAY\") | .steps // null")
    TOTAL_CAL=$(echo "$ACTIVITY" | jq -r ".data[] | select(.day == \"$DAY\") | .total_calories // null")
    ACTIVE_CAL=$(echo "$ACTIVITY" | jq -r ".data[] | select(.day == \"$DAY\") | .active_calories // null")

    # Get sleep data
    SLEEP_DATA=$(echo "$SLEEP_DETAIL" | jq ".data[] | select(.day == \"$DAY\" and .type == \"long_sleep\")")
    if [ -n "$SLEEP_DATA" ]; then
      BEDTIME=$(echo "$SLEEP_DATA" | jq -r '.bedtime_start // null')
      WAKETIME=$(echo "$SLEEP_DATA" | jq -r '.bedtime_end // null')
      TOTAL_SLEEP_SEC=$(echo "$SLEEP_DATA" | jq -r '.total_sleep_duration // 0')
      DEEP_SEC=$(echo "$SLEEP_DATA" | jq -r '.deep_sleep_duration // 0')
      REM_SEC=$(echo "$SLEEP_DATA" | jq -r '.rem_sleep_duration // 0')
      LIGHT_SEC=$(echo "$SLEEP_DATA" | jq -r '.light_sleep_duration // 0')
      EFFICIENCY=$(echo "$SLEEP_DATA" | jq -r '.efficiency // null')
      LOWEST_HR=$(echo "$SLEEP_DATA" | jq -r '.lowest_heart_rate // null')
      AVG_HRV=$(echo "$SLEEP_DATA" | jq -r '.average_hrv // null')
    else
      BEDTIME="null"
      WAKETIME="null"
      TOTAL_SLEEP_SEC="0"
      DEEP_SEC="0"
      REM_SEC="0"
      LIGHT_SEC="0"
      EFFICIENCY="null"
      LOWEST_HR="null"
      AVG_HRV="null"
    fi

    TOTAL_HOURS=$(echo "scale=1; $TOTAL_SLEEP_SEC / 3600" | bc)
    DEEP_MINS=$(echo "$DEEP_SEC / 60" | bc)
    REM_MINS=$(echo "$REM_SEC / 60" | bc)
    LIGHT_MINS=$(echo "$LIGHT_SEC / 60" | bc)

    STRESS_SUMMARY=$(echo "$STRESS" | jq -r ".data[] | select(.day == \"$DAY\") | .day_summary // empty" | head -1)
    [ -z "$STRESS_SUMMARY" ] && STRESS_SUMMARY="null"
    STRESS_HIGH=$(echo "$STRESS" | jq -r ".data[] | select(.day == \"$DAY\") | (.stress_high // 0) / 60 | floor" | head -1)
    [ -z "$STRESS_HIGH" ] && STRESS_HIGH="0"
    RECOVERY_HIGH=$(echo "$STRESS" | jq -r ".data[] | select(.day == \"$DAY\") | (.recovery_high // 0) / 60 | floor" | head -1)
    [ -z "$RECOVERY_HIGH" ] && RECOVERY_HIGH="0"

    # Build sleep object
    if [ "$TOTAL_SLEEP_SEC" != "0" ] && [ -n "$BEDTIME" ] && [ "$BEDTIME" != "null" ]; then
      SLEEP_OBJ=$(jq -n \
        --arg bedtime "$BEDTIME" \
        --arg wake "$WAKETIME" \
        --argjson hours "$TOTAL_HOURS" \
        --argjson deep "$DEEP_MINS" \
        --argjson rem "$REM_MINS" \
        --argjson light "$LIGHT_MINS" \
        --argjson eff "$EFFICIENCY" \
        --argjson hr "$LOWEST_HR" \
        --argjson hrv "$AVG_HRV" \
        '{bedtime: $bedtime, wake_time: $wake, total_hours: $hours, deep_mins: $deep, rem_mins: $rem, light_mins: $light, efficiency: $eff, lowest_hr: $hr, avg_hrv: $hrv}')
    else
      SLEEP_OBJ="null"
    fi

    # Build stress object
    STRESS_OBJ=$(jq -n \
      --arg summary "$STRESS_SUMMARY" \
      --argjson stress "$STRESS_HIGH" \
      --argjson recovery "$RECOVERY_HIGH" \
      '{summary: (if $summary == "null" or $summary == "" then null else $summary end), stress_mins: $stress, recovery_mins: $recovery}')

    # Check if refeed measurement exists for this day
    EXISTS=$(jq -r ".refeed_measurements[] | select(.date == \"$DAY\") | .date" "$DATA_FILE")

    if [ -n "$EXISTS" ]; then
      # Update existing refeed measurement (only oura data, preserve meals/weight)
      echo "  Updating Oura data for refeed day $REFEED_DAY_NUM"

      jq --arg day "$DAY" \
         --argjson sleep_score "${SLEEP_SCORE:-null}" \
         --argjson readiness "${READINESS_SCORE:-null}" \
         --argjson activity "${ACTIVITY_SCORE:-null}" \
         --argjson steps "${STEPS:-null}" \
         --argjson total_cal "${TOTAL_CAL:-null}" \
         --argjson active_cal "${ACTIVE_CAL:-null}" \
         --argjson hrv "${HRV_BALANCE:-null}" \
         --argjson temp "${TEMP_DEV:-null}" \
         --argjson sleep_obj "$SLEEP_OBJ" \
         --argjson stress_obj "$STRESS_OBJ" \
         '(.refeed_measurements[] | select(.date == $day).oura) = {
           sleep_score: $sleep_score,
           readiness_score: $readiness,
           activity_score: $activity,
           steps: $steps,
           total_calories: $total_cal,
           active_calories: $active_cal,
           hrv_balance: $hrv,
           body_temp_deviation: $temp,
           sleep: $sleep_obj,
           stress: $stress_obj
         }' "$DATA_FILE" > "$DATA_FILE.tmp" && mv "$DATA_FILE.tmp" "$DATA_FILE"
    else
      # Add new refeed measurement
      echo "  Adding new refeed entry for day $REFEED_DAY_NUM"

      jq --arg day "$DAY" \
         --argjson refeed_day "$REFEED_DAY_NUM" \
         --argjson sleep_score "${SLEEP_SCORE:-null}" \
         --argjson readiness "${READINESS_SCORE:-null}" \
         --argjson activity "${ACTIVITY_SCORE:-null}" \
         --argjson steps "${STEPS:-null}" \
         --argjson total_cal "${TOTAL_CAL:-null}" \
         --argjson active_cal "${ACTIVE_CAL:-null}" \
         --argjson hrv "${HRV_BALANCE:-null}" \
         --argjson temp "${TEMP_DEV:-null}" \
         --argjson sleep_obj "$SLEEP_OBJ" \
         --argjson stress_obj "$STRESS_OBJ" \
         '.refeed_measurements += [{
           date: $day,
           refeed_day: $refeed_day,
           weight_kg: null,
           weight_change_kg: null,
           calories_consumed: null,
           protein_g: null,
           carbs_g: null,
           meals: [],
           oura: {
             sleep_score: $sleep_score,
             readiness_score: $readiness,
             activity_score: $activity,
             steps: $steps,
             total_calories: $total_cal,
             active_calories: $active_cal,
             hrv_balance: $hrv,
             body_temp_deviation: $temp,
             sleep: $sleep_obj,
             stress: $stress_obj
           },
           notes: ""
         }]' "$DATA_FILE" > "$DATA_FILE.tmp" && mv "$DATA_FILE.tmp" "$DATA_FILE"
    fi
  done
fi

echo
echo "=== Done! ==="
echo "Note: Weight must still be entered manually. Run with a date to update specific day:"
echo "  ./track.sh 2026-01-04"
