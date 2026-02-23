#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOKEN_FILE="$SCRIPT_DIR/.oura_token"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: Required command '$1' is not installed."
    exit 1
  fi
}

usage() {
  cat <<'EOF'
Usage:
  ./setup-oura-token.sh
  ./setup-oura-token.sh --token <oura_token>

This script validates your Oura Personal Access Token and saves it to:
  ./.oura_token
EOF
}

require_cmd curl
require_cmd jq

token_arg=""

while [ "$#" -gt 0 ]; do
  case "$1" in
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
      echo "Error: Unknown argument '$1'."
      usage
      exit 1
      ;;
  esac
done

if [ -n "$token_arg" ]; then
  token="$token_arg"
else
  cat <<'EOF'
Generate an Oura Personal Access Token, then paste it below.
If needed, open:
  https://cloud.ouraring.com/personal-access-tokens
EOF
  printf "Oura token: "
  IFS= read -r -s token
  printf "\n"
fi

token="$(printf '%s' "$token" | tr -d '\r\n')"

if [ -z "$token" ]; then
  echo "Error: Token is empty."
  exit 1
fi

tmp="$(mktemp)"
http_code=$(curl -sS -o "$tmp" -w "%{http_code}" \
  -H "Authorization: Bearer $token" \
  "https://api.ouraring.com/v2/usercollection/personal_info")

if [ "$http_code" != "200" ]; then
  message="$(jq -r '.message // empty' "$tmp" 2>/dev/null || true)"
  rm -f "$tmp"
  echo "Error: Token validation failed (HTTP $http_code)."
  if [ -n "$message" ]; then
    echo "Oura API message: $message"
  fi
  exit 1
fi

rm -f "$tmp"

printf '%s\n' "$token" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE" 2>/dev/null || true

echo "Oura token saved to $TOKEN_FILE"
echo "Next step: run ./track.sh"
