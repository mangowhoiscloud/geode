// Run with: node scripts/test-docs-navigation.mjs (from site/).
// Exercise the real TypeScript projection without adding a test dependency.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { parseSitemap } from "./sitemap-pages.mjs";

async function loadTypeScript(relativePath) {
  const path = fileURLToPath(new URL(relativePath, import.meta.url));
  const { outputText } = ts.transpileModule(readFileSync(path, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
}

const { DOCS_SITEMAP, flattenSitemap, findPage, adjacentPages } = await loadTypeScript("../src/lib/geode-docs/sitemap.ts");
const navigation = await loadTypeScript("../src/lib/geode-docs/navigation.ts");
const { DOCS_NAV_GROUPS, docChapters, docsPageHref, matchesDocPath, matchesDocQuery } = navigation;
const pages = flattenSitemap();
const topicIds = DOCS_NAV_GROUPS.flatMap((group) => [...group.sectionIds]);
assert.equal(DOCS_NAV_GROUPS.length, 4, "Keep the four reader tasks shallow");
assert.equal(new Set(topicIds).size, topicIds.length, "Each topic belongs to exactly one task");
assert.deepEqual([...topicIds].sort(), DOCS_SITEMAP.map((section) => section.id).sort(), "No topic is omitted or invented");
const groupedSlugs = topicIds.flatMap((id) => DOCS_SITEMAP.find((section) => section.id === id).pages.map((page) => page.slug));
assert.equal(new Set(groupedSlugs).size, groupedSlugs.length, "Each public route appears exactly once in the directory");
assert.deepEqual([...groupedSlugs].sort(), pages.map((page) => page.slug).sort());
for (const group of DOCS_NAV_GROUPS) {
  for (const slug of group.entrySlugs) assert.ok(findPage(slug), `Task shortcut resolves: ${slug}`);
}

// The original sitemap/parser still owns publication and adjacent-page order.
const parsed = parseSitemap(fileURLToPath(new URL("../src/lib/geode-docs/sitemap.ts", import.meta.url)));
assert.deepEqual(parsed.map((page) => page.slug), pages.map((page) => page.slug));
for (const [index, page] of pages.entries()) {
  assert.deepEqual(adjacentPages(page.slug), { prev: pages[index - 1], next: pages[index + 1] });
  assert.equal(docsPageHref(page.slug, "ko"), `/docs${page.slug ? `/${page.slug}` : ""}`);
  assert.equal(docsPageHref(page.slug, "en"), `${docsPageHref(page.slug, "ko")}?lang=en`);
}

const auth = findPage("runtime/auth").page;
for (const query of ["", "  ", "OAuth", "인증", "runtime/auth", "OAuth Codex"]) {
  assert.ok(matchesDocQuery(auth, query), `Title/summary/path query should match: ${query}`);
}
for (const query of ["a-nonexistent-doc", "OAuth nonexistent"]) {
  assert.equal(matchesDocQuery(auth, query), false, `Unmatched terms should not return a result: ${query}`);
}
assert.equal(pages.filter((page) => matchesDocQuery(page, "")).length, pages.length);
assert.equal(pages.filter((page) => matchesDocQuery(page, "a-nonexistent-doc")).length, 0);

const loop = DOCS_SITEMAP.find((section) => section.id === "04-self-improving");
assert.equal(loop.title, "Experimental Loop");
const chapters = docChapters(loop);
assert.equal(chapters.length, 4);
assert.deepEqual(chapters.map((chapter) => chapter.pages.length), [3, 5, 2, 2]);
assert.equal(chapters.find((chapter) => chapter.id === "evaluation").pages[0].slug, "verification/evaluation", "Explain evaluation authority before Petri-specific execution");
for (const section of DOCS_SITEMAP.filter((section) => section.chapters)) {
  assert.equal(new Set(section.chapters.map((chapter) => chapter.id)).size, section.chapters.length);
  assert.equal(docChapters(section).length, section.chapters.length, "No empty chapter in the full catalog");
  const assigned = docChapters(section).flatMap((chapter) => chapter.pages.map((page) => page.slug));
  assert.deepEqual([...assigned].sort(), section.pages.map((page) => page.slug).sort(), "No missing or multiply assigned chapter page");
  assert.ok(parsed.filter((page) => assigned.includes(page.slug)).every((page) => page.section.title === section.title), "Chapter labels must not replace publication section titles");
}
for (const query of ["Published evidence", "공개 결과"]) {
  const filtered = { ...loop, pages: loop.pages.filter((page) => matchesDocQuery(page, query, loop)) };
  assert.deepEqual(docChapters(filtered).map((chapter) => chapter.id), ["evidence"]);
  assert.equal(filtered.pages.length, 2);
}
assert.equal(loop.pages.filter((page) => matchesDocQuery(page, "Experimental Loop", loop)).length, 12);
assert.deepEqual(docChapters({ ...loop, pages: [] }), []);
assert.equal(matchesDocPath("", ""), true);
assert.equal(matchesDocPath("", "petri/seeds"), false);
assert.equal(matchesDocPath("petri/seeds", "petri/seeds/specific-run"), true);
assert.equal(matchesDocPath("petri/seeds", "petri/seeds-extra"), false);
assert.equal(matchesDocPath("petri/run", "petri/run"), true);

// Render the authored body in each language without starting Next or a browser.
// This checks real href values; a source-string assertion misses conditional links.
const require = createRequire(import.meta.url);
for (const slug of ["verification/evaluation", "benchmarks/terminal-bench", "petri/overview", "petri/judge-dimensions", "petri/bundle", "explanation/rsi-roadmap"]) {
  const source = readFileSync(new URL(`../src/app/docs/${slug}/page.tsx`, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  });
  for (const locale of ["ko", "en"]) {
    const exports = {};
    const bodyRequire = (id) => {
      if (id === "@/components/geode-docs/docs-shell") return { DocsShell: ({ children }) => children, Bi: (props) => props[locale] };
      if (id === "@/lib/geode-docs/navigation") return navigation;
      if (id === "@/components/geode-docs/benchmark-run-ledger") {
        const ledger = {};
        const source = readFileSync(new URL("../src/components/geode-docs/benchmark-run-ledger.tsx", import.meta.url), "utf8");
        const { outputText } = ts.transpileModule(source, {
          compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
        });
        new Function("require", "exports", outputText)(bodyRequire, ledger);
        return ledger;
      }
      if (id === "@/data/geode/landing-evidence.json") return JSON.parse(readFileSync(new URL("../src/data/geode/landing-evidence.json", import.meta.url), "utf8"));
      if (id.endsWith(".css")) return {};
      return require(id);
    };
    new Function("require", "exports", outputText)(bodyRequire, exports);
    const html = renderToStaticMarkup(createElement(exports.default));
    if (slug === "explanation/rsi-roadmap") {
      assert.ok(html.includes('href="https://arxiv.org/abs/2609.11873v2"'), "Pin the roadmap's reference version");
      for (const anchor of ["autonomy-roadmap", "terms", "evidence", "next", "eco2"]) {
        assert.ok(html.includes(`id="${anchor}"`), `Roadmap section renders in ${locale}: ${anchor}`);
      }
    }
    if (slug === "benchmarks/terminal-bench") {
      assert.ok(html.includes("/geode/benchmarks/terminal-bench/replay/"), "Preserve the native replay route");
      assert.ok(html.includes("system_prompt_override"), "Disclose the measured thin-adapter configuration");
      assert.ok(html.includes("terminal_exec"), "Name the measured tool surface");
      assert.equal(html.includes("the runtime as a whole"), false);
      assert.ok(html.includes("d277607f3a179f191ad24b1497c0934beb9d2470"), "Preserve recovered accounting evidence");
      assert.ok(html.includes("cache_read_tokens"), "Disclose the historical cache export mismatch in both languages");
      assert.ok(html.includes(locale === "ko" ? "관측 하한" : "observed lower bound"), "Partial usage must not read as final totals");
    }
    if (slug === "verification/evaluation") {
      assert.ok(html.includes("verification_error"));
      assert.ok(html.includes("reflexion"));
      assert.equal(html.includes("passed=true, score=0.5"), false, "Malformed judge data is not a success");
    }
    const links = [...html.matchAll(/href="(\/geode\/docs\/[^"]+)"/g)].map((match) => new URL(match[1], "https://docs.test"));
    const relevant = slug === "benchmarks/terminal-bench" ? links.filter((url) => url.pathname === "/geode/docs/verification/evaluation") : links;
    assert.ok(relevant.length, `Evaluation crosslinks render: ${slug}/${locale}`);
    for (const url of relevant) {
      assert.equal(url.searchParams.get("lang"), locale === "en" ? "en" : null, `Body link preserves language: ${slug}/${locale} -> ${url}`);
      assert.ok(findPage(url.pathname.slice("/geode/docs/".length)), `Body link resolves: ${url}`);
    }
  }
}

console.log(`Docs navigation: ${pages.length} routes in ${DOCS_SITEMAP.length} topics across 4 tasks; chapter membership/filtering, current paths, locale links, and parser/adjacency parity passed.`);
