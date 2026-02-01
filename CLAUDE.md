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
- TOP: Current Status (prominent) - Phase, Weight (with total change), Sleep score/hours/deep, Readiness, Lowest HR, Progress (Day X/Y)
- MIDDLE LEFT: Weight chart (main, larger) - thin black line with dots, all days
- MIDDLE RIGHT: Three sparklines stacked:
  - Calories Burned (total_calories from each day)
  - Sleep Hours (total_hours from each day)
  - Sleep Score (sleep_score from each day)
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
GEMINI_API_KEY="<key>" npx @the-focus-ai/nano-banana@latest "prompt..." --output filename.png
```

**Daily Infographic Prompt Template:**
```
Create a 16:9 landscape infographic for Day {N} of an {TOTAL}-day water fast. Use Edward Tufte-inspired design: cream/off-white background, black text, thin hairline rules, serif font (Times/Georgia style), NO neon colors, NO glowing effects, NO gradients. Scientific paper figure aesthetic.

HEADER: 'DAY {N}: {PHASE}' in elegant serif, with '{TOTAL}-Day Water Fast Tracker' subtitle

TOP STATUS BAR (prominent):
- Phase: {phase from day_guide}
- Weight: {weight} kg ({change} overnight, {total_change} kg total)
- Sleep: {sleep_score} score / {sleep_hours} hrs / {deep_mins} min deep
- Readiness: {readiness_score}
- Lowest HR: {lowest_hr} bpm
- Progress: Day {N}/{TOTAL}

MIDDLE LEFT - Weight Chart (main, larger):
Thin black line with small dots showing daily weights:
{list all weights by day}
Y-axis from {min-2} to {max+2} kg. Label: 'Weight (kg)'

MIDDLE RIGHT - Three sparklines stacked:
1. Calories Burned: {list total_calories for each day} (label: Calories Burned)
2. Sleep Hours: {list sleep hours for each day} (label: Sleep Hours)
3. Sleep Score: {list sleep scores for each day} (label: Sleep Score)

BOTTOM - Three columns with thin dividing lines:

METABOLICALLY:
{content from day_guide.metabolic, summarized}

PHYSICALLY:
{current physical state based on biometrics}

WHAT TO EXPECT:
{guidance for the day from day_guide}

FOOTER: Small text 'Generated {date} • Oura Ring Data • @wschenk'
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

### "Order groceries" or "Add to Instacart"

Automate Instacart shopping using the chrome-driver plugin. Shopping list is in `recipes.json`.

**Setup:**
```bash
INTERACT="/Users/wschenk/.claude/plugins/cache/focus-marketplace/chrome-driver/0.1.0/bin/interact --no-headless --user-data=~/.chrome-instacart"
NAVIGATE="/Users/wschenk/.claude/plugins/cache/focus-marketplace/chrome-driver/0.1.0/bin/navigate --no-headless --user-data=~/.chrome-instacart"
```

**Store URLs:**
- Stop & Shop: `https://www.instacart.com/store/stop-shop/storefront`
- Market 32: `https://www.instacart.com/store/market-32/storefront`

#### Step 1: Get Current Cart Contents (IMPORTANT - do this first!)

To compare with shopping list, you need to see what's already in the cart:

```bash
# 1. Navigate to store
$NAVIGATE "https://www.instacart.com/store/stop-shop/storefront" 2>/dev/null

# 2. Click the cart button to open cart drawer (find button with item count in header)
$INTERACT --eval="
var cartBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.match(/\\d+/) && b.getBoundingClientRect().top < 80 && b.getBoundingClientRect().right > 700);
if (cartBtn) {
  cartBtn.dispatchEvent(new MouseEvent('click', {view: window, bubbles: true, cancelable: true}));
  'clicked cart';
} else { 'cart button not found'; }
" 2>/dev/null && sleep 2

# 3. Extract cart contents from the dialog
$INTERACT --eval="
var dialogs = Array.from(document.querySelectorAll('[role=\"dialog\"]'));
var cartDialog = dialogs.find(d => d.innerText.includes('Stop & Shop') && d.innerText.includes('\\$'));
if (cartDialog) {
  cartDialog.innerText;
} else {
  'Cart dialog not found - may need to click cart again';
}
" 2>/dev/null
```

The cart dialog shows:
- Item names with quantities (e.g., "Quantity: 9.5 lbs")
- Prices
- Total at bottom
- "Likely out of Stock" warnings

#### Step 2: Compare Cart with Shopping List

Read `recipes.json` to get the shopping list, then compare with cart contents.
Create a table showing: Item | Needed | In Cart | Action

#### Step 3: Add/Adjust Items

**Search for item (one command at a time for reliability):**
```bash
# Clear search
$INTERACT --eval="var input = document.querySelector('#search-bar-input'); if(input) { input.select(); document.execCommand('delete'); }" 2>/dev/null

# Type search term
$INTERACT --type="#search-bar-input=avocado" 2>/dev/null

# Submit search
$INTERACT --eval="document.querySelector('#search-bar-input').closest('form').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))" 2>/dev/null && sleep 3
```

**Add item to cart:**
```bash
# Add item (use partial match on aria-label)
$INTERACT --eval="
var btn = document.querySelector('button[aria-label*=\"Add\"][aria-label*=\"Avocado\"]');
if (btn) { btn.click(); 'Added'; } else { 'not found'; }
" 2>/dev/null
```

