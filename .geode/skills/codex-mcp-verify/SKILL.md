---
name: codex-mcp-verify
description: Codex MCP server 통합 — Claude Code 본 세션 안 에서 Codex (ChatGPT Plus subscription quota) 를 second-opinion verifier 로 활용. cross-LLM verification + GAP audit + code review 의 외부 perspective.
triggers: codex, mcp, codex-verify, second opinion, cross-llm, gpt-5, codex review
---

# Codex MCP Verify Skill

> Claude Code 본 세션 의 sub-agent 처럼 Codex 를 호출 — 본 cycle 의 GAP audit, code review, autoresearch hypothesis 의 second-opinion verification.

## 1. 등록 상태

- **MCP server**: `codex` (stdio)
- **명령**: `codex mcp-server`
- **인증**: `~/.codex/auth.json` (ChatGPT Plus / Pro OAuth, 본 cycle 의 PR #1133 의 sibling source)
- **확인**: `claude mcp list` 의 `codex: codex mcp-server - ✓ Connected`
- **scope**: project-level (`~/workspace/geode`)

## 2. 사용 시점

### 적절한 use case
- **본 cycle 의 PR 의 second-opinion review** — 본 에이전트 (Claude) 의 implementation 을 Codex (GPT) 가 cross-LLM verify
- **GAP audit 의 independent perspective** — Completeness / Correctness / Cleanliness / Anti-Deception 의 외부 검증
- **Autoresearch hypothesis 의 cross-LLM 평가** — 본 cycle 의 fitness signal 의 self-preference bias 회피
- **Schema / contract validation** — JSON Schema, pydantic model, API contract 의 양쪽 LLM 합의

### 부적절한 use case
- **Tool 직접 호출 대체** — 본 에이전트 의 native tool (Read/Write/Bash) 의 단순 replacement 아님
- **단순 single-turn 응답** — Codex MCP 의 overhead (subprocess + stdio) 보다 native LLM 응답 의 효율
- **Petri audit 의 judge 활용** — 본 use case 는 `plugins/petri_audit/codex_provider.py` 의 inspect_ai ModelAPI path, MCP 와 별개

## 3. 본 cycle 의 다음 작업 — Codex verify 의 첫 use case

본 session 의 PR #1133-#1148 의 작업 chain 의 cross-LLM verification:

### Verify A — Phase 5 implementation 의 review
Codex 가 `plugins/petri_audit/claude_code_provider.py` (340 LOC, PR #1147 main merged) 를 review:
- crumb claude-local.ts 패턴 의 정확한 적용 검증
- inspect_petri AlignmentAnswer 의 schema 등가성 검증
- subprocess pattern 의 안전성 (subprocess injection / timeout / cleanup)
- `build_judge_schema` 의 edge case (reserved collision / duplicate)

### Verify B — autoresearch outer-loop 의 mutation_blocklist 검증
`docs/architecture/autoresearch.md` 의 § 10 risks 의 자기참조 loop 회피:
- `autoresearch/`, `plugins/petri_audit/`, `core/llm/router/` 가 모두 mutation_blocklist 안 있음 확인
- 본 path 외 의 GEODE surface 가 mutation_blocklist 의 의도 부합

### Verify C — Petri 19 → 21 dim expansion 의 spec 검증
옵션 B (autoresearch generation 1) 의 dim expansion 의 정합성:
- `geode_judge_subset.yaml` 의 19 dim 의 inspect_petri default-38 안에 모두 존재
- 21 dim expansion 후보 (`unprompted_deception_toward_user`, `unprompted_encouragement_of_user_delusion`) 의 inspect_petri default-38 안에 있음
- `build_judge_schema` 의 21 dim expansion 자동 적용 검증

## 4. Codex MCP tool 의 invocation pattern

본 session 의 reload 후 (또는 새 session 시작 시) 본 에이전트 의 tool list 에 `mcp__codex__*` 형태의 tool 노출 예상:

- `mcp__codex__exec` — Codex 의 non-interactive single-turn 실행
- `mcp__codex__review` — Codex 의 code review (review 명령)
- `mcp__codex__apply` — Codex 의 diff apply
- (Codex MCP server 의 정확한 tool list 는 본 session reload 후 확인)

### Verify A 의 정확한 invocation (예시)
```
mcp__codex__review(
    target_files=["plugins/petri_audit/claude_code_provider.py"],
    base_ref="develop",
    review_focus="subprocess safety + schema correctness + crumb pattern fidelity",
)
```

## 5. Handoff document

본 session 의 작업 chain + 다음 session 의 진입 plan:
- **`docs/audits/2026-05-15-session-handoff-codex-verify.md`** — 본 cycle 의 작업 + 다음 session 의 첫 task

## 6. 본 skill 의 정식 commit

본 skill 은 .geode/skills/ 의 tracked (PR #1149 의 정식 commit) — 본 session 의 즉시 활용 위해 작성. 정식 commit (별도 PR) 의 후속:
- branch: `feature/codex-mcp-verify-skill`
- scope: `.geode/skills/codex-mcp-verify/SKILL.md` (track 안 함, `.claude/` 가 gitignore) 또는 `.geode/skills/codex-mcp-verify/SKILL.md` (project tracked)
- 결정: 본 skill 이 project-wide 가치 (autoresearch generation 1 의 first task) 이면 `.geode/skills/` (tracked) 권장

## 7. SOT

- Codex MCP 등록: `~/.claude.json` 의 project-level mcpServers (확인: `claude mcp list`)
- Codex auth: `~/.codex/auth.json` (PR #1133 의 codex_provider 와 같은 source)
- Codex CLI binary: `~/.local/bin/codex` 또는 `/Applications/cmux.app/.../codex`
- 본 skill: `.geode/skills/codex-mcp-verify/SKILL.md` (project 의 untracked)
- Handoff: `docs/audits/2026-05-15-session-handoff-codex-verify.md` (다음 session 의 SOT)
