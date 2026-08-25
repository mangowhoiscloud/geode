#!/usr/bin/env node
// Eval harness: recon a site, then capture desktop/mobile before/after snaps
// with the Scandinavian override stylesheet injected.
//
// Usage:
//   node scripts/run-eval.js recon [id]
//   node scripts/run-eval.js snap [id]
//   node scripts/run-eval.js all [id]
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
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';
const SHARED = fs.readFileSync(path.join(ROOT, 'demos/shared.css'), 'utf8');
const UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

const CONSENT_NAMES = [
  'Accept additional cookies',
  'Reject additional cookies',
  'Accept all',
  'Accept All',
  'Accept cookies',
  'Accept',
  'I agree',
  'Agree',
  'Allow all',
  'Allow All',
  'Got it',
  'Continue',
  'OK',
];

const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
};

function sitesFromArgs() {
  const id = process.argv[3];
  if (!id) return SITES;
  const match = SITES.find((s) => s.id === id);
  if (!match) {
    console.error(`Unknown site id "${id}".`);
    process.exit(1);
  }
  return [match];
}

async function mapLimit(items, limit, fn) {
  const out = [];
  let i = 0;
  async function worker() {
    while (i < items.length) {
      const idx = i++;
      out[idx] = await fn(items[idx]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return out;
}

async function dismissConsent(page) {
  for (const name of CONSENT_NAMES) {
    const btn = page.getByRole('button', { name, exact: true }).first();
    try {
      if (await btn.isVisible({ timeout: 600 })) {
        await btn.click({ timeout: 1500 });
        await page.waitForTimeout(400);
        return;
      }
    } catch {
      /* keep trying */
    }
  }
  const cssClickable = [
    '#onetrust-accept-btn-handler',
    '#accept-all',
    'button[id*="accept" i]',
    'button[class*="accept" i]',
  ];
  for (const sel of cssClickable) {
    const loc = page.locator(sel).first();
    try {
      if (await loc.isVisible({ timeout: 400 })) {
        await loc.click({ timeout: 1500 });
        await page.waitForTimeout(400);
        return;
      }
    } catch {
      /* keep trying */
    }
  }
}

async function withPage(url, viewport, fn) {
  const browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
    args: ['--disable-blink-features=AutomationControlled'],
  });
  try {
    const page = await browser.newPage({
      viewport,
      deviceScaleFactor: 2,
      bypassCSP: true,
      userAgent: UA,
    });
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(2500);
    await dismissConsent(page);
    await page.addStyleTag({ content: SHARED }).catch(() => {});
    await page.waitForTimeout(400);
    return await fn(page);
  } finally {
    await browser.close();
  }
}

async function runRecon(site) {
  const dir = path.join(ROOT, 'demos', site.id);
  fs.mkdirSync(dir, { recursive: true });
  const prefix = path.join(dir, 'recon');
  console.log(`recon ${site.id}: ${site.url}`);
  await withPage(site.url, VIEWPORTS.desktop, async (page) => {
    await page.screenshot({ path: `${prefix}.png` });
    const digest = await page.evaluate(() => {
      const ids = [...document.querySelectorAll('[id]')]
        .map((e) => `#${e.id} <${e.tagName.toLowerCase()}>`)
        .slice(0, 80);
      const classCount = {};
      for (const el of document.querySelectorAll('[class]')) {
        for (const c of el.classList) classCount[c] = (classCount[c] || 0) + 1;
      }
      const classes = Object.entries(classCount)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 80)
        .map(([c, n]) => `.${c} x${n}`);

      const tree = [];
      const walk = (el, depth) => {
        if (depth > 4 || tree.length > 120) return;
        const r = el.getBoundingClientRect();
        if (r.width * r.height < 10000) return;
        const cls = el.classList?.length ? '.' + [...el.classList].join('.') : '';
        tree.push(
          `${'  '.repeat(depth)}${el.tagName.toLowerCase()}${
            el.id ? '#' + el.id : ''
          }${cls} ${Math.round(r.width)}x${Math.round(r.height)}`
        );
        for (const c of el.children) walk(c, depth + 1);
      };
      walk(document.body, 0);

      const body = getComputedStyle(document.body);
      const sampleLink = document.querySelector('a');
      const h = document.querySelector('h1,h2,h3,h4');
      const testers = [...document.querySelectorAll('[data-testid]')]
        .map((e) => e.getAttribute('data-testid'))
        .filter(Boolean);
      const testIds = [...new Set(testers)].slice(0, 40);
      return {
        title: document.title,
        href: location.href,
        bodyFont: body.fontFamily,
        bodyBg: body.backgroundColor,
        bodyColor: body.color,
        linkColor: sampleLink ? getComputedStyle(sampleLink).color : null,
        headingSample: h
          ? `${h.tagName} "${h.textContent.trim().slice(0, 48)}" ${
              getComputedStyle(h).fontSize
            }/${getComputedStyle(h).fontWeight}`
          : null,
        ids,
        classes,
        testIds,
        layoutTree: tree,
      };
    });
    fs.writeFileSync(`${prefix}.json`, JSON.stringify(digest, null, 2));
    console.log(`  title: ${digest.title}`);
    console.log(`  heading: ${digest.headingSample || '(none)'}`);
  });
}

