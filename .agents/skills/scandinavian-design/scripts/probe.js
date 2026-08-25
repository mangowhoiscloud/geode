// Probe rendered elements by their visible text to get real selectors,
// computed colors, and ancestor chains. Use when override rules do not take
// effect (specificity battles) or when an element's markup is unknown.
//
// Matching is deliberately loose. An earlier version required an exact
// textContent match on an element with no children, which fails on most real
// sites: labels are nested two or three levels below the element whose style
// you need, and template markup is full of newlines and tabs that make an
// exact comparison impossible. This collapses whitespace, matches on substring,
// and reports the innermost element containing the text plus the chain above
// it, so a wrapper that carries the styling is still visible.
//
// Usage: node scripts/probe.js <url> "text one,text two"

const { chromium } = require('playwright-core');

const [, , url, textsArg] = process.argv;
const texts = (textsArg || '')
  .split(',')
  .map((t) => t.trim())
  .filter(Boolean);

if (!url || !texts.length) {
  console.error('usage: node scripts/probe.js <url> "text one,text two"');
  process.exit(1);
}

const UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

(async () => {
  const browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
    args: ['--disable-blink-features=AutomationControlled'],
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    bypassCSP: true,
    userAgent: UA,
  });
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2500);
  // Scroll once so lazily hydrated regions exist before we look for text.
  await page.evaluate(async () => {
    const step = Math.round(window.innerHeight * 0.8);
    const cap = Math.min(document.documentElement.scrollHeight, 20000);
    for (let y = 0, n = 0; y < cap && n < 25; y += step, n++) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 100));
    }
    window.scrollTo(0, 0);
    await new Promise((r) => setTimeout(r, 300));
  });

  const info = await page.evaluate((targets) => {
    const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const sel = (el) =>
      `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${
        el.classList?.length ? '.' + [...el.classList].slice(0, 3).join('.') : ''
      }`;

    const describe = (el) => {
      const c = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const chain = [];
      let n = el.parentElement;
      for (let i = 0; i < 4 && n && n.tagName !== 'BODY'; i++) {
        chain.push(sel(n));
        n = n.parentElement;
      }
      const bits = [
        `    ${sel(el)}  ${Math.round(r.width)}x${Math.round(r.height)}`,
        `      color=${c.color}  bg=${c.backgroundColor}`,
        `      font=${c.fontSize}/${c.fontWeight} ${c.fontFamily.split(',')[0]}  transform=${c.textTransform}`,
        `      border=${c.borderTopWidth} ${c.borderTopColor}  radius=${c.borderRadius}`,
      ];
      if (c.boxShadow !== 'none') bits.push(`      shadow=${c.boxShadow}`);
      if (chain.length) bits.push(`      in: ${chain.join(' < ')}`);
      return bits.join('\n');
    };

    return targets
      .map((t) => {
        const want = norm(t).toLowerCase();
        // Every element whose own text contains the target, innermost first.
        const matches = [...document.querySelectorAll('body *')].filter((el) => {
          if (!norm(el.textContent).toLowerCase().includes(want)) return false;
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0;
        });
        if (!matches.length) return `"${t}": NOT FOUND`;
        // Innermost = the one with no matching descendant, then its ancestors.
        const innermost = matches.filter(
          (el) => !matches.some((o) => o !== el && el.contains(o)),
        );
        const show = innermost.slice(0, 3);
        const extra =
          innermost.length > show.length
            ? `\n    ... ${innermost.length - show.length} more match${innermost.length - show.length === 1 ? '' : 'es'}`
            : '';
        return `"${t}"  ${innermost.length} match${innermost.length === 1 ? '' : 'es'}\n${show
          .map(describe)
          .join('\n')}${extra}`;
      })
      .join('\n\n');
  }, texts);

  console.log(info);
  await browser.close();
})().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
