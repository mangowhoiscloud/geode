/**
 * GEODE Single Source of Truth — site-wide metrics.
 *
 * Auto-synced from the GEODE repo via `npm run sync-stats`.
 * Do not edit manually. Edit the GEODE repo and re-run sync.
 *
 * Last sync: 2026-05-12
 */

export const GEODE_SOT = {
  version: "0.95.0",
  modules: {
    core: 314,
    plugins: 42,
    total: 356,
  },
  tests: {
    standard: 4608,
    live: 24,
    total: 4632,
  },
  releases: 134,
  since: "2026-02",
  syncedAt: "2026-05-12",
} as const;

export const GEODE_CUMULATIVE_KO =
  `v${GEODE_SOT.version} · ${GEODE_SOT.modules.total} 모듈 · ` +
  `${GEODE_SOT.tests.standard.toLocaleString()} 테스트 · ` +
  `${GEODE_SOT.releases} 릴리스 · 단독 개발 · since ${GEODE_SOT.since}`;

export const GEODE_CUMULATIVE_EN =
  `v${GEODE_SOT.version} · ${GEODE_SOT.modules.total} modules · ` +
  `${GEODE_SOT.tests.standard.toLocaleString()} tests · ` +
  `${GEODE_SOT.releases} releases · solo · since ${GEODE_SOT.since}`;
