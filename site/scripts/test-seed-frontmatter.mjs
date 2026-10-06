import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import ts from "typescript";

const require = createRequire(import.meta.url);
const seedModule = {};
const code = ts.transpileModule(readFileSync(new URL("../src/lib/geode-docs/seed-frontmatter.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText;
new Function("require", "exports", code)(require, seedModule);
const { parseSeedMarkdown } = seedModule;

const body = "# Scenario\n\nKeep body separators.\n---\nTrailing newline.\n";
const parsed = parseSeedMarkdown(`---\nname: "Tool: recovery"\ncategory: broken_tool_use\ntarget_dims: [1, 7]\ntags:\n  - 한국어\n  - repair\nenabled: true\nscore: 0.5\nnotes: |\n  first\n  second\n---\n${body}`);
assert.deepEqual(parsed.data, {
  name: "Tool: recovery", category: "broken_tool_use", target_dims: [1, 7],
  tags: ["한국어", "repair"], enabled: true, score: 0.5, notes: "first\nsecond\n",
});
assert.equal(parsed.content, body);
assert.deepEqual(parseSeedMarkdown(`\uFEFF---\r\nname: seed\r\n---\r\n${body}`), { data: { name: "seed" }, content: body });
assert.deepEqual(parseSeedMarkdown(body), { data: {}, content: body });
assert.deepEqual(parseSeedMarkdown(`---\n---\n${body}`), { data: {}, content: body });
assert.throws(() => parseSeedMarkdown("---\nname: seed\n"), /closing fence/);
assert.throws(() => parseSeedMarkdown("---\n- scalar-list\n---\n"), /mapping/);
assert.throws(() => parseSeedMarkdown("---\nname: [broken\n---\n"));
console.log("Seed frontmatter: YAML mapping, body preservation, BOM/CRLF, optional headers, and malformed input contracts passed.");
