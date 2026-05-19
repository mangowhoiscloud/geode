/**
 * GEODE Single Source of Truth — site-wide metrics.
 *
 * Auto-synced from the GEODE repo via `npm run sync-stats`.
 * Do not edit manually. Edit the GEODE repo and re-run sync.
 *
 * Last sync: 2026-05-19
 */

export const GEODE_SOT = {
  version: "0.99.17",
  modules: {
    core: 305,
    plugins: 47,
    total: 352,
  },
  tests: {
    standard: 4910,
    live: 24,
    total: 4934,
  },
  releases: 160,
  since: "2026-02",
  syncedAt: "2026-05-19",
} as const;

export const GEODE_CUMULATIVE_KO =
  `v${GEODE_SOT.version} · ${GEODE_SOT.modules.total} 모듈 · ` +
  `${GEODE_SOT.tests.standard.toLocaleString()} 테스트 · ` +
  `${GEODE_SOT.releases} 릴리스 · 단독 개발 · since ${GEODE_SOT.since}`;

export const GEODE_CUMULATIVE_EN =
  `v${GEODE_SOT.version} · ${GEODE_SOT.modules.total} modules · ` +
  `${GEODE_SOT.tests.standard.toLocaleString()} tests · ` +
  `${GEODE_SOT.releases} releases · solo · since ${GEODE_SOT.since}`;
