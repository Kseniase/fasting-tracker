# Building a Personal Health Tracker with Claude Code

I just finished a 10-day water fast, and I used Claude Code to build the entire tracking system. What started as a simple conversation turned into a full-stack health dashboard with Oura Ring integration, AI-generated infographics, meal planning, and even automated grocery shopping. Here's what I learned about using an AI coding assistant for personal projects.

## The Setup: Conversation → CLAUDE.md

Every Claude Code project has a `CLAUDE.md` file that acts as persistent memory. Instead of explaining my project from scratch each session, I iteratively built up instructions:

```markdown
# Fasting Tracker - Claude Instructions

## Project Overview
This is a 10-day water fast tracker (Jan 1-11, 2026) with Oura Ring integration.
The goal is to reduce visceral fat from 5.18 lbs to target of 1.0 lb.

## Daily Update Workflow
When the user provides their morning weight (e.g., "my weight is 90.7"):
1. Run `./track.sh` to sync Oura data
2. Update weight in data.json
3. Add daily log entry
4. Generate infographic for social media
...
```

By the end, this file was 300+ lines of structured instructions covering data formats, API patterns, infographic styles, and common tasks. Each session, Claude knew exactly how to help.

## Part 1: Oura Ring API Integration

The first real code was a bash script to pull data from my Oura Ring. Claude wrote `track.sh` - a 270-line script that:

- Fetches sleep, readiness, activity, and stress data from Oura's API
- Gets the API token from 1Password automatically (`op item get "Oura Token"`)
- Calculates day numbers relative to fast start date
- Updates a central `data.json` file with all metrics
- Adds sleep log entries with bedtime/wake times

```bash
# Fetch all data
SLEEP_SUMMARY=$(curl -s -H "Authorization: Bearer $OURA_TOKEN" \
  "https://api.ouraring.com/v2/usercollection/daily_sleep?start_date=$START_DATE&end_date=$END_DATE")

# Update data.json for each day
jq --arg day "$DAY" \
   --argjson sleep_score "${SLEEP_SCORE:-null}" \
   --argjson readiness "${READINESS_SCORE:-null}" \
   '(.measurements[] | select(.date == $day)) |= . + {
     oura: { sleep_score: $sleep_score, readiness_score: $readiness, ... }
   }' "$DATA_FILE" > "$DATA_FILE.tmp" && mv "$DATA_FILE.tmp" "$DATA_FILE"
```

Every morning I'd say "my weight is 90.7" and Claude would run the sync, update the data, and add a log entry. The 1Password integration meant no API keys in the repo.

## Part 2: Data-Driven Dashboard

With data flowing into `data.json`, Claude built a single-page dashboard in `index.html`:

- Dark theme with Chart.js visualizations
- Weight trends, Oura metrics (HRV, resting HR, sleep scores)
- Visceral fat estimation based on body scan baseline
- Day-by-day phase guide (Glycogen Depletion → Ketosis → Autophagy)
- Tabbed interface for reference infographics

The key insight: use `npx live-server` instead of `open index.html` because browsers block loading local JSON files due to CORS.

## Part 3: Research → Infographics Pipeline

