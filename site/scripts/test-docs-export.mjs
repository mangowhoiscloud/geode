// Run with: node scripts/test-docs-export.mjs (from site/).
import assert from "node:assert/strict";
import { buildTurndown } from "./export-docs-md.mjs";

const markdown = buildTurndown().turndown(`
<table><caption>Same common trials.</caption>
<thead><tr><th>Runtime</th><th>Pass rate</th></tr></thead>
<tbody><tr><th>GEODE</th><td><strong>79.02%</strong>
<div aria-hidden="true"><span style="width:79.02%"></span></div>
<div aria-hidden="true"><span>0%</span><span>100%</span></div></td></tr></tbody></table>
<svg role="img"><title>Interval</title><desc>95% interval: -5.40 to +8.05 pp; includes zero.</desc><text>-10</text><text>10</text></svg>
<details><summary>Sources</summary><p>Frozen evidence remains available.</p></details>
<pre>printf 'hello'</pre>`);
assert.ok(markdown.includes("Same common trials.\n\n| Runtime | Pass rate |"));
assert.ok(markdown.includes("| GEODE | **79.02%** |"));
assert.ok(!markdown.includes("0%100%"));
assert.ok(!markdown.includes("-1010"));
assert.ok(markdown.includes("95% interval: -5.40 to +8.05 pp; includes zero."));
assert.ok(markdown.includes("Frozen evidence remains available."));
assert.ok(markdown.includes("```\nprintf 'hello'\n```"));
console.log("Docs export: chart decorations omitted; GFM rows, captions, SVG descriptions, disclosures, and code retained.");
