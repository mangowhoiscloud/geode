import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Co-Scientist Cycle — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="capabilities/co-scientist"
      title="Co-Scientist Cycle"
      titleKo="Co-Scientist 사이클"
      summary="A 6-phase generation cycle codified as a Claude Code skill. Borrows the co-scientist 'easy restart' framing while admitting the upstream impl never delivered usable resume."
      summaryKo="6-phase generation 사이클을 Claude Code 스킬로 구현. co-scientist 논문의 'easy restart' 프레이밍을 차용하되 upstream impl 의 미완성 resume 한계를 명시."
    >
      <Bi
        ko={
          <>
            <h2>왜 cycle skill 인가</h2>
            <p>
              co-scientist 논문은 "easy restarts in case of any failure" 를 한 문장으로 언급하지만 reference impl (Swarms) 의 save-state 는 TODO 로 남아 있습니다. 그래서 GEODE 는 cycle 의 명시적 6-phase 분리를 통해 어디서 끊겨도 다음 phase 부터 재개할 수 있도록 합니다.
            </p>

            <h2>6 Phase + skill 트리거</h2>
            <pre>{`A Allocation     worktree + .owner + Backlog → In Progress
B Implement      P1-P7 prevention checklist, ruff/mypy/pytest
C Verify         Codex MCP cross-LLM review (CRITICAL/HIGH 자동 fix)
D PR & CI        HEREDOC PR body, gh pr checks --watch
E Merge          develop ← feature, develop → main backmerge
F Optional       meta-reflection 7-그룹 + P1-P7 회고`}</pre>

            <p>
              `.claude/skills/seed-pipeline-cycle` 스킬 이 위 6 phase 를 trigger 키워드 (`seed-pipeline`, `sprint`, `cycle`, `S2`, `S3`, …) 로 자동 호출합니다.
            </p>

            <h2>Resume 의 경계</h2>
            <p>
              Phase A-D 중간 실패는 worktree 보존 + `.owner` 로 복구. Phase E 머지 실패는 develop backmerge 가 안전망. Phase F 는 optional 이므로 skip 가능. SessionCheckpoint resume (Phase ζ ADR) 은 inner loop credentials rollover 에만 적용, outer cycle 은 phase boundary 가 곧 checkpoint.
            </p>

            <p className="text-white/40 text-sm"><em>참조</em>: `.claude/skills/seed-pipeline-cycle/`, `docs/architecture/outer-loop-resume-decision.md`, Session 63 handoff.</p>
          </>
        }
        en={
          <>
            <h2>Why a cycle skill</h2>
            <p>
              The co-scientist paper mentions "easy restarts in case of any failure" in one sentence but the reference Swarms impl leaves save-state as a TODO. GEODE codifies the cycle into six explicit phases so a failure at any step resumes from the next phase rather than from scratch.
            </p>

            <h2>The six phases + skill trigger</h2>
            <pre>{`A Allocation     worktree + .owner + backlog move
B Implement      apply P1-P7 prevention checklist, ruff/mypy/pytest
C Verify         Codex MCP cross-LLM review (auto-fix CRITICAL/HIGH)
D PR & CI        HEREDOC PR body, gh pr checks --watch
E Merge          develop <- feature, develop -> main backmerge
F Optional       7-group meta-reflection + P1-P7 retro`}</pre>

            <p>
              The `.claude/skills/seed-pipeline-cycle` skill dispatches each phase when the prompt contains trigger keywords (`seed-pipeline`, `sprint`, `cycle`, `S2`, `S3`, ...).
            </p>

            <h2>Where resume actually works</h2>
            <p>
              A failure in Phases A through D is recovered by preserving the worktree and its `.owner` file. A failed merge in Phase E is caught by the develop backmerge safety net. Phase F is optional. The SessionCheckpoint resume from the Phase ζ ADR applies to the inner-loop credential rollover only. For the outer cycle, the phase boundary is the checkpoint.
            </p>

            <p className="text-white/40 text-sm"><em>References</em>: `.claude/skills/seed-pipeline-cycle/`, `docs/architecture/outer-loop-resume-decision.md`, Session 63 handoff.</p>
          </>
        }
      />
    </DocsShell>
  );
}
