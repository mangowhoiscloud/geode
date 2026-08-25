# Skill Inventory And Ownership

GEODE publishes both its development scaffold and the skills loaded by the
runtime. Machine-local skills outside this repository are not part of this
inventory.

Three paths have three owners:

- `.geode/skills/` is the GEODE runtime source of truth. `SkillLoader` discovers
  bundled, user-global, and project-local contracts there; wheel and sdist
  artifacts ship the bundled tree.
- `.agents/skills/` is the tracked cross-host development scaffold. Codex
  discovers this path directly. When a same-named runtime skill exists, the
  scaffold stays thin and links to `.geode/skills/<name>/SKILL.md` rather than
  copying its behavior contract.
- `.claude/skills/` is Claude Code's project discovery surface. Every tracked
  development skill is a relative per-skill symlink to `.agents/skills/`, so
  both hosts read identical reviewed bytes.

This follows the open [Agent Skills discovery and `.agents/skills` guidance](https://agentskills.io/client-implementation/adding-skills-support)
and [Claude Code project skill and symlink contract](https://code.claude.com/docs/en/slash-commands#where-skills-live).
The security review and handling contracts are recorded in
[`docs/audits/2026-08-25-skill-transparency-security.md`](audits/2026-08-25-skill-transparency-security.md).

## Development And Meta Skills

| Skill | Triggers | Content |
|-------|----------|---------|
| `agent-anti-pattern` | agent audit, deletion, cleanup, slop | Evidence-first audit scaffold with fail-closed KEEP/SHRINK/DELETE/MEASURE/DEFER verdicts |
| `geo` | GEO, generative search, visibility, citations | Thin repository scaffold that routes implementation and evaluation work to the runtime GEO contract and frozen measurement profile |
| `geode-eval` | evaluation, benchmark, run spec, research question, attempt lineage, trajectory, artifact, MCPMark, tau2, Agent-World | Cross-host evaluation workflow with generated routing, frozen research/reproduction contract, append-only retries, digest-bound analysis, and immutable publication |
| `grilling` | grill, interview, decision tree | Thin repository scaffold for the runtime dependency-aware interview contract and slash integration |
| `geode-workflow` | workflow, scaffold, feature work, provider/model changes, GUI/computer-use, observability, verification | Evidence-first execution scaffold with progressive-disclosure references |
| `stanford-test-time-compute` | test-time compute, inference-time scaling, best-of-N, parallel width, sequential repair, measurement replication, verifier/evaluator, promotion authority, Archon | Stanford CS329A Part 2 grounding with GEODE/Eco²/SIL/Crucible decision-plane and authority boundaries |
| `agent-world-benchmark` | Agent-World, AgentWorld, MCP-Mark, BFCL V4, tau2 comparator, paired runtime, mean_accuracy@8 | Agent-World v1 directional reference plus matched thin-runtime control, replication, comparability, and artifact workflow |
| `prompt-writing` | prompt, system prompt, model-facing text, identity, You are, Fable | GEODE prompt-writing standard: metadata/behavioral clauses, no direct identity assertions |
| `geode-distribution` | uvx, PyPI, GitHub Release, 배포 | Coordinated GitHub Release + PyPI stable promotion |
| `geode-gitflow` | branch, git, pr, merge, commit | Gitflow strategy, PR templates, CI fix loops |
| `geode-changelog` | changelog, release, version, release | CHANGELOG management, post-1.0 patch-first versioning (minors are operator-declared; mis-stamp correction procedure) |
| `geode-code-conventions` | abstraction, naming, module, class, type, schema, test placement, versioning | Measured GEODE convention workflow backed by the canonical architecture, naming, data, site, and compatibility guide |
| `agent-ops-debugging` | safe default, root cause, contextvar, multi-gap | Agent-ops debugging patterns — Safe Default anti-pattern, multi-gap root cause, ContextVar DI |
| `architecture-patterns` | architecture, layering, pattern, design | Cross-harness architecture patterns reference |
| `karpathy-patterns` | autoresearch, agenthub, ratchet, context budget | 10 autonomous agent design principles (P1-P10) |
| `openclaw-patterns` | gateway, session, binding, lane, plugin | Agent system design patterns (OpenClaw) |
| `frontier-harness-research` | research, gap, frontier, harness, case study | Comparative research across Claude Code, Codex, OpenClaw, autoresearch, Prime Agent, and the pinned upstream authority |
| `verification-team` | verification, review, verify, inspect | 5-persona verification (Beck/Karpathy/Steinberger/Cherny + Anti-Deception) |
| `tech-blog-writer` | blog, posting, tech blog | Technical blog writing guide |
| `explore-reason-act` | explore, reason, root cause, read before write | 3-phase explore-reason-act before code modification |
| `anti-deception-checklist` | deception, fake success, regression | Fake success prevention verification checklist |
| `code-review-quality` | quality, SOLID, dead code, resource leak | Python code quality 6-lens review |
| `dependency-review` | dependency, import, layer, circular, lazy | 6-Layer dependency health review |
| `kent-beck-review` | kent beck, simple design, simplify, god object, SRP | Simple Design 4-rule code review |
| `codebase-audit` | audit, dead code, refactor, god object, duplication | Code audit + refactoring workflow (v0.24.0 proven) |
| `geode-serve` | serve, gateway, slack, binding, poller, config.toml | Slack Gateway operations + debugging guide |
| `long-task-watcher` | monitor, wait, progress, background task | Thin development router to the runtime long-task monitoring contract |
| `manim-scene-craft` | manim, scene, 영상, 비디오, 1080p60, EN/KO 렌더, GEODE_HERO_LANG | Manim Community Scene 작성 표준 — EN/KO 다국어 lang, Helvetica Neue + Pretendard 폰트 페어링, Anthropic-style 팔레트, layout ratchet + CI 가드. 4 검증 scene (`geode_hero` / `autoresearch_filewalk` / `autoresearch_compare` / `critical_floor`) 의 공통 패턴. |
| `viz-frame-audit` | 노이즈, slop, 프레임 검수, 영상 audit, 글자 깨짐, 패딩 침범, frame extract, naive arrow | 영상 노이즈/slop 검수 워크플로우 — ffmpeg 프레임 추출 + Read 시각 확인 + 4 카테고리 결함 식별 (naive 화살표 / 패딩 침범 / 글자 깨짐 / 프레임 순서). 12+ 사례 카탈로그 (filewalk 7 + hero 7). |
| `docs-link-audit` | broken link, 404, docs link, hyperlink, 링크 점검, 링크 깨짐, audit links, link checker | Docs-site (`site/` Next.js) body / JSX / markdown link audit. `scripts/check_docs_links.py` validates 4 categories (internal /docs / internal /other / anchor / external), build-time copy awareness, and exit-code-based CI guard wiring. Includes PR #1157/#1161 case studies. |
| `baseline-epoch-partition` | baseline epoch, baseline 아카이빙, epoch partition, spec hash, content-addressed, margin_rule namespace, production logic 구분, baseline 하위 서빙 | Content-addressed baseline-archive epoch 분할 — baseline 산출+측정 명세(margin_rule + logic version tag + 4-role model/source + rubric/dim-set + bench + seed-pool identity)를 canonical 해시 → epoch 구분자. spec vs instance 분리, version-tag(소스해시 아님), write-time frozen hash + spec_schema_version, hash+label 병기. hub baseline-하위 epoch 적재(gen-* 미러). |
| `codex-mcp-verify` | Codex MCP, second opinion, cross-check | Read-only second-opinion protocol with local reproduction and no credential access |
| `model-onboarding` | model, provider, capability, pricing, context | Primary-source and call-site checklist without a duplicated, fast-staling model catalog |
| `scandinavian-design` | Scandinavian, Nordic, monochrome, restrained UI | Evidence-led Scandinavian interface design and visual verification toolkit |
| `smoke-green-loop` | smoke, phase failure, empty artifact, iterative repair | Preserve-diagnose-fix-merge-rebuild loop with live-call approval and anti-selection rules |

The table above is executable inventory: `tests/test_skill_surface_policy.py`
fails when a tracked `.agents` skill is missing from it or lacks its relative
Claude Code alias.

## Runtime Skills

These contracts are loadable by `core/skills/`. Eight are immutable wheel
payload; three operator/repository workflows remain project-only. All remain
reviewable real directories under `.geode/skills/`; same-named development
skills are thin routing scaffolds, not copies.

| Runtime skill | Distribution | Purpose |
|---|---|---|
| `arxiv-digest` | wheel | Bounded arXiv discovery and digest production |
| `deep-researcher` | wheel | Evidence-first bounded or explicitly persistent research |
| `frontier-ui-ux-catalog` | wheel | Frontier UI/UX reference catalog |
| `geo` | wheel | Generative-engine optimization workflow and frozen measurement |
| `geode-context` | wheel | Current repository architecture and package-root context |
| `grilling` | wheel | Dependency-aware interview and decision clarification |
| `long-task-watcher` | wheel | Safe progress monitoring for long-running work |
| `pdf` | wheel | PDF reading, extraction, and production guidance |
| `pr-reviewer` | project-only | Repository-grounded PR review contract |
| `slop-audit` | project-only | Runtime-accessible codebase slop and duplication audit |
| `wiki-sync` | project-only | Explicit wiki synchronization workflow |
