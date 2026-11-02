// Where an old GitHub Pages address of GEODE now lives.
//
// Frozen copy of the URL rules in mangowhois-site dabd16825da75537b39fbcfe94905b3878e04852
// (src/lib/research.js: researchRedirect, hubPath, hubRedirect; src/lib/geode.js: GEODE_MEDIA,
// geodeMedia), which owns the canonical addresses. GitHub Pages serves only redirects, so these
// rules change only if a canonical address moves again. Used by scripts/build_pages_redirects.mjs
// (one stub per frozen path) and by 404.html (any other path).
export const SITE = 'https://mangowhois.ai';
export const GEODE_URL = SITE + '/products/geode';
export const TECH = 'https://tech.mangowhois.ai';
export const HOSTS = new Set(['mangowhois.ai', 'tech.mangowhois.ai', 'github.com']);
const PAGES = 'https://mangowhoiscloud.github.io';

const RESEARCH = [
  { id: 'technical', path: '/geode/', source: 'research/geode/' },
  { id: 'jev', path: '/jev/offloading/', source: 'research/jev-system1-offloading/' },
  { id: 'jevdb', path: '/jev/jevdb/', source: 'research/jevdb/' },
  { id: 'index', path: '/', source: 'research/' },
];

function researchRedirect(input) {
  const url = new URL(input, 'https://mangowhois.ai');
  if (!['mangowhois.ai', 'mangowhoiscloud.github.io', 'tech.mangowhois.ai'].includes(url.hostname)) return null;
  const english = url.pathname.startsWith('/en/');
  const path = url.pathname.replace(/^\/en(?=\/)/, '').replace(/^\/(?:products\/)?geode\//, '/').replace(/^\/resaerch\//, '/research/').replace(/\/index\.html$/, '/').replace(/\/?$/, '/');
  const entry = RESEARCH.find((item) => `/${item.source}` === path);
  if (!entry) return null;
  if (english && !['ko', 'en'].includes(url.searchParams.get('lang'))) url.searchParams.set('lang', 'en');
  return TECH + entry.path + url.search + url.hash;
}

const HUB = '/self-improving/';
const HUB_FIXED = new Set(['phase-log', 'active', 'runs']);

function hubPath(rest) {
  const parts = rest.split('/');
  if (parts[0] === 'petri-bundle') return ['audits', ...parts.slice(1)].join('/');
  if (parts[0] !== 'seed-generation' || parts.length < 2 || parts[1] === '') return rest;
  if (parts[1] === 'bundle') return hubPath(['seed-generation', 'phase-log', ...parts.slice(2)].join('/'));
  if (parts[1] === 'phase-log' && (parts[2] === 'assets' || (parts[2] === 'robots.txt' && parts.length === 3))) return ['audits', ...parts.slice(2)].join('/');
  if (HUB_FIXED.has(parts[1]) || parts[1] === 'index.html') return rest;
  const run = parts.slice(2);
  if (run[0] === 'agent') run[0] = 'agents';
  return ['seed-generation', 'runs', parts[1], ...run].join('/');
}

const HUB_RETIRED_AT = 'https://github.com/mangowhoiscloud/geode/blob/10f41ebe2f01718cc92af40153c7deef7b62b4bf/docs/self-improving/';
const HUB_RETIRED = {
  'audits/README.md': 'petri-bundle/README.md',
  ...Object.fromEntries(['baseline-schema-history', 'campaign-procedure', 'campaign-quick-start', 'cycle-input-pool', 'held-out-bench', 'loop-overview'].map((name) => [`${name}.md`, `${name}.md`])),
};

function hubRedirect(input) {
  const url = new URL(input, 'https://mangowhois.ai');
  if (!['mangowhois.ai', 'mangowhoiscloud.github.io', 'tech.mangowhois.ai'].includes(url.hostname)) return null;
  const target = (canonical) => (HUB_RETIRED[canonical] ? HUB_RETIRED_AT + HUB_RETIRED[canonical] : TECH + HUB + canonical + url.search + url.hash);
  const legacy = url.pathname.match(/^\/(?:en\/)?(?:products\/)?geode\/(self-improving\/|petri-bundle\/)(.*)$/);
  if (legacy) return target(hubPath(legacy[1] === 'petri-bundle/' ? `petri-bundle/${legacy[2]}` : legacy[2]));
  if (url.hostname !== 'tech.mangowhois.ai' || !url.pathname.startsWith(HUB)) return null;
  const rest = url.pathname.slice(HUB.length);
  const canonical = hubPath(rest);
  return canonical === rest && !HUB_RETIRED[rest] ? null : target(canonical);
}

const GEODE_MEDIA = {
  '/report.pdf': `${TECH}/geode/report/ko.pdf`,
  '/report-en.pdf': `${TECH}/geode/report/en.pdf`,
  '/resaerch/jev-system1-offloading/report-ko.pdf': `${TECH}/jev/system-1-offloading/ko.pdf`,
  '/resaerch/jev-system1-offloading/report-en.pdf': `${TECH}/jev/system-1-offloading/en.pdf`,
  '/resaerch/jev-system1-offloading/assets/': `${TECH}/resaerch/jev-system1-offloading/assets/`,
};

function geodeMedia(path) {
  if (Object.hasOwn(GEODE_MEDIA, path) && !path.endsWith('/')) return GEODE_MEDIA[path];
  const prefix = Object.keys(GEODE_MEDIA).find((key) => key.endsWith('/') && path.startsWith(key) && path.length > key.length);
  return prefix ? GEODE_MEDIA[prefix] + path.slice(prefix.length) : null;
}

// An old Pages address (path below /geode/, with its query and fragment) -> its canonical URL:
// the experiment hub, a research reader, frozen media on R2, else the same path in the product.
export function pagesRedirect(pathname, search = '', hash = '') {
  if (pathname === '/geode') pathname = '/geode/';
  if (!pathname.startsWith('/geode/')) return GEODE_URL + '/';
  const href = PAGES + pathname + search + hash;
  const rest = pathname.slice('/geode'.length);
  const media = geodeMedia(rest);
  return hubRedirect(href) || researchRedirect(href) || (media ? media + search + hash : null) || GEODE_URL + rest + search + hash;
}
