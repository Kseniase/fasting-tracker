#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT_DIR/.fasting_server.pid"
PORT_FILE="$ROOT_DIR/.fasting_server.port"

if [ ! -f "$PID_FILE" ]; then
  echo "No tracked Fasting Tracker server is running."
  exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"

if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid" 2>/dev/null || true
  sleep 1
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  echo "Stopped Fasting Tracker server (PID $pid)."
else
  echo "Server process was not running."
fi

rm -f "$PID_FILE" "$PORT_FILE"
