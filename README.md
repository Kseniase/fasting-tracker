# Fasting Tracker

10-day fast: Jan 1-11, 2026

## Files

- `data.json` - Daily measurements (weight, Oura scores)
- `track.sh` - Fetch latest Oura data

## Usage

```bash
# Fetch last 7 days of Oura data
./track.sh

# Fetch specific date range
./track.sh 2026-01-01 2026-01-03
```

Requires 1Password CLI with "Oura Token" item.
