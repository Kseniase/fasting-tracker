# Fasting Tracker

Local fasting/refeed dashboard with API backend, SQLite persistence, Oura sync, and MiniMax chat memory.

## Quick start (macOS)

```bash
cd /Users/kseniase/Desktop/Fasting
./run-local.sh
```

Open:

- `http://127.0.0.1:8080/index.html` (or next open port)

Stop:

```bash
cd /Users/kseniase/Desktop/Fasting
./stop-local.sh
```

## Reliability model

- Single writer: `app_server.py` handles all check-ins and Oura updates.
- Primary storage: `fasting.db` (SQLite, WAL mode).
- Compatibility cache: `data.json` is generated from DB for static page fallback.
- Audit trail: `checkin_history.jsonl` (append-only check-in events).
- Backups: daily DB snapshot under `backups/`.

## Oura sync

Trigger manual sync through API wrapper script:

```bash
cd /Users/kseniase/Desktop/Fasting
./track.sh
```

Optional date range:

```bash
./track.sh 2026-02-23 2026-02-24
```

Token sources (in order):

1. `--token <...>`
2. `OURA_TOKEN` env var
3. `.oura_token` file
4. `--refresh-token` via 1Password CLI (optional)

Background auto-sync runs every 2 hours by default.

Environment toggles:

- `OURA_AUTO_SYNC=0` disables automatic sync
- `OURA_AUTO_SYNC_INTERVAL_SECONDS=7200` changes interval

## MiniMax chat

Set key in env or token file:

```bash
export MINIMAX_API_KEY="your_key"
# or
printf '%s\n' "your_key" > .minimax_token
chmod 600 .minimax_token
```

Optional overrides:

- `MINIMAX_MODEL` (default: `MiniMax-M2.5`)
- `MINIMAX_BASE_URL` (default: `https://api.minimax.io/v1`)
- `MINIMAX_CA_FILE`
- `MINIMAX_INSECURE_SKIP_VERIFY=1` (troubleshooting only)

## Smoke test

```bash
cd /Users/kseniase/Desktop/Fasting
./smoke-test.sh
```

This validates API health, check-in persistence, non-destructive partial update semantics, clear behavior, and sync-status endpoint.
