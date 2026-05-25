---
title: DESIGN.md · `/geode/self-improving/petri-bundle/` (Moved SPA)
geode_version: 0.99.63
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.63"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/geode/self-improving/petri-bundle/` (Moved SPA)

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

The inspect_ai SPA log viewer, relocated from `/geode/petri-bundle/` to `/geode/self-improving/petri-bundle/`. **No UI change** — inspect_ai-bundled React SPA stays intact. This doc is a relocation contract, not a design.

## 2. Data sources

Same as before, all relative to new directory:

| Source | Path |
|---|---|
| SPA app shell | `docs/self-improving/petri-bundle/index.html` |
| Task index | `docs/self-improving/petri-bundle/logs/listing.json` |
| Eval archives | `docs/self-improving/petri-bundle/logs/*.eval` |
| SPA assets | `docs/self-improving/petri-bundle/assets/` |
| Seeds catalog | `docs/self-improving/petri-bundle/seeds/listing.json` |
| Per-run seed files | `docs/self-improving/petri-bundle/seeds/<run_id>/*` |

## 3. Move plan (Phase 3 of sprint)

```bash
git mv docs/petri-bundle docs/self-improving/petri-bundle
```

Cascading updates:

| File | Change |
|---|---|
| `.github/workflows/pages.yml` | path filter `docs/petri-bundle/**` → `docs/self-improving/**` |
| `scripts/validate_petri_bundle.py` | hardcoded path → `docs/self-improving/petri-bundle/` |
| `scripts/build_seeds_listing.py` | same |
| `plugins/petri_audit/bundle_sync.py` | `BUNDLE_LOGS_DIR` constant |
| `plugins/seed_generation/bundle_sync.py` | `_bundle_seeds_dir()` |
| `site/src/app/docs/petri/bundle/page.tsx` | `BUNDLE_URL` const `/petri-bundle/` → `/self-improving/petri-bundle/` |
| `site/src/app/docs/petri/seeds/page.tsx` | `RAW_BUNDLE_URL` const update |
| `docs/petri-bundle/README.md` | move to new location, update URL in body |
| Any CHANGELOG mentions of `/petri-bundle/` URL | leave as historical |

## 4. Old URL redirect

Place a single static redirect at `docs/petri-bundle/index.html` (regenerated post-move):

```html
<!doctype html>
<html><head>
<meta http-equiv="refresh" content="0; url=/geode/self-improving/petri-bundle/">
<title>Moved · GEODE petri-bundle</title>
</head><body>
<p>This bundle moved to <a href="/geode/self-improving/petri-bundle/">/geode/self-improving/petri-bundle/</a>.</p>
<script>window.location.replace("/geode/self-improving/petri-bundle/" + window.location.hash);</script>
</body></html>
```

The trailing `window.location.hash` forwards SPA deep-links (e.g. `#/tasks/<id>`).

## 5. Sidebar `.active`

`Petri Audit > SPA log viewer`

But: since inspect_ai SPA replaces `<body>` content with its own React mount, the GEODE sidebar is **not present** on this page. This is acceptable — the SPA is a third-party viewer surface. Visitors return to the hub via browser back, or the SPA's built-in title bar.

## 6. Empty states

The SPA handles its own empty / error states (e.g. "No tasks found in logs/").

## 7. Verification checklist

- [ ] `git mv` preserves history (verify `git log --follow`)
- [ ] Old URL `/geode/petri-bundle/` returns redirect HTML (HEAD 200 + meta-refresh)
- [ ] New URL `/geode/self-improving/petri-bundle/` returns 200 with SPA renders
- [ ] Deep link `/geode/self-improving/petri-bundle/#/tasks/audit_T6LMA3ko` resolves
- [ ] SPA assets (`assets/index.js`, `index.css`) load (no 404 in dev console)
- [ ] `scripts/validate_petri_bundle.py` passes against new path
- [ ] Pages workflow triggers on `docs/self-improving/**` path filter
- [ ] Next.js `site/src/app/docs/petri/bundle/page.tsx` link updates verified
