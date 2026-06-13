# GEODE Docs Rewrite — Progress Tracking

Tracks every documentation page across the 8-chapter restructure.

Status legend:
- `✅` = bilingual `<Bi ko en />` complete (production)
- `🟡` = stub created (sidebar + shell live, body TODO)
- `🔴` = source page is single-language, needs `<Bi>` wrap + translation
- `⛔` = blocked / decision pending
- `🆕` = new page to create

Sprint columns:
- **P1** = Phase 1 (foundation: sitemap + shell + stubs)
- **P2** = Phase 2 (translations of 25 existing EN-only)
- **P3** = Phase 3 (new chapter content from wiki/concepts)

---

## Master table

| # | Chapter | Slug | Title KO / EN | Quadrant | KO | EN | Sprint | Source |
|---|---|---|---|---|---|---|---|---|
| 00 · Welcome — Diátaxis Explanation + Tutorial + Reference |
| 00.1 | 00 Welcome | `(index)` | 개요 / Overview | Explanation | 🟡 | ✅ | P1 | existing `docs/page.tsx` |
| 00.2 | 00 Welcome | `quick-start` | 빠른 시작 / Quick Start | Tutorial | ✅ | ✅ | done | existing |
| 00.3 | 00 Welcome | `architecture/overview` | 4-계층 스택 / 4-Layer Stack | Reference | ✅ | ✅ | — | existing (already Bi) |
| 01 · Run GEODE — Diátaxis How-to (user) |
| 01.1 | 01 Run | `run/pick-path` | 경로 선택 / Pick a Path | How-to | ✅ | ✅ | done | README §Path A/B |
| 01.2 | 01 Run | `run/providers` | 프로바이더 설정 / Configure Providers | How-to | ✅ | ✅ | done | wiki llm-models |
| 01.3 | 01 Run | `run/analyze` | 분석 실행 / Run an Analysis | How-to | ✅ | ✅ | done | plugins/game_ip |
| 01.4 | 01 Run | `run/schedule` | 작업 예약 / Schedule Tasks | How-to | ✅ | ✅ | done | wiki scheduler |
| 01.5 | 01 Run | `run/serve` | 데몬으로 실행 / Run as Daemon | How-to | ✅ | ✅ | done | wiki lifecycle-commands |
| 01.6 | 01 Run | `run/messaging` | Slack 등 메신저 연동 / Messaging Integration | How-to | ✅ | ✅ | done | wiki gateway |
| 01.7 | 01 Run | `run/troubleshooting` | 문제 해결 / Troubleshooting | How-to | ✅ | ✅ | done | README §Troubleshooting |
| 02 · System Reference — Diátaxis Reference (구조 미러) |
| 02.1 | 02 Reference | `architecture/agentic-loop` | Agentic 루프 / Agentic Loop | Reference | ✅ | ✅ | done | existing |
| 02.2 | 02 Reference | `architecture/system-index` | 시스템 색인 / System Index | Reference | ✅ | ✅ | done | existing |
| 02.3 | 02 Reference | `runtime/llm/providers` | 프로바이더 / Providers | Reference | ✅ | ✅ | done | existing |
| 02.4 | 02 Reference | `runtime/llm/prompt-system` | 프롬프트 시스템 / Prompt System | Reference | ✅ | ✅ | — | existing (Bi) |
| 02.5 | 02 Reference | `runtime/llm/prompt-caching` | 프롬프트 캐싱 / Prompt Caching | Reference | ✅ | ✅ | done | existing |
| 02.6 | 02 Reference | `runtime/llm/prompt-hashing` | 프롬프트 해싱 / Prompt Hashing | Reference | ✅ | ✅ | done | existing |
| 02.7 | 02 Reference | `runtime/llm/observability` | 관측성 / Observability | Reference | ✅ | ✅ | done | existing |
| 02.8 | 02 Reference | `runtime/tools/protocol` | 도구 프로토콜 / Tool Protocol | Reference | ✅ | ✅ | done | existing |
| 02.9 | 02 Reference | `runtime/tools/mcp` | MCP 서버 / MCP Servers | Reference | ✅ | ✅ | done | existing |
| 02.10 | 02 Reference | `runtime/memory/5-tier` | 5계층 컨텍스트 / 5-Tier Context | Reference | ✅ | ✅ | done | existing |
| 02.11 | 02 Reference | `runtime/memory/vault` | Vault | Reference | ✅ | ✅ | done | existing |
| 02.12 | 02 Reference | `harness/cli` | CLI & Slash | Reference | ✅ | ✅ | done | existing |
| 02.13 | 02 Reference | `harness/hooks` | 훅 시스템 / Hook System | Reference | ✅ | ✅ | done | existing |
| 02.14 | 02 Reference | `harness/lifecycle` | 라이프사이클 / Lifecycle | Reference | ✅ | ✅ | done | existing |
| 02.15 | 02 Reference | `verification/guardrails` | 가드레일 G1-G4 / Guardrails G1-G4 | Reference | ✅ | ✅ | done | existing |
| 02.16 | 02 Reference | `verification/biasbuster` | BiasBuster | Reference | ✅ | ✅ | done | existing |
| 02.17 | 02 Reference | `runtime/computer-use` | 컴퓨터 사용 / Computer Use | Reference | ✅ | ✅ | done | existing |
| 02.18 | 02 Reference | `runtime/scheduler` | 스케줄러 / Scheduler | Reference | ✅ | ✅ | done | existing |
| 02.19 | 02 Reference | `runtime/automation` | 자동화 / Automation | Reference | ✅ | ✅ | done | existing |
| 02.20 | 02 Reference | `runtime/orchestration` | 오케스트레이션 / Orchestration | Reference | ✅ | ✅ | done | existing |
| 02.21 | 02 Reference | `runtime/auth` | 인증 / Auth & OAuth | Reference | ✅ | ✅ | done | existing |
| 02.22 | 02 Reference | `runtime/domains` | 도메인 플러그인 / Domain Plugins | Reference | ✅ | ✅ | done | existing |
| 02.23 | 02 Reference | `runtime/skills` | 스킬 레지스트리 / Skill Registry | Reference | ✅ | ✅ | done | core/skills |
| 02.24 | 02 Reference | `plugins/game-ip` | Game IP 플러그인 / Game IP Plugin | Reference | ✅ | ✅ | done | existing |
| 03 · Build on GEODE — Diátaxis How-to (developer) |
| 03.1 | 03 Build | `build/add-tool` | 도구 추가하기 / Add a Tool | How-to | ✅ | ✅ | done | wiki tool-system |
| 03.2 | 03 Build | `build/add-domain` | 도메인 플러그인 추가 / Add a Domain Plugin | How-to | ✅ | ✅ | done | wiki domain-plugin |
| 03.3 | 03 Build | `build/add-hook` | 훅 핸들러 추가 / Add a Hook Handler | How-to | ✅ | ✅ | done | wiki hook-production-gap |
| 03.4 | 03 Build | `build/testing` | 변경사항 테스트 / Test Your Changes | How-to | ✅ | ✅ | done | CLAUDE.md Quality Gates |
| 04 · Operations — Diátaxis How-to (operator) |
| 04.1 | 04 Ops | `ops/long-running` | 장기 실행 안전 / Long-running Safety | How-to | ✅ | ✅ | done | wiki long-running-safety |
| 04.2 | 04 Ops | `ops/cost` | 비용 모니터링 / Cost Monitoring | How-to | ✅ | ✅ | done | wiki context-guard |
| 04.3 | 04 Ops | `ops/oauth` | OAuth 토큰 관리 / OAuth Token Rotation | How-to | ✅ | ✅ | done | wiki oauth-policy |
| 04.4 | 04 Ops | `ops/observability` | 관측성 / Observability | How-to | ✅ | ✅ | done | wiki petri-alignment-audit + hooks |
| 05 · Petri Audit — alignment audit (NEW chapter) |
| 05.1 | 05 Petri | `petri/overview` | Petri 통합 / Petri × GEODE Integration | Explanation | ✅ | ✅ | done | wiki petri-alignment-audit |
| 05.2 | 05 Petri | `petri/run` | Audit 실행 / Run an Audit | How-to | ✅ | ✅ | done | plugins/petri_audit cli_audit.py |
| 05.3 | 05 Petri | `petri/judge-dimensions` | 38 Judge 차원 / 38 Judge Dimensions | Reference | ✅ | ✅ | done | plugins/petri_audit/judge_dims |
| 05.4 | 05 Petri | `petri/bundle` | Audit Bundle 뷰어 / Audit Bundle Viewer | Reference | ✅ | ✅ | done | external link `/geode/petri-bundle/` |
| 06 · Explanation — Diátaxis Explanation (의사결정) |
| 06.1 | 06 Why | `explanation/self-hosting` | 왜 self-hosting인가 / Why a Self-Hosting Harness | Explanation | ✅ | ✅ | done | portfolio thesis + wiki architecture |
| 06.2 | 06 Why | `explanation/ratchet` | 왜 ratchet 규율인가 / Why Ratchet Discipline | Explanation | ✅ | ✅ | done | karpathy-patterns skill |
| 06.3 | 06 Why | `explanation/4-layer` | 왜 4-계층인가 / Why 4 Layers | Explanation | ✅ | ✅ | done | wiki architecture |
| 06.4 | 06 Why | `explanation/solo` | 왜 단독 개발인가 / Why a Solo Author | Explanation | ✅ | ✅ | done | portfolio + wiki scaffold-production |
| 99 · Reference — secondary indexes |
| 99.1 | 99 Reference | `reference/changelog` | 변경 이력 / Changelog | Reference | ✅ | ✅ | done | existing |
| 99.2 | 99 Reference | `reference/frontier-comparison` | 프론티어 비교 / Frontier Comparison | Reference | ✅ | ✅ | done | existing |
| 99.3 | 99 Reference | `reference/sot-metrics` | 메트릭 SOT / System Metrics | Reference | ✅ | ✅ | done | `site/src/data/geode/sot.ts` |

