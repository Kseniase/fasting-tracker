# Fasting Tracker - Claude Instructions

## Project Overview

This is a 10-day water fast tracker (Jan 1-11, 2026) with Oura Ring integration. The goal is to reduce visceral fat from 5.18 lbs to target of 1.0 lb through fasting cycles.

## Daily Update Workflow

When the user provides their morning weight (e.g., "my weight is 90.7"):

### Step 1: Sync Oura Data
```bash
./track.sh
```
This script:
- Fetches sleep, readiness, activity, and stress data from Oura API
- Updates `data.json` with all Oura metrics
- Adds sleep log entries (bedtime/wake times)
- Token is stored in `.oura_token` (refreshed from 1Password "Oura Token" if needed)

### Step 2: Update Weight in data.json

Find the current day's measurement entry and update:
- `weight_kg`: The provided weight
- `weight_change_kg`: Calculate from previous day's weight

Example: If today is Jan 9 (Day 8) and weight is 90.7, and yesterday was 92.1:
```json
{
  "date": "2026-01-09",
  "day": 8,
  "weight_kg": 90.7,
  "weight_change_kg": -1.4,
  ...
}
```

### Step 3: Add Daily Log Entry

Add an observation entry to the `log` array with key metrics:
```json
{
  "date": "2026-01-09",
  "day": 8,
  "type": "observation",
  "message": "Weight: 90.7 kg (-1.4 kg overnight, -7.6 kg total). Day 8 Deep Autophagy - sleep score 81, readiness 83, lowest HR 58 bpm."
}
```

Include:
- Weight and change (overnight and total from start)
- Current phase from day_guide
- Notable Oura metrics (sleep score, readiness, HRV, lowest HR)
- Any significant changes or patterns

### Step 4: Generate Daily Social Media Infographic

Generate a Tufte-style 16:9 infographic with current data for social sharing. See "Infographics" section below for style guide and content requirements. Save as `day{N}-update.png`.

### Step 5: Start Live Server (if not already running)

**IMPORTANT: Do NOT use `open index.html` - it won't load data.json due to CORS.**

Use live-server instead:
```bash
npx live-server
```

This will auto-open the browser and pick an available port. Don't specify port or use --no-browser flags.

## File Structure

```
fasting-tracker/
├── index.html          # Dashboard (single-page app)
├── data.json           # All tracking data
├── track.sh            # Oura sync script
├── .oura_token         # Oura API token (gitignored)
├── CLAUDE.md           # This file
└── *.png               # Infographics
    ├── keto-mental-journey-infographic.png
    ├── metabolic-changes-infographic.png
    ├── fast-refeed-infographic.png
    └── refeed-meal-plan-infographic.png
```

## data.json Structure

```json
{
  "fast": {
    "start": "2026-01-01T18:00:00",
    "goal_days": 10,
    "end": "2026-01-11T18:00:00"
  },
  "baseline": { ... },           // Pre-fast averages for comparison
  "body_composition": [ ... ],   // Body scan results (Jan 3 baseline, Jan 11 final)
  "measurements": [ ... ],       // Daily entries with weight + Oura data
  "log": [ ... ],                // Activity log entries
  "day_guide": { ... }           // Day 1-10 phase guides
}
```

## Key Metrics to Track

### From Oura (auto-synced):
- Sleep score, readiness score, activity score
- Steps, total calories, active calories
- HRV balance, body temp deviation
- Sleep details: bedtime, wake time, deep/REM/light mins, efficiency, lowest HR, avg HRV
- Stress: summary, stress mins, recovery mins

### Manual Entry:
- Weight (kg) - user provides each morning
- Notes - any observations, symptoms, or events

## Day Guide Reference

