import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Cause Decision Tree — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="verification/cause-decision-tree"
      title="Cause Decision Tree"
      titleKo="원인 분류 의사결정 트리"
      summary="When a verification step fails, the 6-type cause classification dispatches the verdict into one of 5 recovery actions. Removes the 'just retry' anti-pattern."
      summaryKo="검증 단계 실패 시 6 가지 cause 분류를 통해 5 가지 복구 행동 중 하나로 dispatch. '일단 retry' 안티패턴 제거."
    >
      <Bi
        ko={
          <>
            <h2>6 cause 분류</h2>
            <pre>{`C1 schema_drift       모델 출력이 스키마와 어긋남
C2 evidence_missing   주장은 했지만 근거가 없음
C3 score_inconsistent G1-G4 통과했으나 점수가 evidence 와 모순
C4 bias_detected      BiasBuster 가 confirmation/recency/anchoring 검출
C5 cross_llm_disagree 다른 프로바이더가 다른 verdict
C6 timeout            응답 시간/토큰 초과`}</pre>

            <h2>5 복구 행동</h2>
            <pre>{`A1 re-prompt          같은 모델, 보강된 prompt 로 재호출
A2 escalate           상위 모델 (Sonnet → Opus) 로 라우팅
A3 cross-check        cross-LLM verifier 호출
A4 abstain            verdict 거부, downstream 에 NaN 전달
A5 fail-fast          전체 cycle abort, 운영자 알림`}</pre>

            <h2>매핑</h2>
            <table>
              <thead>
                <tr><th>cause</th><th>1차 action</th><th>fallback</th></tr>
              </thead>
              <tbody>
                <tr><td>C1 schema_drift</td><td>A1 re-prompt</td><td>A4 abstain</td></tr>
                <tr><td>C2 evidence_missing</td><td>A1 re-prompt</td><td>A4 abstain</td></tr>
                <tr><td>C3 score_inconsistent</td><td>A3 cross-check</td><td>A4 abstain</td></tr>
                <tr><td>C4 bias_detected</td><td>A2 escalate</td><td>A3 cross-check</td></tr>
                <tr><td>C5 cross_llm_disagree</td><td>A2 escalate</td><td>A5 fail-fast</td></tr>
                <tr><td>C6 timeout</td><td>A1 re-prompt</td><td>A5 fail-fast</td></tr>
              </tbody>
            </table>

            <h2>왜 트리인가</h2>
            <p>
              실패를 분류하지 않은 채 'retry' 한 줄로 처리하면 같은 실패가 무한 반복되거나, 비용 시도만 늘어납니다. cause 분류는 어디서 멈춰야 하는지 + 어디로 escalate 해야 하는지를 명시.
            </p>

            <p className="text-[var(--ink-3)] text-sm"><em>참조</em>: `.claude/skills/geode-verification` (Decision Tree 섹션), `core/verification/`.</p>
          </>
        }
        en={
          <>
            <h2>The six causes</h2>
            <pre>{`C1 schema_drift       output does not fit the schema
C2 evidence_missing   claim made without supporting evidence
C3 score_inconsistent passes G1-G4 but score contradicts evidence
C4 bias_detected      BiasBuster found confirmation / recency / anchoring
C5 cross_llm_disagree another provider produced a different verdict
C6 timeout            time or token budget exceeded`}</pre>

            <h2>The five actions</h2>
            <pre>{`A1 re-prompt          retry with the same model and a tightened prompt
A2 escalate           route to a stronger model (Sonnet -> Opus)
A3 cross-check        invoke the cross-LLM verifier
A4 abstain            reject the verdict, propagate NaN downstream
A5 fail-fast          abort the cycle, page the operator`}</pre>

            <h2>The mapping</h2>
            <table>
              <thead>
                <tr><th>cause</th><th>primary action</th><th>fallback</th></tr>
              </thead>
              <tbody>
                <tr><td>C1 schema_drift</td><td>A1 re-prompt</td><td>A4 abstain</td></tr>
                <tr><td>C2 evidence_missing</td><td>A1 re-prompt</td><td>A4 abstain</td></tr>
                <tr><td>C3 score_inconsistent</td><td>A3 cross-check</td><td>A4 abstain</td></tr>
                <tr><td>C4 bias_detected</td><td>A2 escalate</td><td>A3 cross-check</td></tr>
                <tr><td>C5 cross_llm_disagree</td><td>A2 escalate</td><td>A5 fail-fast</td></tr>
                <tr><td>C6 timeout</td><td>A1 re-prompt</td><td>A5 fail-fast</td></tr>
              </tbody>
            </table>

            <h2>Why a tree</h2>
            <p>
              Classifying failures forces an explicit decision about where to stop and where to escalate. A single 'retry' line lets the same failure burn budget forever or hide a real bias.
            </p>

            <p className="text-[var(--ink-3)] text-sm"><em>References</em>: `.claude/skills/geode-verification` (Decision Tree section), `core/verification/`.</p>
          </>
        }
      />
    </DocsShell>
  );
}
