// Count how much content is visible per screen, before and after the theme.
//
// The skill names reduced density as an escalation trigger and asks for counts
// before and after, but judging that from screenshots does not work on a long
// page — you cannot hold nine screens in your head, and a change that adds
// height while removing nothing looks fine in every individual shot. This
// scrolls a viewport at a time and counts the distinct links intersecting each
// screen, with and without the stylesheet, in one run.
//
//   node scripts/density.js <url|siteId> [desktop|mobile] [screens]

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');
const { resolveOrExit, fail } = require('./target');

const INTER =
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';
const UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

const [, , targetArg, viewportArg, screensArg] = process.argv;
const site = resolveOrExit(
  targetArg,
  'usage: node scripts/density.js <url|siteId> [desktop|mobile] [screens]',
);

const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
};
const viewportName = viewportArg === 'mobile' ? 'mobile' : 'desktop';
const viewport = VIEWPORTS[viewportName];
const screens = Number(screensArg ?? 7);


function countPerScreen({ screens, vh }) {
  const rows = [];
  const seenAll = new Set();
  for (let i = 0; i < screens; i++) {
    window.scrollTo(0, i * vh);
    const top = window.scrollY;
    const links = new Set();
    let headings = 0;
    for (const a of document.links) {
      const r = a.getBoundingClientRect();
      if (r.bottom < 0 || r.top > vh) continue;
      if (r.width === 0 || r.height === 0) continue;
      const text = (a.innerText || '').trim();
      if (!text) continue;
      const key = a.href + '|' + text.slice(0, 40);
      links.add(key);
      seenAll.add(key);
    }
    for (const h of document.querySelectorAll('h1,h2,h3,h4')) {
      const r = h.getBoundingClientRect();
      if (r.bottom < 0 || r.top > vh) continue;
      if (r.width === 0 || r.height === 0) continue;
      headings += 1;
    }
    rows.push({ screen: i + 1, top, links: links.size, headings });
  }
  window.scrollTo(0, 0);
  return { rows, total: seenAll.size, height: document.documentElement.scrollHeight };
}

async function measure(page, css) {
  // `scrollTo` does not complete synchronously when the page asks for smooth
  // scrolling, so every measurement lands back at y=0 and each screen reports
  // the same counts — which also silently defeats the dropped-control check,
  // since the whole page looks like one viewport.
  await page.addStyleTag({
    content: 'html, body { scroll-behavior: auto !important; }',
  });
  await page.evaluate(async () => {
    const step = Math.round(window.innerHeight * 0.8);
    const cap = Math.min(document.documentElement.scrollHeight, 30000);
    for (let y = 0, n = 0; y < cap && n < 40; y += step, n++) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 120));
    }
    window.scrollTo(0, 0);
    await new Promise((r) => setTimeout(r, 400));
  });
  if (css) {
    await page.addStyleTag({ url: INTER }).catch(() => {});
    await page.addStyleTag({ content: css });
    await page.evaluate(() => document.fonts.ready).catch(() => {});
    await page.waitForTimeout(1600);
  }
  return page.evaluate(countPerScreen, { screens, vh: viewport.height });
}

(async () => {
  const { theme, shared } = site;

  const browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
    args: ['--disable-blink-features=AutomationControlled'],
  });

  const results = {};
  for (const [label, css] of [['before', ''], ['after', theme]]) {
    const page = await browser.newPage({ viewport, bypassCSP: true, userAgent: UA });
    await page.goto(site.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(2500);
    await page.addStyleTag({ content: shared }).catch(() => {});
    results[label] = await measure(page, css);
    await page.close();
  }
  await browser.close();

  const b = results.before;
  const a = results.after;
  console.log(
    `${site.name} — ${viewportName} density over ${screens} screens of ${viewport.height}px\n`,
  );
  console.log('  screen        before          after');
  console.log('              links  head   links  head');
  for (let i = 0; i < screens; i++) {
    const br = b.rows[i] || { links: 0, headings: 0 };
    const ar = a.rows[i] || { links: 0, headings: 0 };
    const flag = ar.links < br.links * 0.8 ? '  <- down' : '';
    console.log(
      `  ${String(i + 1).padStart(6)}  ${String(br.links).padStart(7)}${String(
        br.headings,
      ).padStart(6)}  ${String(ar.links).padStart(6)}${String(ar.headings).padStart(6)}${flag}`,
    );
  }
  const sum = (rows, k) => rows.reduce((n, r) => n + r[k], 0);
  const bl = sum(b.rows, 'links');
  const al = sum(a.rows, 'links');
  const pct = bl ? Math.round(((al - bl) / bl) * 100) : 0;
  console.log(
    `\n  links across those screens  ${bl} -> ${al} (${pct >= 0 ? '+' : ''}${pct}%)`,
  );
  console.log(`  distinct links on page      ${b.total} -> ${a.total}`);
  console.log(
    `  page height                 ${b.height}px -> ${a.height}px (${
      b.height ? (a.height > b.height ? '+' : '') + Math.round(((a.height - b.height) / b.height) * 100) : 0
    }%)`,
  );
  if (a.total < b.total)
    console.log(`\n  ${b.total - a.total} links present before are missing after — check for dropped controls.`);
})().catch(fail);
