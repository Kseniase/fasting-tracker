# Instacart Shopping Automation

Add items from recipes.json to Instacart carts using browser automation.

## Prerequisites

1. Chrome browser installed
2. chrome-driver plugin enabled
3. Logged into Instacart (session saved in `~/.chrome-instacart`)

## Setup

```bash
INTERACT="/Users/wschenk/.claude/plugins/cache/focus-marketplace/chrome-driver/0.1.0/bin/interact --no-headless --user-data=~/.chrome-instacart"
NAVIGATE="/Users/wschenk/.claude/plugins/cache/focus-marketplace/chrome-driver/0.1.0/bin/navigate --no-headless --user-data=~/.chrome-instacart"
```

## Store URLs

- Stop & Shop: `https://www.instacart.com/store/stop-shop/storefront`
- Market 32: `https://www.instacart.com/store/market-32/storefront`

## Workflow Overview

1. **Get current cart contents** - See what's already in the cart
2. **Read shopping list** - Load `recipes.json` shopping list
3. **Compare** - Create table of needed vs. in-cart items
4. **Add/adjust items** - Search and add missing items

---

## Step 1: Get Current Cart Contents (DO THIS FIRST)

### Navigate to store
```bash
$NAVIGATE "https://www.instacart.com/store/stop-shop/storefront" 2>/dev/null
```

Wait 3 seconds for page to load.

### Click cart button in header
```bash
$INTERACT --eval="
var btns = Array.from(document.querySelectorAll('button'));
var cartBtn = btns.find(b => {
  var rect = b.getBoundingClientRect();
  return rect.top < 100 && rect.right > window.innerWidth - 200 && b.innerText.match(/\\d+/);
});
if (cartBtn) {
  cartBtn.click();
  'Clicked cart: ' + cartBtn.innerText.replace(/\\n/g, ' ');
} else { 'Cart button not found'; }
" 2>/dev/null
```

Wait 2 seconds for drawer to open.

### Extract full cart contents (RELIABLE METHOD)

This finds the fixed/absolute positioned drawer panel and extracts all items:

```bash
$INTERACT --eval="
var divs = Array.from(document.querySelectorAll('div'));
var drawer = divs.find(el => {
  var style = window.getComputedStyle(el);
  var rect = el.getBoundingClientRect();
  return (style.position === 'fixed' || style.position === 'absolute') &&
         rect.right >= window.innerWidth - 50 &&
         rect.width > 300 && rect.width < 600 &&
         rect.height > 400 &&
         el.innerText.includes('\\$');
});
if (drawer) {
  drawer.innerText.substring(0, 8000);
} else {
  'Drawer not found - try clicking cart again';
}
" 2>/dev/null
```

### Cart content format

The drawer shows items in this format:
```
Personal Stop & Shop Cart
Shopping in 06754
Stop & Shop
Delivery by 9:39-11:09am
$518.22

Primal Kitchen Avocado Oil Mayo (12 oz)
$12.99
Choose replacement
Quantity:
1 ct

USDA Choice USDA Bone-In Pork Picnic Shoulder Roast Fresh (1 each)
$22.70
Choose replacement
Quantity:
9.5 lbs
```

Parse this to extract: item name, price, quantity.

### Quick cart count check (from header button)
```bash
$INTERACT --eval="
var btns = Array.from(document.querySelectorAll('button'));
var cartBtn = btns.find(b => {
  var rect = b.getBoundingClientRect();
  return rect.top < 100 && rect.right > window.innerWidth - 200 && b.innerText.match(/\\d+/);
});
cartBtn ? 'Cart: ' + cartBtn.innerText.match(/\\d+/)[0] + ' items' : 'Not found';
" 2>/dev/null
```

---

## Step 2: Compare with Shopping List

Read `recipes.json` and compare `shopping` section with cart contents.

Create a comparison table:
| Item | Needed | In Cart | Action |
|------|--------|---------|--------|
| Pork shoulder (7-8 lbs) | 7-8 lbs | 9.5 lbs | OK |
| Eggs (4 dozen) | 48 | 30 | Add 18 more |
| Avocados (10) | 10 | 6 | Add 4 more |

---

## Step 3: Add/Adjust Items

**IMPORTANT: Run each command separately, not chained with &&**

### Clear search
```bash
$INTERACT --eval="var input = document.querySelector('#search-bar-input'); if(input) { input.select(); document.execCommand('delete'); }" 2>/dev/null
```

### Type search term
```bash
$INTERACT --type="#search-bar-input=avocado" 2>/dev/null
```

