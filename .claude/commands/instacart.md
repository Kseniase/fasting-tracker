# Instacart Shopping Automation

Add items from recipes.json to Instacart carts using browser automation.

## Prerequisites

1. Chrome browser installed
2. chrome-driver plugin enabled
3. Logged into Instacart (session saved in `~/.chrome-instacart`)

## Quick Start

```bash
# Set up command shortcuts
INTERACT="/Users/wschenk/.claude/plugins/cache/focus-marketplace/chrome-driver/0.1.0/bin/interact --no-headless --user-data=~/.chrome-instacart"
NAVIGATE="/Users/wschenk/.claude/plugins/cache/focus-marketplace/chrome-driver/0.1.0/bin/navigate --no-headless --user-data=~/.chrome-instacart"
```

## Store URLs (verified working)

- Market 32: `https://www.instacart.com/store/market-32/storefront`
- Stop & Shop: `https://www.instacart.com/store/stop-shop/storefront`

## Core Workflow

### 1. Navigate to Store
```bash
$NAVIGATE "https://www.instacart.com/store/stop-shop/storefront"
```

### 2. Search for Product (3-step pattern)
```bash
# Clear previous search
$INTERACT --eval="var input = document.querySelector('#search-bar-input'); input.select(); document.execCommand('delete'); 'cleared'" 2>/dev/null

# Type search term
$INTERACT --type="#search-bar-input=pork shoulder" 2>/dev/null

# Submit search
$INTERACT --eval="document.querySelector('#search-bar-input').closest('form').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true})); 'submitted'" 2>/dev/null && sleep 3
```

### 3. Add Product to Cart
```bash
# List available products
$INTERACT --eval="JSON.stringify(Array.from(document.querySelectorAll('button[aria-label*=\"Add\"]')).slice(0,8).map(b => b.getAttribute('aria-label')))" 2>/dev/null

# Add specific product (partial match)
$INTERACT --eval="var btn = document.querySelector('button[aria-label*=\"Add\"][aria-label*=\"Pork Shoulder\"]'); if(btn) { btn.click(); 'Added'; } else { 'Not found'; }" 2>/dev/null
```

### 4. Adjust Quantity
```bash
# Increment
$INTERACT --eval="var btn = document.querySelector('button[aria-label*=\"Increment\"][aria-label*=\"Pork\"]'); if(btn) btn.click();" 2>/dev/null

# Multiple increments (get 6 items)
$INTERACT --eval="for(let i=0;i<5;i++){var btn=document.querySelector('button[aria-label*=\"Increment\"][aria-label*=\"Avocado\"]');if(btn)btn.click();}" 2>/dev/null
```

### 5. Check Cart
```bash
# Get cart total
$INTERACT --eval="document.body.innerText.match(/\\$\\d{2,3}\\.\\d{2}/) ? document.body.innerText.match(/\\$\\d{2,3}\\.\\d{2}/)[0] : 'no total found'" 2>/dev/null
```

## Aria-Label Patterns

| Action | Pattern |
|--------|---------|
| Add | `Add 1 ct [Product]` or `Add 1 lb [Product]` |
| Increment | `Increment quantity of [Product]` |
| Decrement | `Decrement quantity of [Product]` |
| Remove | `Remove [Product]` |

## Shopping List Source

The shopping list comes from `recipes.json` in this project. Categories:
- proteins (pork shoulder, chicken thighs, ground beef, etc.)
- vegetables (zucchini, bell peppers, spinach, etc.)
- fresh (avocados, berries, lemons, herbs)
- dairy (butter, cheese, cream, yogurt)
- pantry (broth, seasonings, condiments)

## Tips

1. **Always clear search** before typing new term (prevents concatenation)
2. **Use partial matches** (`aria-label*=`) for flexibility
3. **Add `2>/dev/null`** to suppress Chrome driver noise
4. **Sleep 3 seconds** after search submit for results to load
5. **Check store availability** - not all stores deliver to all addresses
6. **Compare prices** - same item can vary $30+ between stores (e.g., olive oil)

## Troubleshooting

- **Search concatenates**: Clear input with `input.select(); document.execCommand('delete')`
- **Button not found**: List available buttons first, use partial match
- **Store unavailable**: Check address, try different store
- **Session expired**: Re-login with visible browser (`--no-headless`)
