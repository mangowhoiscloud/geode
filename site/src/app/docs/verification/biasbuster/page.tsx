import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "BiasBuster — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="verification/biasbuster"
      title="BiasBuster"
      titleKo="BiasBuster"
      summary="Bias-detection layer on top of G1-G4. Flags Confirmation, Recency, and Anchoring patterns in LLM verdicts before they propagate."
      summaryKo="G1-G4 위에 얹는 편향 탐지 계층. Confirmation, Recency, Anchoring 패턴을 LLM 판정에서 검출하여 전파를 차단."
    >
      <Bi
        ko={
          <>
            <h2>왜 G1-G4 만으로 부족한가</h2>
            <p>
              Schema / Range / Grounding / Consistency 4 게이트는 구조적 결함만 잡습니다. 그러나 LLM 의 출력은 통과하더라도 다음 3 가지 편향이 자주 섞여 있습니다.
            </p>
            <ul>
              <li><strong>Confirmation</strong>. 가설을 뒷받침하는 근거만 인용</li>
              <li><strong>Recency</strong>. 가장 최근 입력에 점수가 과대 반영</li>
              <li><strong>Anchoring</strong>. 첫 평가 (e.g. 직전 analyst) 가 다음 evaluator 를 끌고 감</li>
            </ul>

            <h2>탐지 + 차단</h2>
            <p>
              BiasBuster 는 verdict 의 evidence 분포, 시점, 직전 verdict 와의 상관을 분석하여 위 3 가지 편향의 fingerprint 를 찾습니다. 검출 시 cause classification (Decision Tree 의 6 cause 중 하나) 를 부여하고, evaluator 에 re-prompt 또는 abstain 을 강제.
            </p>

            <h2>관련 코드</h2>
            <ul>
              <li><code>core/verification/</code>. guardrails + cross_llm + stats</li>
              <li><code>.claude/skills/geode-verification</code>. G1-G4 + BiasBuster + Cross-LLM + Cause Tree 의 통합 가이드</li>
            </ul>

            <h2>Clean Context</h2>
            <p>
              BiasBuster 의 anchoring 차단은 Clean Context anchoring prevention 과 연계됩니다. 각 evaluator 는 직전 단계의 verdict 를 직접 보지 못하고, evidence pool 만 받습니다. 자세한 패턴은 `.claude/skills/geode-analysis`.
            </p>

            <p className="text-[var(--ink-3)] text-sm"><em>참조</em>: `core/verification/cross_llm.py`, `core/verification/stats.py`, `.claude/skills/geode-verification`.</p>
          </>
        }
        en={
          <>
            <h2>Why G1-G4 alone is not enough</h2>
            <p>
              The Schema / Range / Grounding / Consistency ladder catches structural defects only. An LLM output that clears all four can still ship three common biases.
            </p>
            <ul>
              <li><strong>Confirmation</strong>. only evidence supporting the hypothesis gets cited</li>
              <li><strong>Recency</strong>. the most recent input over-weights the verdict</li>
              <li><strong>Anchoring</strong>. an earlier analyst pulls the next evaluator's score toward it</li>
            </ul>

            <h2>Detection and rejection</h2>
            <p>
              BiasBuster analyzes the evidence distribution, timing, and correlation with the prior verdict. A detection annotates the verdict with a cause classification (one of the six in the Cause Decision Tree) and forces a re-prompt or an abstain in the evaluator.
            </p>

            <h2>Code map</h2>
            <ul>
              <li><code>core/verification/</code>. guardrails + cross_llm + stats</li>
              <li><code>.claude/skills/geode-verification</code>. integrated guide for G1-G4, BiasBuster, Cross-LLM, and the cause tree</li>
            </ul>

            <h2>Clean Context</h2>
            <p>
              The anchoring branch couples directly to Clean Context anchoring prevention. Each evaluator sees the evidence pool but not the previous step's verdict. The pattern is documented in `.claude/skills/geode-analysis`.
            </p>

            <p className="text-[var(--ink-3)] text-sm"><em>References</em>: `core/verification/cross_llm.py`, `core/verification/stats.py`, `.claude/skills/geode-verification`.</p>
          </>
        }
      />
    </DocsShell>
  );
}