I wanted reference materials about what happens during extended fasting. Claude did research and synthesized it into infographic prompts, then used the **nano-banana skill** (which wraps Google's Gemini image generation) to create them:

- `keto-mental-journey-infographic.png` - Mental experience day by day
- `metabolic-changes-infographic.png` - Cellular changes during fasting
- `fast-refeed-infographic.png` - The fast-refeed-fast cycle protocol
- `refeed-meal-plan-infographic.png` - 7-day refeed meal plan

These are reference materials that don't change - they live in the dashboard as tabs.

## Part 4: Daily Social Media Infographics

For each day of the fast, I wanted a shareable infographic with current data. Claude created a template prompt:

```
Create a 16:9 landscape infographic for Day {N} of a 10-day water fast.
Use Edward Tufte-inspired design: cream/off-white background, black text,
thin hairline rules, serif font (Times/Georgia style), NO neon colors,
NO glowing effects, NO gradients. Scientific paper figure aesthetic.

TOP STATUS BAR:
- Weight: {weight} kg ({change} overnight, {total_change} kg total)
- Sleep: {sleep_score} score / {sleep_hours} hrs
- Readiness: {readiness_score}
...
```

Each morning after updating my weight, Claude would generate `day8-update.png` with current stats. By the end I had 10 daily infographics documenting the journey.

The style guide was important - without explicit instructions like "NO neon colors, NO glowing effects," AI image generators default to a garish "tech startup" aesthetic. Specifying "Edward Tufte-inspired" and "scientific paper figure" got clean, readable results.

## Part 5: Extracting Data from Complex Sources

I had bloodwork results from Function Health, but they were locked in a complex React web app. I did "Save Page As" which created a 696KB HTML file with all the JavaScript and CSS.

Claude read through the mess and extracted the meaningful data into `bloodwork-2025-12-11.md`:

```markdown
## Areas of Concern

| Marker | Value | Status | Notes |
|--------|-------|--------|-------|
| Apolipoprotein B (ApoB) | 153 mg/dL | **Above Range** | Cardiovascular risk |
| LDL Cholesterol | 188 mg/dL | **Above Range** | |
| LDL Pattern | B | **Out of Range** | Small dense particles |
| Triglycerides | 157 mg/dL | **Above Range** | |
| Glucose (fasting) | 102 mg/dL | **Above Range** | Borderline pre-diabetic |
```

This connected my fasting goals to actual health markers - visceral fat reduction should improve these metabolic numbers.

## Part 6: Meal Planning with Multi-Appliance Orchestration

Breaking a fast requires careful refeeding. Claude helped design a 7-day meal plan, but the interesting part was the **cooking system**.

`recipes.json` contains a complete Sunday meal prep workflow:

```json
{
  "cooking": {
    "overview": {
      "total_time": "4.75 hours (12:00pm - 4:45pm)",
      "equipment": {
        "oven1": "Pork braise at 300°F",
        "oven2": "Chicken, then vegetables at 400°F",
        "stovetop": "Eggs, cauliflower mash",
        "slow_cooker_1": "Beef stew on HIGH",
        "air_fryer": "Bacon"
      }
    },
    "steps": [
      {
        "step": 1,
        "time": "12:00",
        "title": "START - Big Proteins Go In",
        "do": [
          "Preheat OVEN #1 to 300°F",
          "PORK: Pat dry, rub with spices, into dutch oven...",
          "BEEF STEW: Cut chuck into cubes, into SLOW COOKER #1..."
        ],
        "status_after": "Pork braising, Beef in slow cooker, Chicken prepped"
      }
    ]
  }
}
```

This is time-boxed cooking - every 15-30 minutes there's a step, and it tells you exactly which appliance to use. The result: 5 proteins and all sides prepped in under 5 hours.

## Part 7: Browser Automation with Session Isolation

The most interesting technical discovery: using Chrome DevTools Protocol for **grocery shopping automation** while keeping the AI agent sandboxed.

The chrome-driver plugin lets Claude control a browser, but here's the key security pattern:

```bash
# Each service gets its own cookie universe
--user-data=/Users/wschenk/.chrome-instacart
```

This means:
- Claude can log into Instacart and manage my cart
- But it has NO access to my main Chrome profile (banking, email, etc.)
- The session persists between runs (stays logged in)
- I can watch what it's doing (`--no-headless`)

Claude learned the Instacart DOM patterns through trial and error:

```bash
# 3-step search pattern (clear → type → submit)
$INTERACT --eval="var input = document.querySelector('#search-bar-input');
  input.select(); document.execCommand('delete'); 'cleared'"
$INTERACT --type="#search-bar-input=avocados"
$INTERACT --eval="document.querySelector('#search-bar-input').closest('form')
  .dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))"

# Add product using aria-label pattern
$INTERACT --eval="var btn = document.querySelector(
  'button[aria-label*=\"Add\"][aria-label*=\"Avocado\"]');
  if(btn) btn.click();"
```

Key discoveries:
- Instacart uses aria-labels like `Add 1 ct [Product Name]` and `Increment quantity of [Product Name]`
- Always clear the search input before typing (otherwise terms concatenate)
- Use `dispatchEvent` for form submission in SPAs, not `.submit()`
- Add `2>/dev/null` to suppress Chrome driver noise
- Sleep 3 seconds after search for results to load

I built two carts at different stores (Market 32: $317, Stop & Shop: $361) and discovered the same olive oil was $46 at one store vs $10 at another. Claude swapped it out.

**All these patterns got documented back into the chrome-driver plugin's SKILL.md** so future sessions benefit from the learnings.

## The Meta-Pattern: Self-Documenting Workflows

The most powerful pattern isn't any single feature - it's that **every discovery gets documented back into the system**.

- Learned how to sync Oura data? It goes in CLAUDE.md
- Figured out Instacart's DOM patterns? They go in the chrome-driver SKILL.md
- Found a good infographic style? The prompt template gets saved

Future sessions don't start from scratch. The project teaches Claude how to work on it.

## What I'd Do Differently

1. **Start with CLAUDE.md earlier** - I added instructions reactively. Starting with a skeleton would have saved time.

2. **Version the data.json schema** - Adding fields mid-project required careful migration.

3. **Separate concerns in HTML** - The dashboard grew organically. A component framework would help.

4. **Document the "why" not just "how"** - CLAUDE.md has great instructions but light on rationale.

## The Stack

| Component | Technology |
|-----------|------------|
| Data sync | Bash + curl + jq |
| API secrets | 1Password CLI |
| Data storage | JSON file |
| Dashboard | Static HTML + Chart.js |
| Image generation | nano-banana + Gemini API |
| Browser automation | Chrome DevTools Protocol |
| Session isolation | `--user-data=PATH` per service |

## Conclusion

Claude Code isn't just for writing code - it's for building systems that evolve with you. The combination of persistent instructions (CLAUDE.md), tool access (bash, browser, image generation), and conversational iteration means you can build surprisingly sophisticated personal tools.

The fasting tracker started as "help me track my weight" and ended up with API integrations, data visualization, AI-generated infographics, meal planning, and automated grocery shopping. Each piece built on the last, with Claude remembering context and patterns across sessions.

The real unlock is **session isolation for browser automation**. Giving an AI agent access to a browser sounds dangerous, but with separate cookie universes per service, you get the automation benefits without the security risks. Claude can shop for groceries without seeing your email.

Ten days of fasting, ten days of building. Both transformative in their own way.

---

*All code and data available at [repo link]. Generated with Claude Code.*
