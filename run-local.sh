#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT_DIR/.fasting_server.pid"
PORT_FILE="$ROOT_DIR/.fasting_server.port"
LOG_FILE="$ROOT_DIR/.fasting_server.log"
START_PORT="${1:-8080}"

is_running() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

find_open_port() {
  local port="$1"
  while lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1; do
    port=$((port + 1))
    if [ "$port" -gt 8999 ]; then
      return 1
    fi
  done
  echo "$port"
}

if [ -f "$PID_FILE" ]; then
  existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${existing_pid:-}" ] && is_running "$existing_pid"; then
    existing_port="$(cat "$PORT_FILE" 2>/dev/null || echo "$START_PORT")"
    existing_url="http://127.0.0.1:${existing_port}/index.html"
    open "$existing_url" >/dev/null 2>&1 || true
    echo "Fasting Tracker is already running at $existing_url (PID $existing_pid)"
    exit 0
  fi
fi

port="$(find_open_port "$START_PORT")" || {
  echo "Error: Could not find an open port between $START_PORT and 8999."
  exit 1
}

nohup python3 -m http.server "$port" --directory "$ROOT_DIR" >"$LOG_FILE" 2>&1 &
pid=$!
sleep 1

if ! is_running "$pid"; then
  echo "Error: Failed to start server."
  echo "Log: $LOG_FILE"
  tail -n 40 "$LOG_FILE" || true
  exit 1
fi

echo "$pid" > "$PID_FILE"
echo "$port" > "$PORT_FILE"

url="http://127.0.0.1:${port}/index.html"
open "$url" >/dev/null 2>&1 || true

echo "Fasting Tracker started at $url"
echo "Stop it with: $ROOT_DIR/stop-local.sh"
