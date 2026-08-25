// Structural recon for an arbitrary site: screenshot + DOM/style digest +
// layout container tree. Run this before writing any override CSS.
//
// Usage: node recon.js <url> <outPrefix>
const { chromium } = require('playwright-core');

const [, , url, prefix] = process.argv;

(async () => {
  const browser = await chromium.launch({ channel: 'chrome' });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    bypassCSP: true,
  });
  await page.goto(url, { waitUntil: 'load', timeout: 45000 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: `${prefix}-before.png` });

  const digest = await page.evaluate(() => {
    const ids = [...document.querySelectorAll('[id]')]
      .map((e) => `#${e.id} <${e.tagName.toLowerCase()}>`)
      .slice(0, 60);
    const classCount = {};
    for (const el of document.querySelectorAll('[class]')) {
      for (const c of el.classList) classCount[c] = (classCount[c] || 0) + 1;
    }
    const classes = Object.entries(classCount)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 60)
      .map(([c, n]) => `.${c} x${n}`);

    // Layout container tree: large elements only, 4 levels deep.
    const tree = [];
    const walk = (el, depth) => {
      if (depth > 4 || tree.length > 100) return;
      const r = el.getBoundingClientRect();
      if (r.width * r.height < 10000) return;
      const cls = el.classList?.length ? '.' + [...el.classList].join('.') : '';
      tree.push(
        `${'  '.repeat(depth)}${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${cls} ${Math.round(r.width)}x${Math.round(r.height)}`
      );
      for (const c of el.children) walk(c, depth + 1);
    };
    walk(document.body, 0);

    const body = getComputedStyle(document.body);
    const sampleLink = document.querySelector('a');
    const h = document.querySelector('h1,h2,h3,h4');
    return {
      title: document.title,
      bodyFont: body.fontFamily,
      bodyBg: body.backgroundColor,
      bodyColor: body.color,
      linkColor: sampleLink ? getComputedStyle(sampleLink).color : null,
      headingSample: h
        ? `${h.tagName} "${h.textContent.trim().slice(0, 40)}" ${getComputedStyle(h).fontSize}/${getComputedStyle(h).fontWeight}`
        : null,
      ids,
      classes,
      layoutTree: tree,
    };
  });
  console.log(JSON.stringify(digest, null, 2));
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