---

## Summary (2026-05-12 후속 sprint 갱신)

| Status | Count |
|---|---:|
| ✅ Bilingual production | 58 |
| 🔴 outstanding | 0 |
| **Total** | **58** |

### 2026-05-19 Phase 1-3 갱신

- **Phase 1**: SOT 재동기화 (v0.99.13 → v0.99.16, 329 → 352 modules, 4897 → 4910 tests). 하드코딩 서브시스템 카운트 + sitemap summary 정정. G4 명칭 Coherence → Consistency.
- **Phase 2**: 12 페이지 신설.
    - 05 Capabilities (4): `capabilities/outer-loop`, `capabilities/seed-pipeline`, `capabilities/autoresearch`, `capabilities/co-scientist`.
    - 03 Runtime (1): `runtime/ui/cli-latex`.
    - 04 Harness (1): `harness/serve-gateway`.
    - 06 Verification (3): `verification/biasbuster`, `verification/cross-llm`, `verification/cause-decision-tree`.
    - 08 Operations (2): `ops/release-pypi-lifecycle`, `ops/backlog-dispose`.
    - 99 References (1): `reference/petri-bundle-isolation`.
- **Phase 3**: orphan 페이지 `runtime/memory/5-tier` 재등록. 실제 중복 slug 0건 (이전 audit 의 placement cross-reference 를 dup 로 오인했음).

