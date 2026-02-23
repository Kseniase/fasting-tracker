# Fasting Tracker

Static local dashboard and planning app for fasting/refeed tracking.

## Quick start (macOS)

```bash
cd /Users/kseniase/Desktop/Fasting
./run-local.sh
```

This starts a local web server and opens:

- `http://127.0.0.1:8080/index.html` (or next open port if 8080 is busy)

Stop the server:

```bash
cd /Users/kseniase/Desktop/Fasting
./stop-local.sh
```

You can also double-click `start.command`.

## Repo structure

- `index.html` - Main fasting tracker dashboard
- `refeed.html` - Refeed planner
- `fasting-info.html` - Research/education page
- `meal-plans/` - Meal prep and menu tools
- `data.json` - Daily measurement data
- `track.sh` - Pull Oura data into `data.json`

## Oura sync (`track.sh`)

First-time setup (no 1Password required):

```bash
cd /Users/kseniase/Desktop/Fasting
./setup-oura-token.sh
```

Then sync:

```bash
cd /Users/kseniase/Desktop/Fasting
./track.sh
```

Dependencies:

- `curl`
- `jq`
- `bc`
- `op` (optional, only if you prefer loading token from 1Password)

Examples:

```bash
# Use token from environment (one-off)
OURA_TOKEN=your_token_here ./track.sh

# Refresh token from 1Password item "Oura Token" (optional flow)
./track.sh --refresh-token

# Fetch a specific date range
./track.sh 2026-01-01 2026-01-03
```