| Day | Phase | Key Events |
|-----|-------|------------|
| 1 | Glycogen Depletion | Hunger peaks, water weight drops |
| 2 | Transition | Brain fog, ketosis starting |
| 3 | Early Ketosis | Mental clarity improving, autophagy begins |
| 4 | Ketosis Established | Hunger gone, steady energy |
| 5 | Deep Ketosis | Halfway, peak clarity |
| 6 | Autophagy Active | Cellular cleanup, stable |
| 7 | Fat Adapted | Running smoothly on ketones |
| 8 | Deep Autophagy | Maximum cellular repair |
| 9 | Final Stretch | Plan refeed |
| 10 | Completion | Body scan, break fast with bone broth |

## Visceral Fat Estimation

Based on data patterns:
- Visceral fat burns 2-3x faster than subcutaneous during fasting
- Estimate ~40-50% of true fat loss comes from visceral stores
- Starting: 5.18 lbs (Jan 3 scan)
- Formula: `current_estimate = 5.18 - (total_fat_lost * 0.45)`

To estimate current visceral fat:
1. Calculate total weight lost since scan
2. Subtract water weight (~2-3 kg in first 2 days)
3. Remaining is mix of fat + small lean mass
4. ~40-50% of fat loss is visceral

## Infographics

There are TWO types of infographics:

### 1. Static Dashboard Infographics (in index.html)

These are reference guides that DON'T change daily. They're displayed in the dashboard with tabs:
- `keto-mental-journey-infographic.png` - Mental experience day by day
- `metabolic-changes-infographic.png` - What's happening metabolically
- `fast-refeed-infographic.png` - The fast-refeed-fast cycle protocol
- `refeed-meal-plan-infographic.png` - 7-day refeed meal plan

**Only regenerate these if the content/design needs updating, not daily.**

### 2. Daily Social Media Updates (shareable)

These are generated DAILY with current data for posting on social media. Use 16:9 landscape format and Tufte-inspired minimalist style.

**Style Guide (from infographic-prompt.txt):**
- Edward Tufte-inspired: clean, elegant, high data-ink ratio
- Cream/off-white background (NOT dark theme)
- Black text, subtle gray accents
- Thin hairline rules and axes
- Serif font (Times/Georgia style)
- No neon colors, no glowing effects, no gradients
- Scientific paper figure aesthetic
- Let the data speak, minimal chrome

**Daily update layout:**
- TOP: Current Status (prominent) - Phase, Weight (with total change), Sleep score/hours/deep, Readiness, Lowest HR, days remaining
- MIDDLE LEFT: Weight chart (thin black line with dots, all days)
- MIDDLE RIGHT: Oura sparklines (Resting HR, Sleep Score, Readiness)
- BOTTOM: Three sections explaining:
  - METABOLICALLY: What's happening at cellular level (from day_guide.metabolic)
  - PHYSICALLY: How the body feels, what biometrics show
  - WHAT TO EXPECT: Mental state, energy levels, tips for the day

**Output:** Save as `day{N}-update.png` (e.g., `day8-update.png`)

### Generating Infographics

Uses nano-banana skill with Google AI Studio key:
```bash
# Get key from 1Password
op item get "Google AI Studio Key" --format json | jq -r '.fields[].value' | grep -E '^AIza' | head -1

# Generate infographic
GEMINI_API_KEY="<key>" npx @the-focus-ai/nano-banana "prompt..." --output filename.png
```

## Refeed Protocol (Post-Fast)

After Day 10:
1. Days 1-2: Bone broth, soft eggs (500-800 cal)
2. Days 3-5: Protein focus, 120-130g/day (1200-1500 cal)
3. Days 6-10: Carb reintroduction (1800-2200 cal)
4. Week 2+: Normalize to maintenance

See infographics for detailed meal plans.

## Common Tasks

### "Update my weight"
1. Run `./track.sh`
2. Edit data.json with weight
3. Add log entry
4. Start live-server if not running

### "What's my estimated visceral fat?"
Calculate based on weight loss and body scan baseline.

### "Add a log entry"
Add to the `log` array with date, day number, type (event/observation/sleep), and message.

### "Create an infographic"
Use nano-banana skill with detailed prompt describing content and style.

### "Show the dashboard"
```bash
npx live-server
```
This will open the browser automatically. If already running, just refresh the page.