**Increment quantity:**
```bash
# Increment (click multiple times for multiple items)
$INTERACT --eval="
var btn = document.querySelector('button[aria-label*=\"Increment\"][aria-label*=\"Avocado\"]');
if (btn) { btn.click(); 'Incremented'; } else { 'not found'; }
" 2>/dev/null
```

**Check what's available after search:**
```bash
$INTERACT --eval="
var btns = Array.from(document.querySelectorAll('button[aria-label*=\"Add\"], button[aria-label*=\"Increment\"]'));
JSON.stringify(btns.map(b => b.getAttribute('aria-label')).slice(0, 15));
" 2>/dev/null
```

#### Aria-Label Patterns

| Action | Pattern | Example |
|--------|---------|---------|
| Add | `Add 1 ct [Product]` or `Add 1 lb [Product]` | `Add 1 ct Hass Avocado` |
| Increment | `Increment quantity of [Product]` | `Increment quantity of Hass Avocado` |
| Decrement | `Decrement quantity of [Product]` | `Decrement quantity of Hass Avocado` |
| Remove | `Remove [Product]` | `Remove Hass Avocado` |

#### Tips

1. **Run commands one at a time** - chaining with `&&` can cause permission issues
2. **Always clear search** before typing new term (prevents concatenation)
3. **Use partial matches** in aria-labels (e.g., `aria-label*=\"vocado\"`)
4. **Wait after search** - sleep 3 seconds for results to load
5. **Suppress noise** with `2>/dev/null`
6. **Items in cart show Increment** button, not Add button
7. **Weight-based items** (meat, produce) may not have increment buttons in search results
8. **Get cart count** from page: look for number in header near "delivery fee"

#### Quick Cart Check

```bash
# Get cart item count
$INTERACT --eval="
var text = document.body.innerText;
var match = text.match(/delivery fee\\s*(\\d+)/);
match ? 'Cart: ' + match[1] + ' items' : 'Could not find count';
" 2>/dev/null
```

### "Generate meal plan PDFs" or "Print meal calendars"

Generate one-page landscape PDF calendars with weekly meal plans and prep instructions.

**Files:**
- `meal-plan-her-calendar.html` / `.pdf` - Her plan (4 meals/day: breakfast, 2nd breakfast, meal 1, meal 2)
- `meal-plan-him-calendar.html` / `.pdf` - His plan (3 meals/day: meal 1, meal 2, snack)
- `meal-plan-her.md` / `meal-plan-him.md` - Markdown versions for email

**To regenerate PDFs:**
```bash
/Users/wschenk/.claude/plugins/cache/focus-marketplace/chrome-driver/0.1.0/bin/pdf "file:///Users/wschenk/The-Focus-AI/fasting-tracker/meal-plan-her-calendar.html" "/Users/wschenk/The-Focus-AI/fasting-tracker/meal-plan-her-calendar.pdf" --landscape

/Users/wschenk/.claude/plugins/cache/focus-marketplace/chrome-driver/0.1.0/bin/pdf "file:///Users/wschenk/The-Focus-AI/fasting-tracker/meal-plan-him-calendar.html" "/Users/wschenk/The-Focus-AI/fasting-tracker/meal-plan-him-calendar.pdf" --landscape
```

**To email meal plans:**
```bash
# Send markdown versions as styled emails
npx tsx /Users/wschenk/.claude/plugins/cache/focus-marketplace/google-skill/0.8.0/scripts/gmail.ts send-md --to="email@example.com" --file="meal-plan-him.md" --style=client

npx tsx /Users/wschenk/.claude/plugins/cache/focus-marketplace/google-skill/0.8.0/scripts/gmail.ts send-md --to="email@example.com" --file="meal-plan-her.md" --style=client
```

**2x Portion System:**

Rule: **Him = 2× Her** for all proteins and vegetables.

| Protein | Her (1x) | Him (2x) |
|---------|----------|----------|
| Chicken | 175g | 350g |
| Pulled Pork | 125g | 250g |
| Beef Stew | 300g | 600g |
| Salmon | 125g | 250g |
| Steak | 150g | 300g |

| Veggie | Her (1x) | Him (2x) |
|--------|----------|----------|
| Roasted | 100g | 200g |
| Mash | 100g | 200g |
| Slaw | 75g | 150g |
| Greens | 75g | 150g |
| Avocado | 50g | 100g |

**Her daily structure:**
- 7am: 3 eggs + veggies (21g protein)
- 10am: 150g yogurt + berries (15g protein)
- 12pm: Meal 1 - 1x portion (~32g protein)
- 3pm: 200g cottage cheese (24g protein)
- 6pm: Meal 2 - 1x portion (~32g protein)
- **Total: ~124g protein, ~1400 cal**

**His daily structure:**
- 12pm: Meal 1 - 2x portion (~65g protein)
- 3pm: Snack (~15g protein)
- 6pm: Meal 2 - 2x portion (~65g protein)
- Snack: Deviled eggs (~14g protein)
- **Total: ~150g protein, ~1900 cal**

**Container Labels:** Pink lid = 1x (Her), Blue lid = 2x (Him)
