#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT_DIR/.fasting_server.pid"
PORT_FILE="$ROOT_DIR/.fasting_server.port"
stopped_any=0

stop_pid() {
  local pid="$1"
  if [ -z "${pid:-}" ]; then
    return
  fi
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "Stopped Fasting Tracker server (PID $pid)."
    stopped_any=1
  fi
}

process_cwd_for_pid() {
  local pid="$1"
  lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1
}

is_project_app_server_pid() {
  local pid="$1"
  local cmd
  cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [ -z "$cmd" ] && return 1
  echo "$cmd" | grep -Fq "app_server.py" || return 1
  if echo "$cmd" | grep -Fq "$ROOT_DIR"; then
    return 0
  fi
  local cwd
  cwd="$(process_cwd_for_pid "$pid")"
  [ "$cwd" = "$ROOT_DIR" ]
}

if [ -f "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  stop_pid "$pid"
fi

# Also stop untracked server processes in this project folder.
while IFS= read -r pid; do
  [ -z "$pid" ] && continue
  is_project_app_server_pid "$pid" || continue
  stop_pid "$pid"
done < <(pgrep -f "app_server.py" || true)

rm -f "$PID_FILE" "$PORT_FILE"

if [ "$stopped_any" -eq 0 ]; then
  echo "No Fasting Tracker server process was running."
fi
