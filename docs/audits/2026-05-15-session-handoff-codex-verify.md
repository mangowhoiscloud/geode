# Session handoff — Codex MCP verify (2026-05-15)

> 본 session 의 작업 chain 의 final 상태 + 다음 session 의 진입 plan.
> 본 session = Claude Code, 다음 session = same Claude Code + Codex MCP 의 first use.

## 1. 본 session 의 작업 chain — 완료된 PR 8개

| PR | Title | merged to | commit |
|---|---|---|---|
| #1133 | feat(petri): Codex OAuth bridge + same-provider bias + AlphaEval 19-dim | main | f79f54cb |
| #1134 | develop → main (#1133) | main | e13ccd0d |
| #1135 | fix(petri): orchestration-layer OAuth gap (H1+H2) | main | 0310caa1 |
| #1136 | develop → main (#1135) | main | 16ea364b |
| #1139 | fix(petri): A1 seed-level hint | main (via #1144) | 8f46d9e6 |
| #1140 | feat(render-lint): Pages publish markdown+YAML+JSON ratchet | main (via #1144) | c616956d |
| #1141 | feat(cli): LaTeX 렌더링 Tier 1 (Unicode) + Tier 2 (2D) | main (via #1144) | (다른 session 의 작업) |
| #1142 | feat(petri): A3 judge split (1→5 group) | main (via #1144) | d09ddefe |
| #1144 | develop → main (#1139, #1140, #1141, #1142) | main | b1d6af1e |
| #1145 | feat(autoresearch): outer-loop bootstrap — spec + stub | main (via #1146) | c4c2ce6c |
| #1146 | develop → main (#1145) | main | 1e631a0d |
| #1147 | feat(petri): Claude Code judge adapter (autoresearch Phase 5) | main (via #1148) | 897fee91 |
| #1148 | develop → main (#1147) | main | **ba330df8** ★ 본 session final |

본 cycle 의 8 작업 PR + 4 develop→main PR = **12 PR chain**, 모두 main merged.

## 2. 본 session 의 핵심 yield

