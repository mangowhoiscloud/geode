// Resolve what a verification script should point at.
//
// The primary use of these tools is a page you are building: pass a URL, most
// often a route on a local dev server, and the script inspects it as it stands.
// Nothing else is required — no config, no repo layout.
//
//   node scripts/lines.js http://localhost:3000/pricing
//
// The eval harness in this repo also refers to its demo pages by id, where the
// URL and an override stylesheet come from demos/sites.json. Passing an id
// resolves to that entry and injects its theme.css before measuring.
//
//   node scripts/lines.js craigslist

const fs = require('fs');
const path = require('path');

// Walk up looking for the eval harness rather than assuming a fixed depth, so
// the scripts work wherever the skill folder is copied to. An installed skill
// has no demos/ above it, which is the correct outcome: URL mode only.
function repoRoot(from = __dirname) {
  let dir = from;
  for (let i = 0; i < 6; i++) {
    if (fs.existsSync(path.join(dir, 'demos', 'sites.json'))) return dir;
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  return null;
}

const ROOT = repoRoot();

function looksLikeUrl(arg) {
  return /^https?:\/\//i.test(arg) || /^localhost([:/]|$)/i.test(arg);
}

function resolve(arg) {
  if (!arg) return null;

  if (looksLikeUrl(arg)) {
    const url = /^https?:\/\//i.test(arg) ? arg : `http://${arg}`;
    return { url, name: url.replace(/^https?:\/\//, ''), theme: '', shared: '' };
  }

  if (!ROOT) return null;
  const sitesPath = path.join(ROOT, 'demos', 'sites.json');
  if (!fs.existsSync(sitesPath)) return null;

  const site = JSON.parse(fs.readFileSync(sitesPath, 'utf8')).find(
    (s) => s.id === arg,
  );
  if (!site) return null;

  const read = (p) => (fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : '');
  return {
    url: site.url,
    name: site.name,
    id: site.id,
    dir: path.join(ROOT, 'demos', site.id),
    theme: read(path.join(ROOT, 'demos', site.id, 'theme.css')),
    shared: read(path.join(ROOT, 'demos', 'shared.css')),
    scrollY: site.scrollY,
  };
}

// Exit with a usage message rather than a stack trace, since the most common
// mistake is passing an id that does not exist rather than a malformed URL.
function resolveOrExit(arg, usage) {
  const target = resolve(arg);
  if (target) return target;
  console.error(usage);
  if (arg) {
    console.error(
      `\n"${arg}" is neither a URL nor an id in demos/sites.json.` +
        `\nPass a URL to inspect any page, for example http://localhost:3000/.`,
    );
  }
  process.exit(1);
}

// Report the one line that matters. Pointing a tool at a dev server that is not
// running is the most common mistake, and a Playwright stack trace buries it.
function fail(err) {
  const message = String(err && err.message ? err.message : err);
  const first = message.split('\n')[0];
  if (/ERR_CONNECTION_REFUSED|ECONNREFUSED/.test(message)) {
    console.error(`Could not reach that URL — is the dev server running?\n${first}`);
  } else {
    console.error(first);
  }
  process.exit(1);
}

module.exports = { resolve, resolveOrExit, fail, repoRoot };
