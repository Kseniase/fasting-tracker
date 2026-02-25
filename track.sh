#!/usr/bin/env bash
# Trigger Oura sync via local API (single-writer backend)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOKEN_FILE="$SCRIPT_DIR/.oura_token"
PORT_FILE="$SCRIPT_DIR/.fasting_server.port"

usage() {
  cat <<'EOF'
Usage:
  ./track.sh [start_date] [end_date]
  ./track.sh --token <oura_token> [start_date] [end_date]
  OURA_TOKEN=<oura_token> ./track.sh [start_date] [end_date]
  ./track.sh --refresh-token [start_date] [end_date]

Notes:
  - start_date/end_date format: YYYY-MM-DD
  - Sync now runs through app_server.py endpoint /api/sync/oura
  - The API server must be running (./run-local.sh or ./start.command)
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
    OURA_TOKEN=""
  fi
else
  OURA_TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
fi

OURA_TOKEN="$(printf '%s' "${OURA_TOKEN:-}" | tr -d '\r\n')"

START_DATE="${positionals[0]:-}"
END_DATE="${positionals[1]:-${START_DATE:-}}"

if [ -n "$START_DATE" ] && ! [[ "$START_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "Error: start_date must be YYYY-MM-DD"
  exit 1
fi
if [ -n "$END_DATE" ] && ! [[ "$END_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "Error: end_date must be YYYY-MM-DD"
  exit 1
fi

PORT="8080"
if [ -f "$PORT_FILE" ]; then
  PORT_CANDIDATE="$(cat "$PORT_FILE" 2>/dev/null || true)"
  if [[ "$PORT_CANDIDATE" =~ ^[0-9]+$ ]]; then
    PORT="$PORT_CANDIDATE"
  fi
fi

API_BASE="${FASTING_API_BASE:-http://127.0.0.1:$PORT}"
HEALTH_URL="$API_BASE/api/health"
SYNC_URL="$API_BASE/api/sync/oura"

if ! curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
  echo "Error: Could not reach local server at $API_BASE"
  echo "Start it with: ./run-local.sh"
  exit 1
fi

payload='{}'
if [ -n "$START_DATE" ]; then
  payload="$(jq -n --arg s "$START_DATE" --arg e "$END_DATE" '{start_date: $s, end_date: $e}')"
fi
if [ -n "$OURA_TOKEN" ]; then
  payload="$(echo "$payload" | jq --arg t "$OURA_TOKEN" '. + {token: $t}')"
fi

response="$(curl -sS -X POST "$SYNC_URL" -H 'Content-Type: application/json' -d "$payload")"
ok="$(echo "$response" | jq -r '.ok // false')"

if [ "$ok" != "true" ]; then
  msg="$(echo "$response" | jq -r '.error // "Unknown error"')"
  echo "Error: $msg"
  exit 1
fi

echo "$response" | jq '{ok, provider, source, start_date, end_date, updated_days}'
