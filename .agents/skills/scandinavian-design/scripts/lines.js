// Find every rule drawn in a themed page, horizontal and vertical.
//
// Lines are drawn at least six different ways — a border edge, box-shadow, a
// ::before/::after bar, an element collapsed to 1px, and a <canvas> painting a
// hairline — and overriding one of them does nothing about the other five.
// This reports whichever mechanism is actually painting each line, so "I
// removed the border and the line is still there" becomes a lookup.
//
// It scans band by band down the page rather than measuring once at the top.
// A single measurement from scroll position zero misses everything on a page
// that hydrates lazily, and misses everything in a virtualized list, which
// swaps off-screen rows for empty placeholders. Both failure modes report
// "none" while the page is visibly full of lines.
//
//   node scripts/lines.js <siteId> [yMin] [yMax] [width]

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');

// Match run-eval's browser identity. Without the real Chrome user agent and the
// automation hint disabled, sites behind a WAF answer these probes with a 403
// while the screenshots taken by run-eval succeed — so the audit silently
// measures an error page.
const UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

const INTER =
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap';

const { resolveOrExit, fail } = require('./target');

const [, , targetArg, yMinArg, yMaxArg, widthArg] = process.argv;
const site = resolveOrExit(
  targetArg,
  'usage: node scripts/lines.js <url|siteId> [yMin] [yMax] [width]',
);

const yMin = Number(yMinArg ?? 0);
const yMax = Number(yMaxArg ?? 100000);
const width = Number(widthArg ?? 1440);
const height = 900;

function collect({ yMin, yMax }) {
  const hits = [];
  const scrollY = window.scrollY;
  const visible = (c) =>
    c.visibility !== 'hidden' && c.display !== 'none' && c.opacity !== '0';
  // Reject anything fully transparent. Reading the alpha rather than matching
  // the end of the string matters for shadows, where the colour is followed by
  // its offsets: "rgba(21, 22, 23, 0) 0px 0px" paints nothing but does not end
  // in ", 0)".
  const paints = (color) => {
    if (!color || color === 'transparent') return false;
    const m = /rgba?\(([^)]+)\)/.exec(color);
    if (!m) return true;
    const parts = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    return parts.length < 4 || parts[3] !== 0;
  };

  // Screen-reader-only wrappers collapse to a 1px clipped box. Anything inside
  // one paints nothing, and reporting it costs a lookup on every run.
  const srOnly = (el) => {
    let n = el;
    for (let i = 0; i < 5 && n; i++) {
      const r = n.getBoundingClientRect();
      if (r.width <= 1 || r.height <= 1) {
        const c = getComputedStyle(n);
        if (c.overflow === 'hidden' || c.clipPath !== 'none' || c.clip !== 'auto')
          return true;
      }
      n = n.parentElement;
    }
    return false;
  };

  // Identify each element across bands so it is reported once no matter how
  // many times the scan sees it. This replaces an earlier attempt that simply
  // skipped pinned elements after the first band — which hid every rule inside
  // a bar that only becomes sticky once you scroll. It also stops an infinite
  // feed from inflating the count, since a footer rule recorded at seven
  // different offsets as the page extends itself is still one rule.
  const idOf = (el) => {
    if (!el.__lid) el.__lid = ++window.__lidCounter || (window.__lidCounter = 1);
    return el.__lid;
  };

  const describe = (el) => {
    const tag = el.tagName.toLowerCase();
    const id = el.id ? `#${el.id}` : '';
    const cls = String(el.getAttribute('class') || '')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 3)
      .map((c) => `.${c}`)
      .join('');
    return `${tag}${id}${cls}`;
  };

  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    const wide = r.width >= 40;
    const tall = r.height >= 40;
    if (!wide && !tall) continue;
    const c = getComputedStyle(el);
    if (!visible(c)) continue;
    if (srOnly(el)) continue;
    const lid = idOf(el);

    const push = (axis, pos, along, mechanism, detail) => {
      const docY = axis === 'h' ? pos + scrollY : r.top + scrollY;
      if (docY < yMin || docY > yMax) return;
      hits.push({
        axis,
        lid,
        y: Math.round(docY),
        x: Math.round(axis === 'h' ? r.left : pos),
        span: Math.round(along),
        mechanism,
        detail,
        el: describe(el),
      });
    };
    const addH = (y, m, d) => wide && push('h', y, r.width, m, d);
    const addV = (x, m, d) => tall && push('v', x, r.height, m, d);

    if (parseFloat(c.borderTopWidth) > 0 && paints(c.borderTopColor))
      addH(r.top, 'border-top', `${c.borderTopWidth} ${c.borderTopColor}`);
    if (parseFloat(c.borderBottomWidth) > 0 && paints(c.borderBottomColor))
      addH(r.bottom, 'border-bottom', `${c.borderBottomWidth} ${c.borderBottomColor}`);
    if (parseFloat(c.borderLeftWidth) > 0 && paints(c.borderLeftColor))
      addV(r.left, 'border-left', `${c.borderLeftWidth} ${c.borderLeftColor}`);
    if (parseFloat(c.borderRightWidth) > 0 && paints(c.borderRightColor))
      addV(r.right, 'border-right', `${c.borderRightWidth} ${c.borderRightColor}`);

    // A shadow reads as a hairline at whichever edge it hugs, and inset flips
    // which edge that is. A symmetric outset shadow is a ring, not a line.
    if (c.boxShadow && c.boxShadow !== 'none' && paints(c.boxShadow.match(/rgba?\([^)]+\)/)?.[0])) {
      const m = c.boxShadow.match(/(-?[\d.]+)px\s+(-?[\d.]+)px/);
      const dx = m ? parseFloat(m[1]) : 0;
      const dy = m ? parseFloat(m[2]) : 0;
      const inset = c.boxShadow.includes('inset');
      if (dx === 0 && dy === 0 && !inset) {
        addH(r.top, 'shadow-ring', c.boxShadow);
      } else {
        const atTop = inset ? dy > 0 : dy < 0;
        addH(atTop ? r.top : r.bottom, 'box-shadow', c.boxShadow);
      }
    }

    if (r.height > 0 && r.height <= 2 && paints(c.backgroundColor))
      addH(r.top, 'element', `${Math.round(r.height)}px ${c.backgroundColor}`);
    if (r.width > 0 && r.width <= 2 && tall && paints(c.backgroundColor))
      addV(r.left, 'element', `${Math.round(r.width)}px ${c.backgroundColor}`);

    // A canvas can paint a hairline that no computed style will ever reveal.
    // Flag the shape rather than guess the pixels: wide, short, and drawn.
    if (el.tagName === 'CANVAS' && r.width >= 200 && r.height <= 160)
      addH(r.top, 'canvas?', `${Math.round(r.width)}x${Math.round(r.height)} — inspect pixels`);

    for (const pseudo of ['::before', '::after']) {
      const pc = getComputedStyle(el, pseudo);
      if (!pc.content || pc.content === 'none' || !visible(pc)) continue;
      const h = parseFloat(pc.height);
      const bar = h > 0 && h <= 3 && paints(pc.backgroundColor);
      const border =
        (parseFloat(pc.borderTopWidth) > 0 && paints(pc.borderTopColor)) ||
        (parseFloat(pc.borderBottomWidth) > 0 && paints(pc.borderBottomColor));
      if (!bar && !border) continue;
      addH(
        pc.bottom !== 'auto' ? r.bottom : r.top,
        pseudo,
        bar ? `${pc.height} ${pc.backgroundColor}` : `border ${pc.borderTopWidth}/${pc.borderBottomWidth}`,
      );
    }
  }
  return hits;
}