### Submit search
```bash
$INTERACT --eval="document.querySelector('#search-bar-input').closest('form').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))" 2>/dev/null
```

Wait 3 seconds for results.

### Check available products
```bash
$INTERACT --eval="
var btns = Array.from(document.querySelectorAll('button[aria-label*=\"Add\"], button[aria-label*=\"Increment\"]'));
JSON.stringify(btns.map(b => b.getAttribute('aria-label')).slice(0, 15));
" 2>/dev/null
```

### Add item
```bash
$INTERACT --eval="
var btn = document.querySelector('button[aria-label*=\"Add\"][aria-label*=\"Avocado\"]');
if (btn) { btn.click(); 'Added'; } else { 'not found'; }
" 2>/dev/null
```

### Increment quantity
```bash
$INTERACT --eval="
var btn = document.querySelector('button[aria-label*=\"Increment\"][aria-label*=\"Avocado\"]');
if (btn) { btn.click(); 'Incremented'; } else { 'not found'; }
" 2>/dev/null
```

For multiple increments, run the increment command multiple times.

---

## Aria-Label Patterns

| Action | Pattern | Example |
|--------|---------|---------|
| Add | `Add 1 ct [Product]` | `Add 1 ct Hass Avocado` |
| Add by weight | `Add 1 lb [Product]` | `Add 1 lb Beef Chuck Roast` |
| Increment | `Increment quantity of [Product]` | `Increment quantity of Hass Avocado` |
| Decrement | `Decrement quantity of [Product]` | `Decrement quantity of Hass Avocado` |
| Remove | `Remove [Product]` | `Remove Hass Avocado` |

**Use partial matches** with `aria-label*=` for flexibility:
- `aria-label*="vocado"` matches any avocado product
- `aria-label*="Increment"][aria-label*="vocado"` for increment buttons

---

## Shopping List Source

From `recipes.json` shopping section:

**Proteins:**
- Pork shoulder (7-8 lbs)
- Beef chuck roast (4 lbs)
- Chicken thighs, bone-in (5-6 lbs)
- Eggs (4 dozen)
- Bacon (1.5 lbs)
- Salmon fillet (1.5 lbs)
- Steak, ribeye or strip (1.5 lbs)

**Vegetables:**
- Broccoli (3 heads)
- Brussels sprouts (3 lbs)
- Cauliflower (3 heads)
- Zucchini (6-8)
- Bell peppers (8)
- Spinach (3 bags)
- Mixed greens (3 containers)
- Celery (2 bunches)
- Mushrooms (12 oz)
- Radishes (1.5 lbs)
- Green cabbage (1 head)

**Fresh:**
- Avocados (10)
- Cherry tomatoes (3 pints)
- Cucumber (5)
- Berries (3 pints)
- Lemons (6)
- Fresh thyme, rosemary, dill

**Dairy:**
- Butter (1.5 lbs)
- Cheese variety (1 lb)
- Feta (12 oz)
- Heavy cream (1 quart)
- Greek yogurt (48 oz)
- Olives (2 jars)

**Pantry:**
- Beef broth (64 oz)
- Tomato paste, Worcestershire, bay leaves
- Dijon mustard, red wine vinegar, mayo
- Spices: paprika, garlic powder, cumin, Italian herbs
- Capers, pickles, hot sauce
- Everything bagel seasoning, ranch dressing
- Almonds/mixed nuts

---

## Tips

1. **Run commands one at a time** - Avoid chaining with `&&` to prevent permission issues
2. **Always clear search first** - Prevents search term concatenation
3. **Use partial matches** - `aria-label*="vocado"` is more reliable than exact match
4. **Wait after search** - 3 seconds for results to load
5. **Suppress noise** - Add `2>/dev/null` to commands
6. **Items in cart** - Show Increment button, not Add button
7. **Weight-based items** - May not have increment buttons in search (adjust in cart drawer)
8. **Check cart drawer** - Most reliable way to see quantities

---

## Troubleshooting

**Search concatenates text:**
```bash
$INTERACT --eval="var input = document.querySelector('#search-bar-input'); input.select(); document.execCommand('delete');" 2>/dev/null
```

**Button not found:**
List available buttons first to see exact aria-label text.

**Cart dialog not opening:**
Click the cart button again - sometimes needs two clicks.

**Session expired:**
Browser will show login page. Log in manually (session saves to `~/.chrome-instacart`).

**Store unavailable:**
Check delivery address. Try different store.
