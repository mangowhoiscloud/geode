// Package an approved film source, not a second slide or metric generator.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync, realpathSync, statSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

export const EVIDENCE = "https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/3bcf4044eb5c2411dd48122d672aef72a83fb30e/reports/e2e-validation/jev-v3-20260927/";
export const PUBLIC_URL = "https://mangowhoiscloud.github.io/geode/resaerch/jev-system1-offloading/";
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
const escape = (text) => text.replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const privatePath = /(?:file:\/\/|\/(?:Users|home)\/|localhost|127\.0\.0\.1|research-team-20260926)/i;

// Reader chrome only. The approved slide canvas and its runtime remain source-owned.
const READER_CSS = `
body.jev-reader{color:var(--film-ink);min-height:100dvh}
.reader-header.masthead{width:calc(100% - 48px);max-width:1376px;padding:16px 0;margin:0 auto;min-height:76px;gap:24px}
.reader-identity,.reader-actions,.reader-languages,.reader-pager,.reader-links{display:flex;align-items:center}
.reader-identity{gap:20px;min-width:0}.reader-home{font-weight:700;letter-spacing:.03em;padding:0 20px 0 0;border-right:1px solid var(--film-line)}
.reader-heading{min-width:0}.reader-header.masthead h1{font:600 18px/1.3 Pretendard,sans-serif;letter-spacing:-.02em;margin:0;color:var(--film-ink)}
.reader-heading p{margin:3px 0 0;font-size:12px;line-height:1.35;color:var(--film-muted)}
.reader-actions{gap:16px;flex-shrink:0}.reader-languages{padding:2px;border:1px solid var(--film-line);border-radius:6px;gap:2px}
.reader-header a,.reader-navigation button,.reader-toc button{display:inline-flex;align-items:center;justify-content:center;min-height:44px;white-space:nowrap;font:500 13px/1.2 Pretendard,sans-serif;color:var(--film-ink);text-decoration:none;border-radius:4px}
.reader-languages a{min-width:68px;padding:0 12px;color:var(--film-muted)}.reader-languages a[aria-current=page]{color:var(--film-ink);background:var(--film-paper);box-shadow:0 1px 2px #171b2712}
.reader-header .reader-download{padding:0 18px;background:var(--film-ink);color:var(--film-paper);font-weight:600;border:1px solid var(--film-ink)}
.reader-header a:not(.reader-download):hover,.reader-navigation button:not(:disabled):hover{background:var(--surface-card);color:var(--film-ink)}
.reader-header .reader-download:hover{background:var(--body-strong)}
.reader-header a:focus-visible,.reader-navigation button:focus-visible,.reader-footer button:focus-visible,.reader-toc :focus-visible,.reader-sources :focus-visible{outline:2px solid var(--film-accent);outline-offset:3px}
.reader-header a:active,.reader-navigation button:not(:disabled):active{transform:translateY(1px)}
.reader-workspace{width:calc(100% - 48px);max-width:1376px;margin:auto;display:grid;grid-template-columns:224px minmax(0,1fr);gap:24px}.reader-content{min-width:0}
/* Layer 1 keeps navigation above the canvas; the mobile dialog uses the native top layer. */
.reader-navigation.navigation{position:sticky;top:0;z-index:1;width:100%;margin:0 0 12px;padding:10px 0;background:var(--canvas);border-top:1px solid var(--film-line);gap:16px;flex-wrap:nowrap}
.reader-tools.toolbar{gap:4px;margin:0;flex-wrap:wrap}.reader-navigation.navigation button{padding:0 12px;background:transparent;border:1px solid transparent;border-radius:4px}
.reader-navigation.navigation button[aria-pressed=true],.reader-navigation.navigation button[aria-current=page]{background:var(--surface-card);border-color:var(--film-line);color:var(--film-ink)}
.reader-navigation button:disabled{opacity:1;color:var(--muted-soft);cursor:not-allowed}
.reader-pager{gap:8px;flex-shrink:0}.reader-pager .counter{margin:0 4px;min-width:166px;text-align:center;color:var(--film-muted);font:12px/1.3 'IBM Plex Mono',Pretendard,monospace;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
html:not(.render-mode) body.jev-reader .deck{width:100%;max-width:none}
html:not(.render-mode) body.jev-reader .stage{box-shadow:0 2px 12px #171b270a;outline:1px solid var(--film-line)}
.reader-footer.below{margin:20px auto 24px;padding:16px 0 0;grid-template-columns:minmax(0,1fr) auto;align-items:start;gap:24px}
.reader-footer.below p{font-size:12px;line-height:1.65;color:var(--film-muted);word-break:keep-all}
.reader-links{gap:20px;flex-wrap:wrap}.reader-links button{display:inline-flex;align-items:center;min-height:44px;padding:0;background:transparent;border:0;border-radius:4px;font:500 13px/1.4 Pretendard,sans-serif;color:var(--film-ink);text-decoration:underline;text-underline-offset:4px;text-decoration-color:var(--film-line);white-space:nowrap;cursor:pointer}.reader-links button:hover{text-decoration-color:currentColor}
html.reader-sources-open{overflow:hidden}.reader-sources.sources{position:fixed;inset:16px 16px 16px auto;width:600px;max-width:calc(100vw - 32px);height:calc(100dvh - 32px);max-height:none;margin:0;padding:0;border:1px solid var(--film-line);border-radius:6px;background:var(--canvas);color:var(--film-ink);overflow:hidden}.reader-sources[open]{display:flex;flex-direction:column}.reader-sources:not([open]){display:none}.reader-sources::backdrop{background:color-mix(in srgb,var(--film-ink) 30%,transparent)}
.reader-sources-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-shrink:0;padding:16px 24px;border-bottom:1px solid var(--film-line)}.reader-sources-heading h2{margin:0;font:600 18px/1.4 Pretendard,sans-serif;letter-spacing:-.02em}.reader-sources-heading button{min-width:64px;min-height:44px;padding:0 12px;border:1px solid var(--film-line);border-radius:4px;background:transparent;color:var(--film-ink);font:500 13px/1.4 Pretendard,sans-serif;cursor:pointer}.reader-sources-heading button:hover{background:var(--surface-card)}
.reader-sources-body{overflow:auto;overscroll-behavior:contain;min-height:0;padding:20px 24px 28px}.reader-sources-body p{margin:0;font:400 13px/1.65 Pretendard,sans-serif;color:var(--film-muted);word-break:keep-all;overflow-wrap:anywhere}.reader-source-groups{display:grid;grid-template-columns:minmax(0,1fr);gap:28px;margin:28px 0}.reader-source-group h3{margin:0 0 8px;font:600 13px/1.4 Pretendard,sans-serif}.reader-source-group ul{margin:0;padding:0;list-style:none}.reader-source-group li{margin:0!important}.reader-source-group a{display:grid;grid-template-columns:40px minmax(0,1fr);align-items:baseline;gap:12px;min-height:44px;padding:10px 0;font-size:13px;line-height:1.5;color:var(--film-muted);text-decoration:none;overflow-wrap:anywhere}.reader-source-group a>span:first-child{font:11px/1.5 'IBM Plex Mono',monospace}.reader-source-group a:hover{color:var(--film-ink);text-decoration:underline;text-underline-offset:3px}.reader-archive-note{padding-top:20px;border-top:1px solid var(--film-line)}.reader-archive-note h3{font:600 12px/1.4 Pretendard,sans-serif;margin:0 0 8px}.reader-archive-note ul{margin:8px 0 16px;padding-left:18px;font-size:12px;color:var(--film-muted)}.reader-archive-note li{margin:6px 0;overflow-wrap:anywhere}.reader-archive-note p+p{margin-top:12px}
.reader-toc{position:sticky;inset:auto;top:16px;align-self:start;width:100%;max-width:none;max-height:calc(100dvh - 32px);margin:0;padding:0 12px 0 0;border:0;border-right:1px solid var(--film-line);background:var(--canvas);color:var(--film-ink)}
.reader-toc[open]{display:flex;flex-direction:column}.reader-toc:not([open]){display:none}.reader-toc-heading{display:flex;align-items:center;justify-content:space-between;min-height:64px;gap:12px;flex-shrink:0}.reader-toc h2{margin:0;font:600 13px/1.4 Pretendard,sans-serif}.reader-toc small{font-weight:400;color:var(--film-muted)}.reader-toc button{display:none;background:transparent;border:1px solid var(--film-line);padding:0 12px}
.reader-scene-list{overflow:auto;overscroll-behavior:contain;padding:4px 4px 12px}.reader-scene-list a{display:grid;grid-template-columns:24px minmax(0,1fr);align-items:start;gap:8px;min-height:44px;padding:10px 8px;margin-bottom:2px;border-radius:4px;color:var(--film-muted);font-size:12px;line-height:1.45;text-decoration:none;word-break:keep-all;overflow-wrap:anywhere}.reader-scene-list a>span:first-child{font-family:'IBM Plex Mono',monospace;font-size:11px;padding-top:1px}.reader-scene-list a:hover{background:var(--surface-card);color:var(--film-ink)}.reader-scene-list a[aria-current=page]{background:var(--surface-card);color:var(--film-ink);font-weight:600}
.reader-toc::backdrop{background:color-mix(in srgb,var(--film-ink) 30%,transparent)}
html:not(.render-mode) .reader-content>.overview{width:100%;max-width:none;padding:0 0 32px;gap:16px}
@media(max-width:1023px){.reader-workspace{grid-template-columns:minmax(0,1fr)}.reader-toc{position:fixed;inset:16px auto 16px 16px;width:min(360px,calc(100% - 32px));max-height:calc(100dvh - 32px);height:calc(100dvh - 32px);padding:0 12px;border:1px solid var(--film-line);border-radius:6px}.reader-toc button{display:inline-flex}.reader-footer.below{grid-template-columns:1fr;gap:8px}}
@media(max-width:767px){.reader-header.masthead{display:grid;grid-template-columns:minmax(0,1fr);justify-content:stretch;width:calc(100% - 32px);gap:10px;padding:12px 0}.reader-identity{gap:14px}.reader-home{padding-right:14px}.reader-header.masthead h1{font-size:16px}.reader-actions{justify-content:space-between;gap:12px}.reader-workspace{width:calc(100% - 32px)}.reader-navigation.navigation{flex-direction:column;align-items:stretch;gap:8px;padding:8px 0;margin-bottom:10px}.reader-tools.toolbar{justify-content:space-between;gap:2px}.reader-navigation button{padding:0 10px}.reader-pager{justify-content:space-between;gap:0}.reader-pager .counter{min-width:0;margin:0 2px;font-size:11px}.reader-footer.below{margin-top:16px}.reader-links{gap:20px}.jev-reader>.sources,html:not(.render-mode) .jev-reader>.overview{width:calc(100% - 32px)}.reader-source-groups{grid-template-columns:1fr;gap:24px}.reader-source-group a{min-height:44px}html:not(.render-mode) .jev-reader>.overview{grid-template-columns:1fr}}
@media print{.reader-toc,.reader-sources{display:none!important}.reader-workspace{display:block;width:100%;max-width:none}}
@media(max-width:767px){html:not(.render-mode) .reader-content>.overview{grid-template-columns:1fr}.reader-sources.sources{inset:8px;width:calc(100vw - 16px);max-width:none;height:calc(100dvh - 16px)}.reader-sources-heading{padding:12px 16px}.reader-sources-body{padding:20px 16px 24px}}
html.render-mode .reader-toc,html.render-mode .reader-sources{display:none!important}html.render-mode .reader-workspace{display:block;width:1920px;max-width:none}
@media(prefers-reduced-motion:reduce){.reader-header a:active,.reader-navigation button:active{transform:none}}
`;

