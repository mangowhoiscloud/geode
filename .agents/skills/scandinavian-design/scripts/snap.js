// Before/after screenshotter for CSS-only redesigns of live sites.
// Loads a URL, screenshots it, injects Inter + an override stylesheet,
// and screenshots again.
//
// Usage: node snap.js <url> <cssFile> <outPrefix> [width] [height]
//   e.g. node snap.js https://example.com theme.css example 1440 900
//        node snap.js https://example.com theme.css example-mobile 390 844
//
// Requires playwright-core and a local Chrome (channel: "chrome").
const { chromium } = require('playwright-core');
const fs = require('fs');

const [, , url, cssFile, prefix, width = '1440', height = '900'] = process.argv;

(async () => {
  const browser = await chromium.launch({ channel: 'chrome' });
  const page = await browser.newPage({
    viewport: { width: Number(width), height: Number(height) },
    deviceScaleFactor: 2,
    bypassCSP: true, // sites like HN block external styles via CSP
  });
  await page.goto(url, { waitUntil: 'load', timeout: 45000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${prefix}-before.png` });

  // Inter (the skill's default web typeface), then the override sheet.
  await page.addStyleTag({
    url: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap',
  });
  await page.addStyleTag({ content: fs.readFileSync(cssFile, 'utf8') });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${prefix}-after.png` });

  await browser.close();
  console.log('done:', `${prefix}-before.png`, `${prefix}-after.png`);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