function themeCss(site) {
  const p = path.join(ROOT, 'demos', site.id, 'theme.css');
  return fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null;
}

// Force every lazy image to load before either capture. Without this the
// before shot is taken at scroll position zero and the after shot lands after
// a full-page expansion has pulled the rest of the page into view, so media
// that had never loaded appears only in the after — or, worse, media that had
// loaded goes blank — and the difference reads as damage the stylesheet did.
async function settleMedia(page) {
  await page.evaluate(async () => {
    const step = Math.round(window.innerHeight * 0.8);
    const cap = Math.min(document.documentElement.scrollHeight, 30000);
    for (let y = 0, n = 0; y < cap && n < 40; y += step, n++) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 120));
    }
    window.scrollTo(0, 0);
    await new Promise((r) => setTimeout(r, 300));
    await Promise.all(
      [...document.images]
        .filter((i) => !i.complete)
        .map(
          (i) =>
            new Promise((r) => {
              i.addEventListener('load', r, { once: true });
              i.addEventListener('error', r, { once: true });
              setTimeout(r, 2000);
            })
        )
    );
  });
  await page.waitForTimeout(400);
}

// `scrollY` may be a single number or `{ desktop, mobile }`, because the two
// layouts rarely put the same thing at the same offset.
async function atOffset(page, site, viewportName) {
  const raw = site.scrollY;
  const y = Number(
    raw && typeof raw === 'object' ? raw[viewportName] || 0 : raw || 0
  );
  if (!y) return;
  await page.evaluate((v) => window.scrollTo(0, v), y);
  await page.waitForTimeout(500);
}

async function runSnap(site) {
  const css = themeCss(site);
  if (!css) {
    console.log(`snap ${site.id}: skipped (no theme.css)`);
    return;
  }
  const dir = path.join(ROOT, 'demos', site.id);
  console.log(`snap ${site.id}: ${site.url}`);
  for (const [name, viewport] of Object.entries(VIEWPORTS)) {
    const prefix = path.join(dir, name);
    // Two captures per state. The fold pair is what the gallery compares, and
    // the full pair is what verification needs: a 900px shot of an 11,000px
    // page can pass review having never shown nine of its ten chapters. Full
    // shots use `scale: 'css'` so a tall page does not land at twice the
    // device scale and produce an unusable file.
    let height = 0;
    await withPage(site.url, viewport, async (page) => {
      // Let the page reach the same age the "after" shot will be taken at.
      // Without this the before lands ~2s younger, and anything that mounts in
      // between — lazy sections, chat widgets — appears only in the after and
      // reads as something the stylesheet did.
      await page.evaluate(() => document.fonts.ready).catch(() => {});
      await settleMedia(page);
      // A site may open on a leaderboard ad or a consent band that has nothing
      // to do with the design. `scrollY` in sites.json moves the fold capture
      // down to where the page actually starts. It applies to both states, so
      // the pair stays comparable, and the full-page shots are unaffected.
      await atOffset(page, site, name);
      await page.waitForTimeout(1800);
      await page.screenshot({ path: `${prefix}-before.png` });
      await page.screenshot({
        path: `${prefix}-before-full.png`,
        fullPage: true,
        scale: 'css',
      });
      await page.addStyleTag({ url: INTER }).catch(() => {});
      await page.addStyleTag({ content: css });
      await page.evaluate(() => document.fonts.ready).catch(() => {});
      await atOffset(page, site, name);
      await page.waitForTimeout(1800);
      await page.screenshot({ path: `${prefix}-after.png` });
      await page.screenshot({
        path: `${prefix}-after-full.png`,
        fullPage: true,
        scale: 'css',
      });
      height = await page.evaluate(() => document.documentElement.scrollHeight);
    });
    const shown = Math.round((viewport.height / height) * 100);
    console.log(
      `  ${name}  full page ${height}px — the fold shot shows ${shown}%`
    );
  }
}

(async () => {
  const cmd = process.argv[2];
  if (!['recon', 'snap', 'all'].includes(cmd)) {
    console.error('Usage: node scripts/run-eval.js recon|snap|all [id]');
    process.exit(1);
  }
  const sites = sitesFromArgs();
  const limit = 2;
  if (cmd === 'recon' || cmd === 'all') {
    await mapLimit(sites, limit, async (site) => {
      try {
        await runRecon(site);
      } catch (err) {
        console.error(`recon ${site.id} failed:`, err.message);
      }
    });
  }
  if (cmd === 'snap' || cmd === 'all') {
    await mapLimit(sites, limit, async (site) => {
      try {
        await runSnap(site);
      } catch (err) {
        console.error(`snap ${site.id} failed:`, err.message);
      }
    });
  }
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