(async () => {
  // Both are empty when the target is a plain URL: your own page is inspected
  // exactly as it is served, with nothing injected on top of it.
  const { theme, shared } = site;

  const browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const page = await browser.newPage({
    viewport: { width, height },
    bypassCSP: true,
    userAgent: UA,
  });

  await page.goto(site.url, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2200);
  // Only the override mode injects anything. Inter comes with the theme, so a
  // page of your own is measured in the type it actually ships.
  if (shared) await page.addStyleTag({ content: shared }).catch(() => {});
  if (theme) {
    await page.addStyleTag({ url: INTER }).catch(() => {});
    await page.addStyleTag({ content: theme });
  }
  await page.evaluate(() => document.fonts.ready).catch(() => {});
  await page.waitForTimeout(1200);

  const seen = new Map();
  const step = Math.round(height * 0.8);
  // Bound the sweep against the page height measured once. An infinite feed
  // extends itself every time the scan reaches the bottom, so a loop that
  // re-reads scrollHeight each pass will never finish.
  const initialH = await page.evaluate(
    () => document.documentElement.scrollHeight,
  );
  const limit = Math.min(yMax, initialH, 30000);
  let top = 0;
  for (let n = 0; n < 45; n++) {
    await page.evaluate((y) => window.scrollTo(0, y), top);
    await page.waitForTimeout(260);
    const batch = await page.evaluate(collect, { yMin, yMax });
    // Key by element identity, not position, so one rule stays one rule.
    for (const h of batch) {
      const key = `${h.axis}|${h.mechanism}|${h.lid}`;
      if (!seen.has(key)) seen.set(key, h);
    }
    if (top + height >= limit) break;
    top += step;
  }
  const docH = await page.evaluate(() => document.documentElement.scrollHeight);
  await page.evaluate(() => window.scrollTo(0, 0));

  const found = [...seen.values()].sort((a, b) => a.y - b.y || b.span - a.span);
  const report = (label, rows) => {
    console.log(`\n${label} (${rows.length})`);
    if (!rows.length) console.log('  none');
    for (const h of rows) {
      console.log(
        `  y=${String(h.y).padStart(6)} x=${String(h.x).padStart(5)} span=${String(
          h.span,
        ).padStart(5)}  ${h.mechanism.padEnd(13)} ${h.el}\n` +
          `${' '.repeat(24)}${h.detail}`,
      );
    }
  };

  console.log(
    `${site.name} — rules from y=${yMin} to y=${Math.min(yMax, docH)} (page is ${docH}px, scanned in bands)`,
  );
  report('horizontal', found.filter((h) => h.axis === 'h'));
  report('vertical', found.filter((h) => h.axis === 'v'));

  await browser.close();
})().catch(fail);