function readerSources(html) {
  return html.replace(/<details class="sources">[^]*?<\/details>/, original => {
    const entries = [...original.matchAll(/<a\b[^>]*href="([^"]+)"[^>]*>([^]*?)<\/a>/g)].map(([, href, label]) => ({ href, label, id: label.match(/^\[([^\]]+)\]/)?.[1] }));
    const groups = [
      ["연구 기록", "Study records", ["W1", "W2"]],
      ["TypeSafe 공식 문서", "TypeSafe documentation", ["S3", "S15", "S8", "S9"]],
      ["관련 연구", "Related research", ["A4", "A5", "DP1", "DP2", "N1", "N2", "RS1"]],
      ["설계·해석 참고", "Design and interpretation", ["N3", "PR5", "PR6", "PR7", "N4", "V2"]],
    ];
    const known = groups.flatMap(([, , ids]) => ids);
    assert(entries.every(entry => known.includes(entry.id) || entry.href === EVIDENCE + "README.md"), "Unclassified public source; preserve it before regrouping");
    const identified = entries.filter(entry => entry.id);
    assert.equal(new Set(identified.map(entry => entry.id)).size, identified.length, "Source IDs must not hide duplicate destinations");
    const recordLinks = [["DATA", "연구 근거·보존 기록", "Study evidence and archived records", "README.md"], ["SCORE", "채점 기준", "Scoring rules", "SCORING.md"], ["REPRO", "재현 안내", "Reproduction guide", "REPRODUCE.md"]].map(([id, ko, en, file]) => `<li><a href="${EVIDENCE + file}"><span>${id}</span> <span data-en="${en}">${ko}</span></a></li>`).join("");
    const sections = groups.map(([ko, en, ids], index) => `<section class="reader-source-group"><h3 data-en="${en}">${ko}</h3><ul>${index === 0 ? recordLinks : ""}${ids.map(id => entries.find(entry => entry.id === id)).filter(Boolean).map(({ id, href, label }) => `<li><a href="${href}"><span>${id}</span> <span>${label.replace(/^\[[^\]]+\]\s*/, "")}</span></a></li>`).join("")}</ul></section>`).join("");
    const unavailable = [...original.matchAll(/<span\b[^>]*>([^]*?)<\/span>/g)].map(([, label]) => `<li>${label}</li>`).join("");
    const boundaries = [...original.matchAll(/<p\b[^]*?<\/p>/g)].map(match => match[0]).join("");
    return `<dialog class="sources reader-sources" id="readerSources" aria-labelledby="readerSourcesTitle"><header class="reader-sources-heading"><h2 id="readerSourcesTitle" data-en="Evidence and sources">근거와 출처</h2><button id="closeReaderSources" autofocus data-en="Close">닫기</button></header><div class="reader-sources-body"><p data-en="Study records are pinned to commit 3bcf404. Reference IDs match the slides; interviews and design references are not experimental results.">연구 기록은 커밋 3bcf404에 고정되어 있습니다. 출처 ID는 슬라이드와 연결되며, 인터뷰·설계 참고는 실험 결과와 구분합니다.</p><div class="reader-source-groups">${sections}</div><div class="reader-archive-note"><h3 data-en="Historical records outside this public package">이 공개 패키지에 포함되지 않은 역사 기록</h3><ul>${unavailable}</ul>${boundaries}</div></div></dialog>`;
  });
}