### 후속 sprint 변경

- **03 Build 챕터 제거** — 4 페이지(`build/add-tool`·`build/add-domain`·`build/add-hook`·`build/testing`). 이전 PR 빌드 로그엔 53 routes로 보였으나 deploy commit에 build/* 파일이 누락돼 실제 라이브에서 404. 사용자 결정으로 챕터 자체를 제외.
- **02 System Reference (24 페이지) → 7 챕터로 분할**: 02 Architecture · 03 LLM Pipeline · 04 Tools and Memory · 05 Harness · 06 Capabilities · 07 Verification · 08 Plugins.
- **Vault 페이지 제거** — `runtime/memory/vault` 는 wiki에서 관리. site/docs에선 5-tier Context만 유지.
- **References 챕터 확장** — 99 References에 신규 `reference/external-references` 추가. Frontier 시스템 (Claude Code·OpenClaw·Hermes·autoresearch 등), Diátaxis 표준, Petri/inspect_ai, mango-wiki 내부 자산, Karpathy autoresearch의 5 reusable pattern 인용.

`<Bi>` wrap audit: 49/49 pages bilingual. 49 routes prerender. 신규 페이지 본문 깊이 보강은 wiki/concepts (33 narrative) 기반으로 추후 sprint.

## Sprint owners

| Sprint | Scope | Pages |
|---|---|---:|
| **P1 (this turn)** | sitemap.ts + DocsShell + 23 new stubs + 25 NO-BI shell-conversion | 51 (foundation) |
| **P2** | 25 page Korean translations | 25 |
| **P3** | 23 new page content from wiki/concepts | 23 |

## Notes

- `existing` 페이지: 현재 `<a href="/geode/docs/...">` raw anchors 사용 — basePath 변경 후에도 동작 ([Sprint 1.5 분석](../README.md))
- `wiki source` 컬럼은 `~/workspace/mango-wiki/vault/projects/geode/concepts/geode-*.md` 파일 가리킴
- Petri 외부 링크 `https://mangowhoiscloud.github.io/geode/petri-bundle/` — site/public/petri-bundle/ 는 사용자가 별도 publish 예정
- 모든 페이지 `quadrant` prop을 사이드바 chip + 페이지 상단 chip으로 렌더
- 메트릭 (v, 모듈, 테스트, 릴리스 등)은 SOT (`site/src/data/geode/sot.ts`) import만 — 페이지 본문에 하드코딩 0개 목표
