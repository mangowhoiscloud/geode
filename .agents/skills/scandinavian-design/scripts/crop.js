#!/usr/bin/env node
// Zoomed crops of specific regions with a site's theme applied, for close review.
//
// Usage: node scripts/crop.js <siteId> <outDir> "<selector>=<name>" ["<selector>=<name>" ...]
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const { repoRoot } = require('./target');

const ROOT = repoRoot();
if (!ROOT) {
  console.error('This tool drives the eval harness and needs demos/sites.json above it.');
  process.exit(1);
}
const SITES = JSON.parse(
  fs.readFileSync(path.join(ROOT, 'demos/sites.json'), 'utf8')
);
const INTER =
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap';
const SHARED = fs.readFileSync(path.join(ROOT, 'demos/shared.css'), 'utf8');

const [, , siteId, outDir, ...targets] = process.argv;
const site = SITES.find((s) => s.id === siteId);
if (!site) {
  console.error(`Unknown site "${siteId}"`);
  process.exit(1);
}

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const css = fs.readFileSync(
    path.join(ROOT, 'demos', site.id, 'theme.css'),
    'utf8'
  );
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 3,
    bypassCSP: true,
  });
  await page.goto(site.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2500);
  await page.addStyleTag({ content: SHARED }).catch(() => {});
  await page.addStyleTag({ url: INTER }).catch(() => {});
  await page.addStyleTag({ content: css });
  await page.evaluate(() => document.fonts.ready).catch(() => {});
  await page.waitForTimeout(1500);

  for (const target of targets) {
    const idx = target.lastIndexOf('=');
    const selector = target.slice(0, idx);
    const name = target.slice(idx + 1);
    const el = page.locator(selector).first();
    try {
      await el.screenshot({ path: path.join(outDir, `${name}.png`) });
      console.log(`ok ${name}  ${selector}`);
    } catch (err) {
      console.log(`MISS ${name}  ${selector}  (${err.message.split('\n')[0]})`);
    }
  }
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