function readerChrome(html, videoUrl) {
  const tools = `<div class="toolbar reader-tools"><button id="contentsButton" aria-controls="readerScenes" aria-expanded="false" data-en="Scenes">장면 목록</button><button id="overviewButton" aria-pressed="false" data-en="All scenes">전체 장면</button></div>`;
  const navigation = `<nav class="navigation reader-navigation" aria-label="Report navigation">${tools}<div class="reader-pager"><button id="previous" data-en="Previous">이전</button><span class="counter" aria-live="polite" aria-atomic="true"></span><button id="next" data-en="Next">다음</button></div><span id="timing" hidden></span></nav>`;
  const header = `<header class="masthead reader-header"><div class="reader-identity"><a class="reader-home" href="/geode/" aria-label="GEODE home">GEODE</a><div class="reader-heading"><h1>Jev: System 1 offloading</h1><p data-en="Research report">연구 보고서</p></div></div><div class="reader-actions"><nav class="reader-languages" aria-label="Language"><a href="?lang=ko" lang="ko" aria-current="page">한국어</a><a href="?lang=en" lang="en" aria-current="false">English</a></nav><a class="reader-download" id="reportDownload" href="report-ko.pdf" download data-en="Download PDF">PDF 다운로드</a>${videoUrl ? `<a href="${escape(videoUrl)}" data-en="Watch film">영상 보기</a>` : ""}</div></header>`;
  const scenePanel = `<dialog class="reader-toc" id="readerScenes" aria-labelledby="readerScenesTitle"><div class="reader-toc-heading"><h2 id="readerScenesTitle"><span data-en="Scenes">장면 목록</span> <small id="readerSceneCount"></small></h2><button id="closeReaderScenes" data-en="Close">닫기</button></div><nav class="reader-scene-list" aria-label="Scenes"></nav></dialog>`;
  return readerSources(html).replace(/<body\b/, '<body class="jev-reader"')
    .replace(/<header\b[^]*?<\/header>/, header)
    .replace(/<nav class="navigation"[^]*?<\/nav>/, "")
    .replace(/<main\b/, `<div class="reader-workspace">${scenePanel}<div class="reader-content">${navigation}<main`)
    .replace("<script>", "</div></div><script>")
    .replace('<div class="below">', '<div class="below reader-footer">')
    .replace("</head>", `<link rel="canonical" href="${PUBLIC_URL}"><meta name="description" content="Jev decision offloading: an evidence-bound bilingual research report."><style id="public-report-controls">${READER_CSS}</style></head>`);
}

