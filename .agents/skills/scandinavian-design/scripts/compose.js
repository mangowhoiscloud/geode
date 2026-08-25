// Compose a demo's before and after captures into one side-by-side image.
//
// A README needs a single image referenced with plain markdown: two separate
// files need HTML <img> tags to sit side by side, and those do not render in
// every markdown viewer. One composite renders everywhere.
//
//   node scripts/compose.js hn [outPath]

const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');
const { repoRoot, fail } = require('./target');

const ROOT = repoRoot();
if (!ROOT) {
  console.error('This tool composes demo captures and needs demos/ above it.');
  process.exit(1);
}

const [, , id, outArg] = process.argv;
if (!id) {
  console.error('usage: node scripts/compose.js <siteId> [outPath]');
  process.exit(1);
}

const dir = path.join(ROOT, 'demos', id);
const before = path.join(dir, 'desktop-before.png');
const after = path.join(dir, 'desktop-after.png');
for (const f of [before, after]) {
  if (!fs.existsSync(f)) {
    console.error(`missing ${path.relative(ROOT, f)} — run snap first`);
    process.exit(1);
  }
}

const out = outArg
  ? path.resolve(outArg)
  : path.join(dir, 'before-after.png');

// Each half renders at this width; the pair plus the gap is the final image.
const HALF = 900;
const GAP = 24;

const asDataUri = (p) =>
  `data:image/png;base64,${fs.readFileSync(p).toString('base64')}`;

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({
    viewport: { width: HALF * 2 + GAP, height: 600 },
    deviceScaleFactor: 1,
  });

  await page.setContent(`
    <style>
      * { margin: 0; box-sizing: border-box; }
      body { background: #fff; font-family: ui-sans-serif, system-ui, sans-serif; }
      .pair { display: grid; grid-template-columns: 1fr 1fr; gap: ${GAP}px; }
      figure { margin: 0; }
      figcaption {
        font-size: 13px; font-weight: 500; color: rgb(0 0 0 / 44%);
        margin-bottom: 8px;
      }
      img { display: block; width: 100%; height: auto; border: 1px solid rgb(0 0 0 / 10%); }
    </style>
    <div class="pair">
      <figure><figcaption>Before</figcaption><img src="${asDataUri(before)}"></figure>
      <figure><figcaption>After</figcaption><img src="${asDataUri(after)}"></figure>
    </div>
  `);
  await page.waitForTimeout(400);

  const el = await page.$('.pair');
  await el.screenshot({ path: out });
  await browser.close();

  const kb = Math.round(fs.statSync(out).size / 1024);
  console.log(`${path.relative(process.cwd(), out)}  ${kb}KB`);
})().catch(fail);
