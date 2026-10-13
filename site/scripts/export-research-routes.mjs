/** Route projection of the frozen Jev package. Never regenerates its source or PDFs. */
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const legacyPath = "/geode/resaerch/jev-system1-offloading/";
export const readerPath = "/geode/research/jev-system1-offloading/";
const origin = "https://mangowhoiscloud.github.io";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function replaceRequired(html, before, after) {
  assert(html.includes(before), `Frozen reader routing contract changed: ${before}`);
  return html.replaceAll(before, after);
}

export function projectReader(source) {
  let html = replaceRequired(source, origin + legacyPath, origin + readerPath);
  // Rebase only file references, leaving scene and language URLs at the new resource.
  html = html.replace(/(["'])(assets\/[^"']+|report-(?:ko|en)\.pdf)\1/g,
    (_, quote, file) => `${quote}${legacyPath}${file}${quote}`);
  html = replaceRequired(html, 'class="reader-home" href="/geode/" aria-label="GEODE home">GEODE<', 'class="reader-home" href="/geode/research/#research-jev">GEODE / Research<');
  html = replaceRequired(html, '.reader-home{font-weight:700;', '.reader-home{white-space:nowrap;flex-shrink:0;font-weight:700;');
  html = replaceRequired(html, "href='/geode/?lang='+(english?'en':'ko');", "href='/geode/research/?lang='+(english?'en':'ko')+'#research-jev';");
  html = replaceRequired(html, "jump(s.id);history.replaceState(null,'','#'+s.id);", "jump(s.id);");
  // The frozen film's show() owns all scene navigation (TOC, keyboard, overview,
  // and pager). Project that boundary once; builds within a scene stay local.
  return html.replace("</script>", `
let restoringResearchRoute=false;
const routeShow=show;
show=function(index){routeShow(index);const hash='#'+slides[state.index].id;if(!restoringResearchRoute&&!renderMode&&location.hash!==hash)history.pushState(history.state,'',hash);};
function restoreResearchRoute(){
 restoringResearchRoute=true;
 try{if(location.hash==='#readerSources'){openReaderSources();}else{if(readerSources.open)readerSources.close();if(location.hash)jump(location.hash.slice(1));else show(0);}}
 finally{restoringResearchRoute=false;}
}
window.addEventListener('popstate',restoreResearchRoute);
readerSourcesButton.addEventListener('click',()=>{if(location.hash!=='#readerSources')history.pushState(history.state,'','#readerSources');});
</script>`);
}

export function legacyRedirect() {
  // Fixed same-origin target; user-controlled query/hash never become a destination.
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Jev Decision Offloading — moved</title><link rel="canonical" href="${origin + readerPath}"></head><body><p><a id="reader" href="${readerPath}">Jev Decision Offloading · 보고서 열기 / Open report</a></p><script>const target=${JSON.stringify(readerPath)}+location.search+location.hash;document.getElementById('reader').href=target;location.replace(target);</script></body></html>\n`;
}

export function exportResearchRoutes(out = join(root, "out")) {
  const source = readFileSync(join(root, "public", legacyPath.slice("/geode/".length), "index.html"), "utf8");
  for (const [path, html] of [[readerPath, projectReader(source)], [legacyPath, legacyRedirect()]]) {
    const destination = join(out, path.slice("/geode/".length), "index.html");
    mkdirSync(dirname(destination), { recursive: true });
    writeFileSync(destination, html);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  exportResearchRoutes();
  console.log("Research routes exported; frozen Jev assets remain at their published addresses.");
}