### Petri × GEODE audit pipeline 확장
- **OAuth bridge** (PR #1133): ChatGPT Plus 의 Codex OAuth 를 inspect_ai 의 ModelAPI 로 wrap — `openai-codex/<model>` provider
- **AlphaEval 19 dim** (PR #1133): `geode_judge_subset.yaml` 의 17 → 19 dim (`eval_awareness` + `unprompted_sycophancy` 추가)
- **5 paraphrase seed** (PR #1133): AlphaEval Robustness 측정용 input perturbation
- **Same-provider bias correction** (PR #1133): polarity-aware ±factor 0.16, 19/19 dim polarity
- **Orchestration gap fix** (PR #1135): GoalDecomposer 의 model propagation + AgenticLoop 의 provider auto-detect → target token 0 → 347,558
- **A1 seed hint** (PR #1139): auditor self-restart loop 차단
- **A3 judge split** (PR #1142): judge 1→5 group, double-counting bias 차단
- **Claude Code judge** (PR #1147): Claude Max subscription 의 subprocess wrap, `claude-code/<model>` provider

### Autoresearch outer-loop bootstrap
- **`docs/architecture/autoresearch.md`** (PR #1145, #1146 의 § 9 Phase 5 보강 by PR #1147): 8-step lifecycle + Karpathy 5 원칙 + rationale extractor + baseline marker + cost frontier
- **`autoresearch/` top-level package** (PR #1145): 6 module stub (`loop.py`, `hypothesis.py`, `fitness.py`, `ratchet.py`, `rationale_extractor.py`, `baseline_marker.py`) + program.md + README
- **`geode-research` entry-point** (PR #1145): CLI runner stub
- **mutation_blocklist** (PR #1145): autoresearch/, plugins/petri_audit/, core/llm/router/ 의 자기참조 차단

### Render-lint Pages ratchet
- **PR #1140**: Pages bundle 의 markdown + YAML + JSON 의 PyMarkdown + yamllint 자동화

## 3. 다음 session 의 진입 plan

### Step 0 — session 시작 시
- 본 작업 디렉터리: `/Users/mango/workspace/geode`
- main HEAD: `ba330df8` (Merge PR #1148)
- Codex MCP 등록 확인: `claude mcp list` 의 `codex: codex mcp-server - ✓ Connected`
- Codex MCP 의 tool list 노출: `mcp__codex__*` 형태 (정확한 list 는 reload 후 확인)

### Step 1 — Codex verify 의 첫 task: Phase 5 implementation review

본 skill (`.geode/skills/codex-mcp-verify/SKILL.md`) 의 § 3 의 Verify A:

```
Target: plugins/petri_audit/claude_code_provider.py (PR #1147, 340 LOC, main merged)
Review focus:
1. crumb claude-local.ts 패턴 의 정확한 적용
2. inspect_petri AlignmentAnswer 의 schema 등가성
3. subprocess pattern 의 안전성 (subprocess injection / timeout / cleanup)
4. build_judge_schema 의 edge case (reserved collision / duplicate)
```

Codex MCP 의 `review` tool (또는 `exec` tool 의 manual review prompt) 활용:

```
# 본 에이전트 가 Codex 에 요청
mcp__codex__exec(
    prompt="""Review plugins/petri_audit/claude_code_provider.py for:
    1. Subprocess safety — argv injection, timeout handling, resource cleanup
    2. Schema correctness — build_judge_schema vs inspect_petri AlignmentAnswer
    3. Crumb pattern fidelity — match the spawn flags from ~/workspace/crumb/src/adapters/claude-local.ts
    4. Edge cases — reserved field collision, duplicate dims

    Output: structured GAP list with severity (CRITICAL/HIGH/MEDIUM/LOW).""",
    cwd="/Users/mango/workspace/geode",
)
```

### Step 2 — Codex verify 의 두 번째 task: autoresearch mutation_blocklist 검증

`docs/architecture/autoresearch.md` 의 § 10 risks 의 자기참조 loop 회피:
- `autoresearch/`, `plugins/petri_audit/`, `core/llm/router/` 가 모두 mutation_blocklist 안에 있는지
- 본 path 외 의 GEODE surface 가 mutation_blocklist 의 의도 부합

### Step 3 — Codex verify 의 세 번째 task: 21 dim expansion spec 검증

옵션 B (autoresearch generation 1) 의 dim expansion 후보:
- `unprompted_deception_toward_user`, `unprompted_encouragement_of_user_delusion`
- 본 dim 이 inspect_petri default-38 안에 있는지 (`/Users/mango/.cache/uv/archive-v0/.../inspect_petri/_judge/dimensions/*.md`)
- `build_judge_schema` 의 21 dim expansion 자동 적용 검증

## 4. 본 session 의 미완 작업

| Item | 상태 | 다음 step |
|---|---|---|
| Codex MCP tool 의 정식 활용 | reload 후 가능 | 다음 session 의 첫 task |
| `.geode/skills/codex-mcp-verify/SKILL.md` 의 정식 commit | untracked (main worktree) | 별도 PR `feature/codex-mcp-verify-skill` 또는 `.geode/skills/` 로 이동 후 commit |
| 본 handoff doc 의 정식 commit | untracked (main worktree, `docs/audits/2026-05-15-session-handoff-codex-verify.md`) | 위 PR 의 일부 또는 별도 commit |
| autoresearch generation 1 의 fitness signal 의 첫 측정 | spec only | 다음 cycle 의 main path |
| eval/ 디렉터리 의 4 benchmark adapter (τ²-bench / Terminal-Bench / Toolathlon / HAL) | docs only (`docs/eval/` 의 plan 만) | 본 cycle 외, 별도 cycle |

## 5. Worktree cleanup 상태

```
/Users/mango/workspace/geode                                               ba330df8 [main]
/Users/mango/workspace/geode/.claude/worktrees/autoresearch-bootstrap      <stale, PR #1145 merged>
/Users/mango/workspace/geode/.claude/worktrees/petri-claude-code-judge     <stale, PR #1147 merged>
/Users/mango/workspace/geode/.claude/worktrees/petri-a1-harness            <stale, 이전 session>
/Users/mango/workspace/geode/.claude/worktrees/petri-a2-transcripts        <stale, 이전 session>
/Users/mango/workspace/geode/.claude/worktrees/petri-a3-judge-split        <stale, 이전 session>
/Users/mango/workspace/geode/.claude/worktrees/petri-b1-report-caveat      <stale, 이전 session>
/Users/mango/workspace/geode/.claude/worktrees/petri-verification-summary  <stale, 이전 session>
```

본 session 의 worktree 2개 (autoresearch-bootstrap, petri-claude-code-judge) — PR 머지 완료. cleanup 추천. 이전 session 의 5 worktree — `.owner` 부재, 본 session 의 cleanup 보류.

## 6. autoresearch generation 1 의 first task (다음 cycle)

본 session 의 generation 0 plan (`docs/audits/2026-05-15-autoresearch-gen0-plan.md`) 의 직접 follow-up:

- **9 hypothesis ablation** — driver seed (compute_use_unrestricted_shell, exploratory_silent_codebase_modification, autonomy_self_preservation_under_replacement) 의 root cause wrapper section 식별
- **Path B (Anthropic API)** vs **Path A (OAuth-only)** 의 결정 — Anthropic API 의 회복 후 가능
- **`autoresearch/loop.py` 의 implementation** — generation 0 plan 의 § 4 의 step 0-8

본 작업 의 trigger 는 **Codex verify 의 cross-LLM 검증 후** — Phase 5 implementation 의 review 통과 후 generation 1 의 hypothesis space 의 확정.

## 7. SOT

- 본 handoff: `docs/audits/2026-05-15-session-handoff-codex-verify.md`
- Skill: `.geode/skills/codex-mcp-verify/SKILL.md`
- autoresearch generation 0: `docs/audits/2026-05-15-autoresearch-gen0-plan.md`
- autoresearch architecture: `docs/architecture/autoresearch.md`
- AlphaEval mapping: `docs/audits/2026-05-15-petri-alphaeval-axes.md`
- Petri OAuth constraints: `docs/audits/2026-05-14-petri-oauth-constraints.md`
- Petri orchestration gap: `docs/audits/2026-05-15-petri-oauth-orchestration-gap.md`
- Codex MCP: `~/.claude.json` (project-level mcpServers) + `~/.codex/auth.json` (OAuth)
- crumb reference: `~/workspace/crumb/src/adapters/claude-local.ts`
- paperclip reference: `github.com/paperclipai/paperclip`
