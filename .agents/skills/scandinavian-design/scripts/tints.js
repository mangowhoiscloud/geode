// Find tinted neutrals left behind in a themed page's chrome.
//
// A neutralizing pass is easy to believe you have finished, because the colours
// that survive are the ones a CSS read cannot see: literal hex buried in
// component CSS, and token aliases you never overrode. This walks every painted
// element and flags any colour that is neither properly neutral nor genuinely
// expressive — a grey with a visible cast.
//
// The measure is channel spread, max(r,g,b) - min(r,g,b). Zero is neutral. A
// spread of two or three is invisible. Ten or more reads distinctly warm or
// cool beside true black or white. Above roughly forty it is a real colour
// doing a real job, and not this tool's business.
//
// Product media is exempt, but only `<img>`, `<svg>`, `<canvas>` and friends are
// detectable as media. A marketing page often rebuilds its product screenshots
// in live DOM, and those mockups read the same tokens as the chrome around
// them. Pass `--exclude=<selector>` to name the mockup roots, so the number
// this prints is the chrome you actually own.
//
//   node scripts/tints.js <url|siteId> [minSpread] [maxSpread] [width] [--exclude=sel]

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

const args = process.argv.slice(2);
const excludeArg = args.find((a) => a.startsWith('--exclude='));
const exclude = excludeArg ? excludeArg.slice('--exclude='.length) : '';
const [targetArg, minArg, maxArg, widthArg] = args.filter(
  (a) => !a.startsWith('--'),
);
const site = resolveOrExit(
  targetArg,
  'usage: node scripts/tints.js <url|siteId> [minSpread] [maxSpread] [width] [--exclude=sel]',
);

const minSpread = Number(minArg ?? 5);
const maxSpread = Number(maxArg ?? 40);
const width = Number(widthArg ?? 1440);


