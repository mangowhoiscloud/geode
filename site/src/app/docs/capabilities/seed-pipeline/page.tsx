import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Seed Pipeline — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="capabilities/seed-pipeline"
      title="Seed Pipeline"
      titleKo="Seed 파이프라인"
      summary="Plugin that grows the Petri seed corpus from scratch each generation. Picker → orchestrator → manifest → cost preview, with a 6-phase cycle scaffold."
      summaryKo="매 generation 마다 Petri seed 코퍼스를 자가 생성하는 플러그인. picker → orchestrator → manifest → cost preview 의 파이프라인 + 6-phase cycle scaffold."
    >
      <Bi
        ko={
          <>
            <h2>구성</h2>
            <p>
              `plugins/seed_pipeline/` 가 자기개선 루프 (autoresearch) 의 상위 generation 마다 새로운 Petri seed 묶음을 생성합니다. 입력은 직전 generation 의 transcript + audit 결과. 출력은 다음 generation 의 시드 파일.
            </p>
            <pre>{`plugins/seed_pipeline/
├── picker.py          # auditor 가 다음 raise 할 시나리오 선택
├── orchestrator.py    # picker → agents → manifest 의 graph 실행
├── agents/            # generation/critique/refine sub-agents
├── manifest.py        # seed_file × dimension × budget manifest
├── cost_preview.py    # 실행 전 비용 추정
├── pre_flight.py      # subscription / credential / quota 점검
└── auth_coverage.py   # 모델 역할별 OAuth/key 가용성 audit`}</pre>

            <h2>6-Phase Cycle</h2>
            <p>
              Session 63 의 7 PR (S0/S1/S2/S2-wire/S2-fix/cycle-skill) 로 안착한 워크플로우. `.claude/skills/seed-pipeline-cycle` 스킬 이 다음 단계를 자동화합니다.
            </p>
            <ol>
              <li><strong>A — Allocation</strong>: worktree + .owner + Backlog → In Progress</li>
              <li><strong>B — Implement</strong>: P1-P7 prevention checklist 적용</li>
              <li><strong>C — Verify</strong>: ruff/mypy/pytest + Codex MCP cross-LLM review</li>
              <li><strong>D — PR &amp; CI</strong>: HEREDOC PR body, CI 5/5 watch</li>
              <li><strong>E — Merge</strong>: develop → main backmerge</li>
              <li><strong>F — Optional review</strong>: meta-reflection 7 그룹 + P1-P7 회고</li>
            </ol>

            <h2>다음 단계</h2>
            <p>
              13 PR 남음 (S2.5–S12 + S6.5-wire). 자세한 상태는 `project_session63_handoff` memory entry + cycle skill 의 trigger keywords.
            </p>

            <p className="text-[var(--ink-3)] text-sm"><em>참조</em>: `plugins/seed_pipeline/`, `.claude/skills/seed-pipeline-cycle/`, Session 63 PR #1272–#1277.</p>
          </>
        }
        en={
          <>
            <h2>Shape</h2>
            <p>
              `plugins/seed_pipeline/` regenerates the Petri seed corpus once per autoresearch generation. Input is the prior generation's transcripts and audit verdicts. Output is the next generation's seed files.
            </p>
            <pre>{`plugins/seed_pipeline/
├── picker.py          # selects what the auditor should raise next
├── orchestrator.py    # runs picker → agents → manifest graph
├── agents/            # generation / critique / refine sub-agents
├── manifest.py        # seed_file x dimension x budget manifest
├── cost_preview.py    # pre-run cost estimate
├── pre_flight.py      # subscription / credential / quota checks
└── auth_coverage.py   # OAuth/key availability audit per model role`}</pre>

            <h2>6-Phase Cycle</h2>
            <p>
              The cycle scaffold landed across Session 63's seven PRs (S0, S1, S2, S2-wire, S2-fix, cycle-skill). The `.claude/skills/seed-pipeline-cycle` skill automates each phase.
            </p>
            <ol>
              <li><strong>A — Allocation</strong>: worktree + .owner + backlog move</li>
              <li><strong>B — Implement</strong>: apply P1-P7 prevention checklist</li>
              <li><strong>C — Verify</strong>: ruff/mypy/pytest + Codex MCP cross-LLM review</li>
              <li><strong>D — PR &amp; CI</strong>: HEREDOC PR body, watch CI 5/5</li>
              <li><strong>E — Merge</strong>: develop → main backmerge</li>
              <li><strong>F — Optional review</strong>: 7-group meta-reflection + P1-P7 retro</li>
            </ol>

            <h2>What is left</h2>
            <p>
              Thirteen PRs remain (S2.5 through S12 plus S6.5-wire). Status lives in the `project_session63_handoff` memory entry and the cycle skill trigger keywords.
            </p>

            <p className="text-[var(--ink-3)] text-sm"><em>References</em>: `plugins/seed_pipeline/`, `.claude/skills/seed-pipeline-cycle/`, Session 63 PRs #1272-#1277.</p>
          </>
        }
      />
    </DocsShell>
  );
}
