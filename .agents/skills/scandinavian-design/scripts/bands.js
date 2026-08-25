// Slice a themed page into viewport-height bands you can actually look at.
//
// A full-page capture of a long marketing or news page is 10,000-20,000px tall
// and is not reviewable as a single image — it scales down past the point where
// type, rules, and alignment can be judged. Cropping it afterwards is worse:
// image tools crop from the centre by default and will hand you a mid-page slice
// labelled as the top. This captures each band directly from the live page at
// full resolution instead.
//
//   node scripts/bands.js <url|siteId> [desktop|mobile] [maxBands]
//
// Writes demos/<id>/bands/<viewport>-after-01.png ... and prints the list.

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');
const { resolveOrExit, fail } = require('./target');

// Match run-eval's browser identity. Without the real Chrome user agent and the
// automation hint disabled, sites behind a WAF answer these probes with a 403
// while the screenshots taken by run-eval succeed — so the audit silently
// measures an error page.
const UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

const INTER =
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';

const [, , targetArg, viewportArg, maxArg] = process.argv;
const site = resolveOrExit(
  targetArg,
  'usage: node scripts/bands.js <url|siteId> [desktop|mobile] [maxBands]',
);

const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
};
const viewportName = viewportArg === 'mobile' ? 'mobile' : 'desktop';
const viewport = VIEWPORTS[viewportName];
const maxBands = Number(maxArg ?? 14);


(async () => {
  // A demo writes beside its own captures; a URL writes to ./bands in the
  // directory you ran from, so the tool needs no repo layout to be useful.
  const outDir = site.dir
    ? path.join(site.dir, 'bands')
    : path.join(process.cwd(), 'bands');
  fs.mkdirSync(outDir, { recursive: true });
  for (const f of fs.readdirSync(outDir)) {
    if (f.startsWith(`${viewportName}-`)) fs.unlinkSync(path.join(outDir, f));
  }

  const { theme, shared } = site;

  const browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const page = await browser.newPage({
    viewport,
    bypassCSP: true,
    userAgent: UA,
  });

  await page.goto(site.url, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  if (shared) await page.addStyleTag({ content: shared }).catch(() => {});
  if (theme) {
    await page.addStyleTag({ url: INTER }).catch(() => {});
    await page.addStyleTag({ content: theme });
  }
  await page.evaluate(() => document.fonts.ready).catch(() => {});
  await page.waitForTimeout(1500);

  const docH = await page.evaluate(() => {
    window.scrollTo(0, 0);
    return document.documentElement.scrollHeight;
  });
  const bands = Math.min(maxBands, Math.ceil(docH / viewport.height));

  const written = [];
  for (let i = 0; i < bands; i++) {
    const top = i * viewport.height;
    await page.evaluate((y) => window.scrollTo(0, y), top);
    await page.waitForTimeout(320);
    const name = `${viewportName}-${String(i + 1).padStart(2, '0')}.png`;
    await page.screenshot({ path: path.join(outDir, name) });
    written.push({ name, top });
  }

  console.log(
    `${site.name} ${viewportName} — ${docH}px in ${bands} bands of ${viewport.height}px` +
      (bands * viewport.height < docH ? ` (capped at ${maxBands})` : ''),
  );
  for (const w of written) {
    console.log(`  ${path.relative(process.cwd(), path.join(outDir, w.name))}   y=${w.top}`);
  }

  await browser.close();
})().catch(fail);
