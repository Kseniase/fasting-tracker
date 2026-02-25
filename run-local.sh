#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT_DIR/.fasting_server.pid"
PORT_FILE="$ROOT_DIR/.fasting_server.port"
LOG_FILE="$ROOT_DIR/.fasting_server.log"
ENV_FILE="$ROOT_DIR/.env.local"
START_PORT="${1:-8080}"

load_local_env() {
  if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
  fi
}

auto_configure_minimax_ca() {
  if [ "$(uname -s)" != "Darwin" ]; then
    return
  fi
  if [ -n "${MINIMAX_INSECURE_SKIP_VERIFY:-}" ] || [ -n "${MINIMAX_CA_FILE:-}" ] || [ -n "${SSL_CERT_FILE:-}" ]; then
    return
  fi

  local cert_dir="$ROOT_DIR/.certs"
  local bundle="$cert_dir/macos-keychain-ca.pem"
  mkdir -p "$cert_dir"

  local keychains=(
    "/System/Library/Keychains/SystemRootCertificates.keychain"
    "/Library/Keychains/System.keychain"
  )
  if [ -f "$HOME/Library/Keychains/login.keychain-db" ]; then
    keychains+=("$HOME/Library/Keychains/login.keychain-db")
  fi
  if [ -f "$HOME/Library/Keychains/login.keychain" ]; then
    keychains+=("$HOME/Library/Keychains/login.keychain")
  fi

  if security find-certificate -a -p "${keychains[@]}" >"$bundle" 2>/dev/null && [ -s "$bundle" ]; then
    export MINIMAX_CA_FILE="$bundle"
  fi
}

is_running() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

health_ok() {
  local port="$1"
  curl -fsS "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1
}

port_for_pid() {
  local pid="$1"
  local cmd
  cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  if [ -z "$cmd" ]; then
    return 1
  fi

  local parsed
  parsed="$(echo "$cmd" | sed -n 's/.*--port[[:space:]]\([0-9]\{2,5\}\).*/\1/p')"
  if [ -n "$parsed" ]; then
    echo "$parsed"
  else
    echo "8080"
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

find_existing_app_server_pid() {
  while IFS= read -r pid; do
    [ -z "$pid" ] && continue
    [ "$pid" = "$$" ] && continue
    if is_project_app_server_pid "$pid"; then
      echo "$pid"
      return 0
    fi
  done < <(pgrep -f "app_server.py" || true)
  return 1
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

load_local_env
auto_configure_minimax_ca

if [ -f "$PID_FILE" ]; then
  existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${existing_pid:-}" ] && is_running "$existing_pid"; then
    existing_port="$(cat "$PORT_FILE" 2>/dev/null || true)"
    if [ -z "${existing_port:-}" ]; then
      existing_port="$(port_for_pid "$existing_pid" || echo "$START_PORT")"
    fi
    if ! health_ok "$existing_port"; then
      maybe_port="$(port_for_pid "$existing_pid" || echo "$existing_port")"
      if [ "$maybe_port" != "$existing_port" ] && health_ok "$maybe_port"; then
        existing_port="$maybe_port"
      fi
    fi
    echo "$existing_port" > "$PORT_FILE"
    existing_url="http://127.0.0.1:${existing_port}/index.html"
    cache_bust="$(date +%s)"
    open "${existing_url}?t=${cache_bust}" >/dev/null 2>&1 || true
    echo "Fasting Tracker is already running at $existing_url (PID $existing_pid)"
    exit 0
  fi
  rm -f "$PID_FILE" "$PORT_FILE"
fi

# If an app server is running but wasn't tracked, adopt it.
if existing_pid="$(find_existing_app_server_pid)"; then
  existing_port="$(port_for_pid "$existing_pid" || echo "$START_PORT")"
  if health_ok "$existing_port"; then
    echo "$existing_pid" > "$PID_FILE"
    echo "$existing_port" > "$PORT_FILE"
    existing_url="http://127.0.0.1:${existing_port}/index.html"
    cache_bust="$(date +%s)"
    open "${existing_url}?t=${cache_bust}" >/dev/null 2>&1 || true
    echo "Fasting Tracker is already running at $existing_url (PID $existing_pid)"
    exit 0
  fi
fi

port="$(find_open_port "$START_PORT")" || {
  echo "Error: Could not find an open port between $START_PORT and 8999."
  exit 1
}

nohup python3 "$ROOT_DIR/app_server.py" --port "$port" >"$LOG_FILE" 2>&1 &
pid=$!
ready=0
for _ in {1..20}; do
  if is_running "$pid" && health_ok "$port"; then
    ready=1
    break
  fi
  sleep 0.25
done

if [ "$ready" -ne 1 ]; then
  echo "Error: Failed to start server."
  echo "Log: $LOG_FILE"
  tail -n 40 "$LOG_FILE" || true
  if is_running "$pid"; then
    kill "$pid" >/dev/null 2>&1 || true
  fi
  exit 1
fi

echo "$pid" > "$PID_FILE"
echo "$port" > "$PORT_FILE"

url="http://127.0.0.1:${port}/index.html"
cache_bust="$(date +%s)"
open "${url}?t=${cache_bust}" >/dev/null 2>&1 || true

echo "Fasting Tracker started at $url"
echo "Stop it with: $ROOT_DIR/stop-local.sh"
