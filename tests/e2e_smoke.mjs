#!/usr/bin/env node
import { spawn } from 'node:child_process';
import process from 'node:process';
import { chromium } from 'playwright';

const PORT = Number(process.env.E2E_PORT || 8112);
const BASE = `http://127.0.0.1:${PORT}`;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitForHealth(timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${BASE}/api/health`, { cache: 'no-store' });
      if (res.ok) {
        const payload = await res.json();
        if (payload?.ok) return payload;
      }
    } catch (_) {}
    await sleep(150);
  }
  throw new Error(`Server did not become healthy at ${BASE}`);
}

function normalizeNumericInputValue(value) {
  if (value === null || value === undefined) return '';
  const text = String(value).trim();
  if (!text) return '';
  const num = Number(text);
  return Number.isFinite(num) ? String(num) : text;
}

async function run() {
  const env = { ...process.env, OURA_AUTO_SYNC: '0' };
  const server = spawn('python3', ['app_server.py', '--port', String(PORT)], {
    cwd: process.cwd(),
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let serverOut = '';
  server.stdout.on('data', (d) => {
    serverOut += d.toString();
  });
  server.stderr.on('data', (d) => {
    serverOut += d.toString();
  });

  const cleanup = async () => {
    if (!server.killed) {
      server.kill('SIGTERM');
      await sleep(500);
      if (!server.killed) {
        server.kill('SIGKILL');
      }
    }
  };

  let browser;
  try {
    await waitForHealth();

    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();

    await page.goto(`${BASE}/index.html`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#entryDate');

    const ouraStatsText = await page.locator('#ouraTodayStats').innerText();
    if (/No Oura data yet/i.test(ouraStatsText)) {
      throw new Error('Oura stats panel shows no data unexpectedly.');
    }

    const originalDate = await page.locator('#entryDate').inputValue();
    const originalWeight = normalizeNumericInputValue(await page.locator('#entryWeight').inputValue());
    const originalWater = normalizeNumericInputValue(await page.locator('#entryWater').inputValue());

    const tempWeight = '70.2';
    const tempWater = '2.3';

    await page.locator('#entryWeight').fill(tempWeight);
    await page.locator('#entryWater').fill(tempWater);
    await page.locator('button:has-text("Save Entry")').click();
    await page.waitForFunction(() => {
      const el = document.querySelector('#checkinStatus');
      return !!el && /Saved check-in/i.test(el.textContent || '');
    }, null, { timeout: 10000 });

    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('#entryDate');

    const reloadedDate = await page.locator('#entryDate').inputValue();
    if (reloadedDate !== originalDate) {
      throw new Error(`Date changed unexpectedly after reload: ${reloadedDate} != ${originalDate}`);
    }

    const reloadedWeight = normalizeNumericInputValue(await page.locator('#entryWeight').inputValue());
    const reloadedWater = normalizeNumericInputValue(await page.locator('#entryWater').inputValue());
    if (reloadedWeight !== tempWeight || reloadedWater !== tempWater) {
      throw new Error(`Save/refresh mismatch. weight=${reloadedWeight}, water=${reloadedWater}`);
    }

    // Restore original values.
    await page.locator('#entryWeight').fill(originalWeight);
    await page.locator('#entryWater').fill(originalWater);
    if (!originalWeight && !originalWater) {
      await page.locator('button:has-text("Clear")').click();
      await page.waitForFunction(() => {
        const el = document.querySelector('#checkinStatus');
        return !!el && /Cleared check-in/i.test(el.textContent || '');
      }, null, { timeout: 10000 });
    } else {
      await page.locator('button:has-text("Save Entry")').click();
      await page.waitForFunction(() => {
        const el = document.querySelector('#checkinStatus');
        return !!el && /Saved check-in/i.test(el.textContent || '');
      }, null, { timeout: 10000 });
    }

    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('#entryDate');
    const restoredWeight = normalizeNumericInputValue(await page.locator('#entryWeight').inputValue());
    const restoredWater = normalizeNumericInputValue(await page.locator('#entryWater').inputValue());
    if (restoredWeight !== originalWeight || restoredWater !== originalWater) {
      throw new Error(`Restore mismatch. weight=${restoredWeight}/${originalWeight}, water=${restoredWater}/${originalWater}`);
    }

    const syncPayload = await page.evaluate(async () => {
      const resp = await fetch('/api/sync/status', { cache: 'no-store' });
      return { status: resp.status, payload: await resp.json() };
    });
    if (syncPayload.status !== 200 || !syncPayload.payload?.ok) {
      throw new Error(`Sync status endpoint check failed: ${JSON.stringify(syncPayload)}`);
    }

    await page.waitForFunction(() => {
      const badge = document.querySelector('#chatBadge');
      return !!badge && (badge.textContent || '').trim() !== '' && (badge.textContent || '').trim() !== 'CONNECTING';
    }, null, { timeout: 10000 });

    const chatStatusText = await page.locator('#chatStatus').innerText();
    const chatMessagesText = await page.locator('#chatMessages').innerText();
    if (!chatStatusText && !chatMessagesText) {
      throw new Error('Chat panel did not load status/history text.');
    }

    console.log('Browser e2e smoke passed.');
  } catch (err) {
    console.error('Browser e2e smoke failed.');
    console.error(err?.stack || String(err));
    if (serverOut) {
      console.error('--- server output ---');
      console.error(serverOut.slice(-4000));
    }
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    await cleanup();
  }
}

run();
