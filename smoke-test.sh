#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8099}"
LOG_FILE="/tmp/fasting-smoke-${PORT}.log"

cd "$ROOT_DIR"

python3 app_server.py --port "$PORT" >"$LOG_FILE" 2>&1 &
PID=$!
cleanup() {
  kill "$PID" >/dev/null 2>&1 || true
  wait "$PID" 2>/dev/null || true
}
trap cleanup EXIT

for _ in {1..80}; do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done

curl -fsS "http://127.0.0.1:${PORT}/api/health" | jq -e '.ok == true and .storage == "sqlite"' >/dev/null

DATE_KEY="$(curl -fsS "http://127.0.0.1:${PORT}/api/data" | jq -r '.data.measurements | if length > 0 then .[-1].date else empty end')"
if [ -z "${DATE_KEY:-}" ]; then
  echo "No existing measurement date found for smoke test."
  exit 1
fi

ORIG_JSON="$(curl -fsS "http://127.0.0.1:${PORT}/api/data" | jq -c --arg d "$DATE_KEY" '.data.measurements[] | select(.date == $d) | {weight_kg, water_liters}')"
ORIG_WEIGHT="$(echo "$ORIG_JSON" | jq '.weight_kg')"
ORIG_WATER="$(echo "$ORIG_JSON" | jq '.water_liters')"

curl -fsS -X POST "http://127.0.0.1:${PORT}/api/checkin" \
  -H 'Content-Type: application/json' \
  -d "{\"date\":\"${DATE_KEY}\",\"weight_kg\":70.5,\"water_liters\":2.4}" \
  | jq -e '.ok == true and .weight_kg == 70.5 and .water_liters == 2.4' >/dev/null

curl -fsS "http://127.0.0.1:${PORT}/api/data" \
  | jq -e --arg d "$DATE_KEY" '.ok == true and (.data.measurements[] | select(.date == $d) | .weight_kg == 70.5 and .water_liters == 2.4)' >/dev/null

curl -fsS -X POST "http://127.0.0.1:${PORT}/api/checkin" \
  -H 'Content-Type: application/json' \
  -d "{\"date\":\"${DATE_KEY}\"}" \
  | jq -e '.ok == true and .weight_kg == 70.5 and .water_liters == 2.4' >/dev/null

RESTORE_PAYLOAD="$(jq -n --arg d "$DATE_KEY" --argjson w "$ORIG_WEIGHT" --argjson water "$ORIG_WATER" '{date:$d, weight_kg:$w, water_liters:$water}')"
curl -fsS -X POST "http://127.0.0.1:${PORT}/api/checkin" \
  -H 'Content-Type: application/json' \
  -d "$RESTORE_PAYLOAD" >/dev/null

curl -fsS "http://127.0.0.1:${PORT}/api/sync/status" | jq -e '.ok == true and .auto_sync.enabled != null' >/dev/null

echo "Smoke test passed on port ${PORT}."