export function safeRelative(path) {
  assert(typeof path === "string" && path.length > 0 && !isAbsolute(path), "Asset paths must be relative");
  assert(!/[\\?#\s]/.test(path) && !path.split("/").some((part) => !part || part === ".." || part === "."), "Unsafe asset path");
  return path;
}

export function projectPreview(source, { date, assets, videoUrl = null }) {
  assert(/^\d{4}-\d{2}-\d{2}$/.test(date), "A publication date is required");
  assert(source.includes("window.__film=") && source.includes('id="overview"'), "Unsupported preview contract");
  if (videoUrl) assert(/^https:\/\/(?:www\.)?(?:youtube\.com|youtu\.be)\//.test(videoUrl), "Use the approved public video URL");
  let html = source
    .replaceAll("jev-film-sources.md", EVIDENCE + "README.md")
    .replaceAll("Full claim/source map and historical receipts", "Public study evidence and archived records")
    .replaceAll("full source map", "public study evidence").replaceAll("전체 출처 지도", "공개 연구 근거")
    .replace(/<!--[^]*?-->/g, "")
    .replace(/\sdata-note(?:-[\w-]+)?="[^"]*"/g, "")
    .replace(/\sdata-(?:replay-manifest|film-edition)="[^"]*"/g, "")
    .replace(/<button\b[^>]*id="notesButton"[^>]*>[^]*?<\/button>/, "")
    .replace(/<aside\b[^>]*id="notes"[^>]*>[^]*?<\/aside>/, "")
    .replace(/\/\/ User-supplied MP3[^]*?(?=if\(english\))/, "")
    .replace(/if\(\['timeline','mix'\]\.includes\(params\.get\('music'\)\)\)\{[^]*?(?=<\/script>)/, "")
    .replace("['timeline','mix'].includes(params.get('music'))||", "")
    .replace("document.getElementById('notes').textContent=slides[state.index].dataset.note;", "")
    .replace(/document\.getElementById\('notesButton'\)\.onclick=\(\)=>\{[^]*?\};/, "")
    .replace("if(e.key.toLowerCase()==='n')document.getElementById('notesButton').click();", "")
    .replaceAll(" · N Notes", "").replaceAll(" · N 노트", "")
    .replace(/Research film \/ Revised [^<]+/, `Research report / ${date}`)
    .replace(/<div class="below">[^]*?(?=<\/main>)/, `<div class="below"><p data-en="One source for the interactive report and both PDFs. Historical failures, partial analyses and synthetic-task limits remain separate.">웹 보고서와 두 언어 PDF는 같은 원고를 사용합니다. 과거 실패·부분 분석·합성 과제의 한계는 별도로 보존합니다.</p><div class="reader-links"><button id="openReaderSources" aria-haspopup="dialog" aria-controls="readerSources" aria-expanded="false" data-en="Evidence and sources">근거와 출처</button></div></div>`);
  // Preserve scholarly/public evidence links; local production destinations are not public evidence.
  html = html.replace(/<a\b([^>]*?)href="([^"]*)"([^>]*)>([^]*?)<\/a>/g, (whole, before, href, after, text) => {
    if (/^(?:https:\/\/|#|\?)/.test(href)) return whole;
    return `<span${before}${after}>${text}</span>`;
  });
  html = html.replace(/&lt;a\b[^]*?href=&quot;([^]*?)&quot;[^]*?&gt;([^]*?)&lt;\/a&gt;/g, (whole, href, text) => /^(?:https:\/\/|#|\?)/.test(href) ? whole : text);
  html = html.replace(/\b(src|poster|data-src-en|data-poster-en)="([^"]+)"/g, (whole, attr, value) => {
    if (value.startsWith("data:")) return whole;
    assert(assets.has(value), `Unapproved media reference: ${value}`);
    return `${attr}="${escape(assets.get(value))}"`;
  }).replace(/url\((['"]?)([^)'"\s]+)\1\)/g, (whole, quote, value) => {
    if (value.startsWith("#") || value.startsWith("data:")) return whole;
    assert(assets.has(value), `Unapproved CSS asset: ${value}`);
    return `url('${assets.get(value)}')`;
  });
  html = html.replace(/<video\b/g, "<video muted");
  html = readerChrome(html, videoUrl);
  html = html.replace("if(english){", "if(english){document.getElementById('reportDownload').href='report-en.pdf';");
  html = html.replace("</script>", `
document.querySelector('.reader-home').href='/geode/?lang='+(english?'en':'ko');
document.querySelectorAll('.reader-languages a').forEach(a=>a.setAttribute('aria-current',a.lang===(english?'en':'ko')?'page':'false'));
const readerToc=document.getElementById('readerScenes'),readerWide=matchMedia('(min-width:1024px)'),readerTocButton=document.getElementById('contentsButton');
document.getElementById('readerSceneCount').textContent=slides.length;
slides.forEach((s,i)=>{const a=document.createElement('a'),number=document.createElement('span'),title=document.createElement('span');a.href='#'+s.id;number.textContent=String(i+1).padStart(2,'0');title.textContent=s.dataset.title; a.append(number,title);a.onclick=e=>{e.preventDefault();jump(s.id);history.replaceState(null,'','#'+s.id);if(!readerWide.matches)readerToc.close();};readerToc.querySelector('nav').append(a);});
function syncReaderPanel(){if(readerToc.open)readerToc.close();if(readerWide.matches&&!renderMode)readerToc.setAttribute('open','');readerTocButton.setAttribute('aria-expanded',String(readerToc.open));resize();}
readerWide.addEventListener('change',syncReaderPanel);syncReaderPanel();
readerTocButton.onclick=()=>{if(!readerWide.matches)readerToc.showModal();readerTocButton.setAttribute('aria-expanded','true');readerToc.querySelector('[aria-current=page]')?.focus();};
document.getElementById('closeReaderScenes').onclick=()=>readerToc.close();readerToc.addEventListener('close',()=>readerTocButton.setAttribute('aria-expanded',String(readerToc.open)));
const readerSources=document.getElementById('readerSources'),readerSourcesButton=document.getElementById('openReaderSources');
function openReaderSources(){if(renderMode||readerSources.open)return;if(readerToc.matches(':modal'))readerToc.close();readerSources.showModal();readerSourcesButton.setAttribute('aria-expanded','true');document.documentElement.classList.add('reader-sources-open');}
readerSourcesButton.onclick=openReaderSources;document.getElementById('closeReaderSources').onclick=()=>readerSources.close();
readerSources.addEventListener('close',()=>{document.documentElement.classList.remove('reader-sources-open');readerSourcesButton.setAttribute('aria-expanded','false');if(location.hash==='#readerSources')history.replaceState(null,'','#'+slides[state.index].id);readerSourcesButton.focus({preventScroll:true});});
readerSources.addEventListener('click',e=>{const r=readerSources.getBoundingClientRect();if(e.target===readerSources&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))readerSources.close();});
readerSources.addEventListener('keydown',e=>{e.stopPropagation();if(e.key!=='Tab')return;const links=readerSources.querySelectorAll('button,a[href]'),first=links[0],last=links[links.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}});
window.addEventListener('hashchange',()=>{if(location.hash==='#readerSources')openReaderSources();});if(location.hash==='#readerSources')openReaderSources();
function updateReaderNavigation(s,k){
 const i=slides.indexOf(s),n=stepCount(s);
 document.querySelector('.counter').textContent=(english?'Scene ':'장면 ')+(i+1)+' / '+slides.length+' · '+(english?'Build ':'단계 ')+k+' / '+n;
 document.getElementById('previous').disabled=i===0&&k===1;
 document.getElementById('next').disabled=i===slides.length-1&&k===n;
 document.querySelectorAll('.reader-languages a').forEach(a=>a.href='?lang='+a.lang+'#'+s.id);
 readerToc.querySelectorAll('a').forEach(a=>a.setAttribute('aria-current',a.hash==='#'+s.id?'page':'false'));
}
const readerSetStep=setStep;setStep=function(s,k){readerSetStep(s,k);if(s.classList.contains('active'))updateReaderNavigation(s,k);};
updateReaderNavigation(slides[state.index],+(slides[state.index].dataset.stepNow||1));
if(!renderMode&&matchMedia('(prefers-reduced-motion:reduce)').matches&&!document.documentElement.classList.contains('motion-paused'))motionButton.click();
</script>`);
  assert(!privatePath.test(html), "Private/local path remains in public HTML");
  assert(!/review-with-music|musicTracks|musicFilm|notesButton|data-note=/i.test(html), "Production-only content remains");
  assert(!/<audio\b/i.test(html), "The report links to the music edition; it does not embed a soundtrack");
  // A source change must not silently remove the report's navigation/build API.
  for (const token of ["window.__film=", 'id="contentsButton"', 'id="overviewButton"', 'id="previous"', 'id="next"']) assert(html.includes(token), `Lost control: ${token}`);
  return html;
}

export function approvedAssets(root, rows, reuseDirectory) {
  assert(Array.isArray(rows) && rows.length > 0, "An explicit approved asset list is required");
  const assetRoot = reuseDirectory ? realpathSync(reuseDirectory) : root;
  const prior = reuseDirectory ? JSON.parse(readFileSync(join(assetRoot, "publication.json"), "utf8")) : null;
  if (prior) assert.equal(prior.schema, "jev-report-publication-v1", "Unsupported asset package receipt");
  const paths = new Set();
  return rows.map((row) => {
    safeRelative(row.source); safeRelative(row.target);
    assert(/\.(?:otf|ttf|woff2|svg|png|jpg|txt|mp4)$/i.test(row.target), "Unsupported asset type");
    assert(!paths.has(row.target), "Duplicate public asset target"); paths.add(row.target);
    if (prior) assert(prior.assets.some(asset => asset.path === row.target && asset.sha256 === row.sha256), `Asset is not approved by the package receipt: ${row.target}`);
    const source = realpathSync(join(assetRoot, reuseDirectory ? row.target : row.source));
    const outside = relative(assetRoot, source).startsWith("..") || isAbsolute(relative(assetRoot, source));
    assert(!outside || row.dereference === true, `External asset alias needs explicit approval: ${row.source}`);
    const bytes = readFileSync(source);
    assert(sha(bytes) === row.sha256, `Asset digest mismatch: ${row.source}`);
    assert(bytes.length < 100 * 1024 * 1024, "Asset exceeds regular Git file limit");
    if (/\.mp4$/i.test(source)) {
      const check = spawnSync("ffprobe", ["-v", "error", "-show_entries", "stream=codec_type", "-of", "json", source], { encoding: "utf8" });
      assert(check.status === 0, "ffprobe is required to verify replay streams");
      assert(!JSON.parse(check.stdout).streams.some((stream) => stream.codec_type === "audio"), "Only verified audio-free replay assets are allowed");
    }
    return { ...row, sourceRef: row.source, source, bytes: bytes.length };
  });
}

export async function freezeReplayFrames(page) {
  for (const video of await page.locator('.stage>.slide.active video').elementHandles()) {
    let src = await video.getAttribute('poster');
    if (!src) {
      await video.evaluate(async element => {
        element.controls = false; element.muted = true; element.pause();
        if (element.readyState < 2) await new Promise((resolve, reject) => {
          const timer = setTimeout(() => reject(Error('Replay first frame did not load')), 15000);
          element.addEventListener('loadeddata', () => { clearTimeout(timer); resolve(); }, { once: true });
          element.addEventListener('error', () => { clearTimeout(timer); reject(Error('Replay decode failed')); }, { once: true });
          element.preload = 'auto'; element.load();
        });
      });
      src = 'data:image/png;base64,' + (await video.screenshot({ type: 'png' })).toString('base64');
    }
    await video.evaluate((element, src) => {
      const still = document.createElement('img'), style = getComputedStyle(element);
      still.src = src; still.alt = element.getAttribute('aria-label') || 'Recorded replay frame';
      still.className = element.className;
      for (const key of ['position', 'top', 'right', 'bottom', 'left', 'display', 'width', 'height', 'margin', 'padding', 'object-fit', 'border', 'border-radius', 'background']) still.style.setProperty(key, style.getPropertyValue(key));
      element.replaceWith(still);
    }, src);
  }
  await page.evaluate(() => Promise.all([...document.querySelectorAll('.stage>.slide.active img')].map(image => image.decode())));
}

async function exportPdfs(out, expectedPages) {
  // Use the existing/bundled browser and PDF packages via NODE_PATH; install nothing.
  const require = createRequire(import.meta.url);
  const { chromium } = require("playwright");
  const { PDFDocument } = require("pdf-lib");
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const editions = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
    await context.route("**/*", (route) => /^(?:file:|data:)/.test(route.request().url()) ? route.continue() : route.abort());
    for (const lang of ["ko", "en"]) {
      console.log(`Exporting ${lang}: ${expectedPages} settled builds`);
      const page = await context.newPage(), errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(pathToFileURL(join(out, "index.html")).href + `?render=1&lang=${lang}`, { waitUntil: "load" });
      await page.emulateMedia({ media: "screen" });
      const inventory = await page.evaluate(async () => {
        await Promise.all([...document.fonts].map((font) => font.load())); await document.fonts.ready;
        return window.__film.pages();
      });
      const localLinks = await page.evaluate(() => [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href')).filter(href => !/^(?:https:\/\/|\/geode\/|#|\?|report-(?:ko|en)\.pdf$)/.test(href)));
      assert.deepEqual(localLinks, [], "Unpublished link restored after language selection");
      assert.equal(inventory.reduce((n, scene) => n + scene.steps, 0), expectedPages, "Unexpected build count");
      const pdf = await PDFDocument.create(), pages = [];
      for (const scene of inventory) for (let step = 1; step <= scene.steps; step++) {
        await page.evaluate(({ id, step }) => {
          window.__film.go(id, step);
          document.querySelectorAll("video").forEach((video) => { video.pause(); video.muted = true; });
          for (const animation of document.getAnimations()) if (Number.isFinite(animation.effect?.getComputedTiming().endTime)) animation.finish();
        }, { id: scene.id, step });
        await freezeReplayFrames(page);
        const bytes = await page.pdf({ width: "1920px", height: "1080px", printBackground: true, preferCSSPageSize: false, margin: { top: "0", bottom: "0", left: "0", right: "0" } });
        const single = await PDFDocument.load(bytes);
        assert.equal(single.getPageCount(), 1, `${lang}/${scene.id}/${step} spans multiple PDF pages`);
        for (const copied of await pdf.copyPages(single, [0])) pdf.addPage(copied);
        pages.push({ scene_id: scene.id, build: step });
        if (pages.length % 20 === 0) console.log(`${lang}: ${pages.length}/${expectedPages} pages`);
      }
      assert.deepEqual(errors, [], "Browser errors during PDF export");
      assert.equal(pdf.getPageCount(), expectedPages);
      const file = `report-${lang}.pdf`, bytes = await pdf.save();
      assert(bytes.length < 100 * 1024 * 1024, "PDF exceeds regular Git file limit");
      writeFileSync(join(out, file), bytes);
      editions.push({ language: lang, file, sha256: sha(bytes), bytes: bytes.length, pages });
      await page.close();
    }
    assert.deepEqual(editions[0].pages, editions[1].pages, "KO/EN build inventories differ");
  } finally { await browser.close(); }
  return editions;
}

export function reusePdfs(directory, sourceSha, expectedPages, assets, html) {
  const receiptBytes = readFileSync(join(directory, "publication.json")), prior = JSON.parse(receiptBytes);
  assert.equal(prior.schema, "jev-report-publication-v1");
  assert.equal(prior.source_sha256, sourceSha, "Reused PDFs need the same approved source");
  const originalGenerator = prior.pdf_generator_sha256 || prior.generator_sha256;
  assert(/^[a-f0-9]{64}$/.test(originalGenerator), "Missing original PDF generator identity");
  const previousHtml = readFileSync(join(directory, "index.html"), "utf8");
  assert.equal(sha(previousHtml), prior.html_sha256, "Previous HTML digest mismatch");
  const slides = value => [...value.matchAll(/<section\b[^]*?<\/section>/g)].map(match => match[0]).filter(section => section.match(/^<section\b[^>]*\bclass="([^"]*)"/)?.[1].split(/\s+/).includes("slide"));
  assert(slides(html).length > 0, "Missing slide inventory");
  assert.deepEqual(slides(html), slides(previousHtml), "PDF reuse cannot change slide content");
  assert.deepEqual(prior.assets, assets, "PDF reuse cannot change approved assets");
  assert.deepEqual(prior.pdfs.map(pdf => pdf.language), ["ko", "en"]);
  assert.deepEqual(prior.pdfs[0].pages, prior.pdfs[1].pages, "Previous build inventories differ");
  assert.equal(slides(html).length, new Set(prior.pdfs[0].pages.map(page => page.scene_id)).size, "Slide and PDF scene inventories differ");
  for (const pdf of prior.pdfs) {
    assert.equal(pdf.file, `report-${pdf.language}.pdf`);
    assert.equal(pdf.pages.length, expectedPages, "Unexpected reused PDF page count");
    assert.equal(new Set(pdf.pages.map(page => `${page.scene_id}:${page.build}`)).size, expectedPages);
    const bytes = readFileSync(join(directory, pdf.file));
    assert.equal(bytes.length, pdf.bytes); assert(bytes.length < 100 * 1024 * 1024);
    assert.equal(sha(bytes), pdf.sha256, "Reused PDF digest mismatch");
  }
  return { pdfs: prior.pdfs, pdf_generator_sha256: originalGenerator, pdf_reused_from_manifest_sha256: sha(receiptBytes) };
}

export async function main(args) {
  const { values } = parseArgs({ args, options: {
    source: { type: "string" }, "source-sha": { type: "string" }, assets: { type: "string" }, out: { type: "string" },
    date: { type: "string" }, "video-url": { type: "string" }, pdf: { type: "boolean", default: false },
    "expected-pages": { type: "string" }, "reuse-pdfs": { type: "string" }, "asset-package": { type: "string" }, release: { type: "boolean", default: false },
  } });
  for (const key of ["source", "source-sha", "assets", "out", "date"]) assert(values[key], `Missing --${key}`);
  const sourcePath = realpathSync(resolve(values.source)), source = readFileSync(sourcePath);
  assert.equal(sha(source), values["source-sha"], "Source changed since approval");
  const out = resolve(values.out), publicRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../public");
  assert(!(values.pdf && values["reuse-pdfs"]), "Choose PDF rendering or verified reuse, not both");
  assert(!(values["asset-package"] && values["reuse-pdfs"]), "PDF reuse already selects its asset package");
  const hasPdfs = values.pdf || Boolean(values["reuse-pdfs"]);
  if (out === publicRoot || out.startsWith(publicRoot + "/")) assert(values.release && hasPdfs, "Public output requires --release and rendered or verified reused PDFs");
  assert(!existsSync(out), "Refuse to overwrite an existing output directory");
  const assetPackage = values["asset-package"] || values["reuse-pdfs"];
  const rows = approvedAssets(dirname(sourcePath), JSON.parse(readFileSync(values.assets, "utf8")), assetPackage && resolve(assetPackage));
  const assets = new Map(rows.map((row) => [row.sourceRef, row.target]));
  assert.equal(assets.size, rows.length, "Duplicate source asset");
  const html = projectPreview(source.toString("utf8"), { date: values.date, assets, videoUrl: values["video-url"] });
  const count = Number(values["expected-pages"]);
  if (hasPdfs) assert(Number.isInteger(count) && count > 0, "PDF output requires --expected-pages from the final audit");
  const assetReceipt = rows.map(({ target, sha256, bytes }) => ({ path: target, sha256, bytes }));
  const reused = values["reuse-pdfs"] ? reusePdfs(resolve(values["reuse-pdfs"]), sha(source), count, assetReceipt, html) : null;
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, "index.html"), html);
  for (const row of rows) { const target = join(out, row.target); mkdirSync(dirname(target), { recursive: true }); copyFileSync(row.source, target); }
  const receipt = {
    schema: "jev-report-publication-v1", status: "prepared-not-published", source_sha256: sha(source), html_sha256: sha(html),
    generator_sha256: sha(readFileSync(fileURLToPath(import.meta.url))), evidence_readme: EVIDENCE + "README.md",
    date: values.date, video_url: values["video-url"] || null, video_sha256: null, report_audio_streams: 0,
    music_publication: "User selected the existing six-track music edition; the report preserves its credits and cover art",
    rights_documentation_verified: false,
    assets: assetReceipt, pdfs: [],
    unverified: ["Final visual review", "Video export identity", "Public URL readback"],
  };
  if (assetPackage) receipt.asset_package_manifest_sha256 = sha(readFileSync(join(resolve(assetPackage), "publication.json")));
  writeFileSync(join(out, "publication.json"), JSON.stringify(receipt, null, 2) + "\n");
  if (values.pdf) receipt.pdfs = await exportPdfs(out, count);
  if (reused) {
    Object.assign(receipt, reused);
    for (const pdf of receipt.pdfs) copyFileSync(join(resolve(values["reuse-pdfs"]), pdf.file), join(out, pdf.file));
  } else if (values.pdf) receipt.pdf_generator_sha256 = receipt.generator_sha256;
  assert.equal(sha(readFileSync(sourcePath)), receipt.source_sha256, "Source changed during export");
  receipt.total_bytes = statSync(join(out, "index.html")).size + rows.reduce((n, row) => n + row.bytes, 0) + receipt.pdfs.reduce((n, pdf) => n + pdf.bytes, 0);
  writeFileSync(join(out, "publication.json"), JSON.stringify(receipt, null, 2) + "\n");
  console.log(JSON.stringify({ status: receipt.status, source_sha256: receipt.source_sha256, pdf_pages: receipt.pdfs.map((pdf) => pdf.pages.length), output: out }));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main(process.argv.slice(2));