(async () => {
  const { theme, shared } = site;

  const browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const page = await browser.newPage({
    viewport: { width, height: 900 },
    bypassCSP: true,
    userAgent: UA,
  });

  await page.goto(site.url, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2200);
  if (shared) await page.addStyleTag({ content: shared }).catch(() => {});
  if (theme) {
    await page.addStyleTag({ url: INTER }).catch(() => {});
    await page.addStyleTag({ content: theme });
  }
  await page.evaluate(() => document.fonts.ready).catch(() => {});
  await page.waitForTimeout(1200);

  // Scroll the whole page before measuring. Lazily hydrated chapters do not
  // exist in the DOM until they scroll into view, and a scan from the top
  // reports a clean page while most of it has never rendered.
  // The cap matters: an infinite feed grows its scrollHeight every time you
  // reach the bottom, so a loop bounded by the live document height never
  // terminates. Measure the page once and take a fixed number of steps.
  await page.evaluate(async () => {
    const step = Math.round(window.innerHeight * 0.8);
    const cap = Math.min(document.documentElement.scrollHeight, 30000);
    for (let y = 0, n = 0; y < cap && n < 40; y += step, n++) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 140));
    }
    window.scrollTo(0, 0);
    await new Promise((r) => setTimeout(r, 500));
  });
  await page.waitForTimeout(600);

  const found = await page.evaluate(
    ({ minSpread, maxSpread, exclude }) => {
      const parse = (v) => {
        const m = /rgba?\(([^)]+)\)/.exec(v || '');
        if (!m) return null;
        const parts = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
        if (parts.length < 3 || parts.some(Number.isNaN)) return null;
        const alpha = parts.length > 3 ? parts[3] : 1;
        if (alpha === 0) return null;
        return { rgb: parts.slice(0, 3), alpha };
      };
      const spread = (rgb) => Math.max(...rgb) - Math.min(...rgb);

      // Measure what is painted, not what is declared. A tint on a dark canvas
      // cannot be built from low-alpha black, so design systems build it from a
      // saturated colour at low alpha instead: rgba(179,218,255,0.08) declares a
      // spread of 76, which reads as a real colour worth keeping, but composites
      // to rgb(23,27,30) — a spread of 7, and a faint blue wash over whatever it
      // covers. Judging the declared value misses the entire category.
      const behind = (el) => {
        let n = el.parentElement;
        while (n) {
          const p = parse(getComputedStyle(n).backgroundColor);
          if (p && p.alpha >= 0.95) return p.rgb;
          n = n.parentElement;
        }
        const b = parse(getComputedStyle(document.body).backgroundColor);
        return b && b.alpha >= 0.95 ? b.rgb : [255, 255, 255];
      };
      const composite = (p, bg) =>
        p.alpha >= 1
          ? p.rgb
          : p.rgb.map((c, i) => Math.round(c * p.alpha + bg[i] * (1 - p.alpha)));

      // Gradients never appear in a colour property, so a page that moved its
      // casts into background-image reads as clean.
      const gradientStops = (v) => {
        if (!v || v === 'none' || !/gradient/.test(v)) return [];
        return (v.match(/rgba?\([^)]+\)/g) || []).map(parse).filter(Boolean);
      };

      // Product media is allowed its own colour. Anything inside a picture,
      // video, canvas, or svg is the medium, not the chrome around it.
      // `svg` is deliberately not exempt on its own. Design systems draw their
      // icons as inline SVG, and icons are chrome that belongs on the ink
      // ladder — exempting the element wholesale made the tool blind to every
      // icon on the page, including 250 gold stars it reported as clean. An
      // SVG inside a real media container is still media, and a standalone
      // illustration can be named with --exclude.
      const mediaSel =
        'picture, video, canvas, img, figure' + (exclude ? `, ${exclude}` : '');
      const inMedia = (el) => el.closest(mediaSel) !== null;

      const describeEl = (el) => {
        const cls = String(el.getAttribute('class') || '')
          .split(/\s+/)
          .filter(Boolean)
          .slice(0, 2)
          .map((x) => `.${x}`)
          .join('');
        return `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${cls}`;
      };

      const byKey = new Map();
      const saturated = new Map();
      for (const el of document.querySelectorAll('*')) {
        if (inMedia(el)) continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const c = getComputedStyle(el);
        if (c.visibility === 'hidden' || c.display === 'none') continue;

        const bg = behind(el);
        const candidates = [];
        for (const prop of [
          'color',
          'backgroundColor',
          'borderTopColor',
          'borderRightColor',
          'borderBottomColor',
          'borderLeftColor',
          'outlineColor',
          'fill',
          'stroke',
        ]) {
          const p = parse(c[prop]);
          if (!p) continue;
          // A border colour on a zero-width edge paints nothing.
          if (prop.startsWith('border')) {
            const edge = prop.replace('Color', 'Width');
            if (parseFloat(c[edge]) === 0) continue;
          }
          candidates.push({ prop, raw: c[prop], p });
        }
        for (const p of gradientStops(c.backgroundImage)) {
          candidates.push({
            prop: 'backgroundImage',
            raw: `gradient stop rgba(${p.rgb.join(',')},${p.alpha})`,
            p,
          });
        }

        for (const { prop, raw, p } of candidates) {
          const declared = spread(p.rgb);
          // Anything past the ceiling is real colour, which this tool exists to
          // leave alone — but on a page whose canvas is a brand hue, that is the
          // single biggest thing a monochrome pass has to deal with, and
          // reporting only tinted neutrals would call such a page clean before
          // anything had been done to it. Collect it separately.
          if (declared > maxSpread) {
            const key = `sat|${prop}|${raw}`;
            const hit = saturated.get(key) || {
              prop,
              value: raw,
              spread: declared,
              count: 0,
              sample: '',
            };
            hit.count += 1;
            if (!hit.sample) hit.sample = describeEl(el);
            saturated.set(key, hit);
            continue;
          }
          // The declared colour has to be the thing contributing the cast. A
          // genuinely neutral value at low alpha inherits whatever tint sits
          // behind it, and blaming the overlay for its backdrop sends you
          // editing the wrong rule — the backdrop is reported on its own.
          if (declared < minSpread) continue;
          const painted = composite(p, bg);
          const s = spread(painted);
          if (s < minSpread || s > maxSpread) continue;
          const key = `${prop}|${raw}`;
          const hit = byKey.get(key) || {
            prop,
            value: raw,
            spread: s,
            declared,
            alpha: p.alpha,
            count: 0,
            sample: '',
          };
          hit.count += 1;
          if (!hit.sample) {
            const cls = String(el.getAttribute('class') || '')
              .split(/\s+/)
              .filter(Boolean)
              .slice(0, 2)
              .map((x) => `.${x}`)
              .join('');
            hit.sample = `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${cls}`;
          }
          byKey.set(key, hit);
        }
      }
      const bySize = (a, b) => b.count - a.count;
      return {
        tinted: [...byKey.values()].sort(bySize),
        saturated: [...saturated.values()].sort(bySize).slice(0, 12),
      };
    },
    { minSpread, maxSpread, exclude },
  );

  const { tinted, saturated } = found;
  const total = tinted.reduce((n, h) => n + h.count, 0);
  console.log(
    `${site.name} — colour in chrome at ${width}px` +
      (exclude ? `\nexcluding media roots: ${exclude}` : ''),
  );

  console.log(
    `\ntinted neutrals (spread ${minSpread}-${maxSpread}) — ${total} painted element${
      total === 1 ? '' : 's'
    } across ${tinted.length} colour${tinted.length === 1 ? '' : 's'}`,
  );
  for (const h of tinted) {
    // Show the declared spread too when compositing changed the verdict, since
    // that is the number a reader of the CSS would have seen.
    const note =
      h.alpha < 1 ? ` (declared ${h.declared} at ${h.alpha} alpha)` : '';
    console.log(
      `  ${String(h.count).padStart(4)}x  painted spread ${String(h.spread).padStart(2)}  ` +
        `${h.prop.padEnd(17)} ${h.value.padEnd(30)} e.g. ${h.sample}${note}`,
    );
  }
  if (!tinted.length) console.log('  none');

  const satTotal = saturated.reduce((n, h) => n + h.count, 0);
  console.log(
    `\nsaturated colour (spread over ${maxSpread}) — ${satTotal} painted element${
      satTotal === 1 ? '' : 's'
    }, top ${saturated.length}`,
  );
  console.log(
    '  Real colour, which this tool does not judge. Read it as the inventory a\n' +
      '  monochrome pass has to account for: brand marks and semantic states belong\n' +
      '  here, a page canvas does not.',
  );
  for (const h of saturated) {
    console.log(
      `  ${String(h.count).padStart(4)}x  spread ${String(h.spread).padStart(3)}  ` +
        `${h.prop.padEnd(17)} ${h.value.padEnd(30)} e.g. ${h.sample}`,
    );
  }
  if (!saturated.length) console.log('  none');

  await browser.close();
})().catch(fail);
