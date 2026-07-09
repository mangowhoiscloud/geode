# Custom Skills (Scaffold)

Skills used by Scaffold during GEODE development (`.claude/skills/`). Separate from GEODE runtime's `core/skills/` SkillRegistry.

> `.claude/skills/` is gitignored (scaffold-local); the rows below are the repo-tracked set that ships with a clone. Additional local-only skills (e.g. `model-onboarding`, `codex-mcp-verify`, `smoke-green-loop`) may exist per machine and are intentionally not listed.

| Skill | Triggers | Content |
|-------|----------|---------|
| `geode-workflow` | workflow, scaffold, feature work, provider/model changes, GUI/computer-use, observability, verification | Evidence-first execution scaffold with progressive-disclosure references |
| `prompt-writing` | prompt, system prompt, model-facing text, identity, You are, Fable | GEODE prompt-writing standard: metadata/behavioral clauses, no direct identity assertions |
| `geode-gitflow` | branch, git, pr, merge, commit | Gitflow strategy, PR templates, CI fix loops |
| `geode-changelog` | changelog, release, version, release | CHANGELOG management, SemVer versioning |
| `agent-ops-debugging` | safe default, root cause, contextvar, multi-gap | Agent-ops debugging patterns — Safe Default anti-pattern, multi-gap root cause, ContextVar DI |
| `architecture-patterns` | architecture, layering, pattern, design | Cross-harness architecture patterns reference |
| `karpathy-patterns` | autoresearch, agenthub, ratchet, context budget | 10 autonomous agent design principles (P1-P10) |
| `openclaw-patterns` | gateway, session, binding, lane, plugin | Agent system design patterns (OpenClaw) |
| `frontier-harness-research` | research, gap, frontier, harness, case study | Frontier harness 4-system comparative research process |
| `verification-team` | verification, review, verify, inspect | 5-persona verification (Beck/Karpathy/Steinberger/Cherny + Anti-Deception) |
| `tech-blog-writer` | blog, posting, tech blog | Technical blog writing guide |
| `explore-reason-act` | explore, reason, root cause, read before write | 3-phase explore-reason-act before code modification |
| `anti-deception-checklist` | deception, fake success, regression | Fake success prevention verification checklist |
| `code-review-quality` | quality, SOLID, dead code, resource leak | Python code quality 6-lens review |
| `dependency-review` | dependency, import, layer, circular, lazy | 6-Layer dependency health review |
| `kent-beck-review` | kent beck, simple design, simplify, god object, SRP | Simple Design 4-rule code review |
| `codebase-audit` | audit, dead code, refactor, god object, duplication | Code audit + refactoring workflow (v0.24.0 proven) |
| `geode-serve` | serve, gateway, slack, binding, poller, config.toml | Slack Gateway operations + debugging guide |
| `long-task-watcher` | monitor, tail -F, progress, background, live audit, stdbuf, buffering | Long-running task watching patterns. Covers the Petri × GEODE N7' Monitor timeout case and stable watch patterns (cat-and-grep / stdbuf streaming / polling). |
| `manim-scene-craft` | manim, scene, 영상, 비디오, 1080p60, EN/KO 렌더, GEODE_HERO_LANG | Manim Community Scene 작성 표준 — EN/KO 다국어 lang, Helvetica Neue + Pretendard 폰트 페어링, Anthropic-style 팔레트, layout ratchet + CI 가드. 4 검증 scene (`geode_hero` / `autoresearch_filewalk` / `autoresearch_compare` / `critical_floor`) 의 공통 패턴. |
| `viz-frame-audit` | 노이즈, slop, 프레임 검수, 영상 audit, 글자 깨짐, 패딩 침범, frame extract, naive arrow | 영상 노이즈/slop 검수 워크플로우 — ffmpeg 프레임 추출 + Read 시각 확인 + 4 카테고리 결함 식별 (naive 화살표 / 패딩 침범 / 글자 깨짐 / 프레임 순서). 12+ 사례 카탈로그 (filewalk 7 + hero 7). |
| `docs-link-audit` | broken link, 404, docs link, hyperlink, 링크 점검, 링크 깨짐, audit links, link checker | Docs-site (`site/` Next.js) body / JSX / markdown link audit. `scripts/check_docs_links.py` validates 4 categories (internal /docs / internal /other / anchor / external), build-time copy awareness, and exit-code-based CI guard wiring. Includes PR #1157/#1161 case studies. |
| `baseline-epoch-partition` | baseline epoch, baseline 아카이빙, epoch partition, spec hash, content-addressed, margin_rule namespace, production logic 구분, baseline 하위 서빙 | Content-addressed baseline-archive epoch 분할 — baseline 산출+측정 명세(margin_rule + logic version tag + 4-role model/source + rubric/dim-set + bench + seed-pool identity)를 canonical 해시 → epoch 구분자. spec vs instance 분리, version-tag(소스해시 아님), write-time frozen hash + spec_schema_version, hash+label 병기. hub baseline-하위 epoch 적재(gen-* 미러). |
