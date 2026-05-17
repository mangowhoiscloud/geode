import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Guardrails G1-G4 — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="verification/guardrails"
      title="Guardrails G1-G4"
      titleKo="가드레일 G1-G4"
      summary="Four progressive checks on LLM output. Schema, Range, Grounding, Coherence. Fail-fast, ladder-shaped."
      summaryKo="LLM 출력에 대한 4단계 점진적 검사. Schema, Range, Grounding, Coherence. fail-fast, 사다리 구조."
    >
      <Bi
        ko={
          <>
            <h2>사다리</h2>
            <pre>{`G1 Schema      — does the JSON parse and match the type?
   ↓ pass
G2 Range       — are numeric scores in [1,5], probabilities in [0,1]?
   ↓ pass
G3 Grounding   — is each finding backed by evidence in the input?
   ↓ pass
G4 Coherence   — do the findings imply the score?
   ↓ pass
output accepted`}</pre>
            <p>
              각 게이트는 다음 단계보다 저렴합니다. G1은 Pydantic 검증, G2는 수치 검사입니다.
              G3는 verifier LLM이 입력을 다시 읽고 인용된 각 사실을 확인합니다. G4는 verifier
              LLM이 점수가 findings로부터 따라 나오는지 묻습니다. G1이 이미 실패했다면 G4 비용은
              지불하지 않습니다.
            </p>

            <h2>검증 엔진</h2>
            <p>
              <code>core/verification/engine.py</code>가 사다리를 오케스트레이션합니다.
              <code>core/verification/guardrails.py</code>는 <code>GuardrailType</code> enum과
              타입별 validator를 정의합니다.
            </p>

            <h2>실패 시 동작</h2>
            <p>
              실패는 <code>VERIFICATION_FAIL</code> 훅을 발화시키며, AgenticLoop의
              <code>ErrorRecoveryStrategy</code>가 이를 잡을 수 있습니다. 기본 복구는 모델에
              구조화된 re-ask를 보냅니다.
            </p>
            <ul>
              <li>위반된 규칙</li>
              <li>실패한 정확한 필드</li>
              <li>기대 형태 (정답을 흘리지 않는 선에서)</li>
            </ul>
            <p>
              최대 N회 재시도 (설정 가능). 그 이상은 analyst 출력이 <code>analyst_failed</code>로
              표시되고 synthesizer가 해당 기여자를 건너뜁니다.
            </p>

            <h2>가드레일이 다루지 않는 영역</h2>
            <p>
              가드레일은 출력의 <em>형상</em>과 <em>방어 가능성</em>을 검사합니다. 편향 검사는
              다루지 않습니다. 편향과 도메인별 캘리브레이션은 외부 도메인 플러그인의
              책임입니다. <code>cross_llm.md</code> 템플릿이 독립 재스코어링으로 제공하는
              Cross-LLM 일관성도 별도 검증 계층입니다.
            </p>

            <h2>원인 분류 (synthesizer 잠금)</h2>
            <p>
              검증 후 별도의 결정 트리가 원인을 분류합니다. 6가지 중 하나:
              <code>conversion_failure</code>, <code>undermarketed</code>,
              <code>discovery_failure</code>, <code>genre_mismatch</code>,
              <code>technical_debt</code>, <code>none</code>. synthesizer는 재분류가 금지됩니다.
              서술만 가능합니다. 이 분리는 서술이 증거에 모순되는 원인을 만들어 내는 것을 막습니다.
            </p>
          </>
        }
        en={
          <>
            <h2>The ladder</h2>
            <pre>{`G1 Schema      — does the JSON parse and match the type?
   ↓ pass
G2 Range       — are numeric scores in [1,5], probabilities in [0,1]?
   ↓ pass
G3 Grounding   — is each finding backed by evidence in the input?
   ↓ pass
G4 Coherence   — do the findings imply the score?
   ↓ pass
output accepted`}</pre>
            <p>
              Each gate is cheaper than the next. G1 is a Pydantic validation. G2
              is a numeric check. G3 calls a verifier LLM that re-reads the input
              and confirms each cited fact. G4 calls a verifier LLM that asks
              whether the score follows from the findings. We do not pay for G4
              if G1 already failed.
            </p>

            <h2>The verification engine</h2>
            <p>
              <code>core/verification/engine.py</code> orchestrates the ladder.
              <code>core/verification/guardrails.py</code> defines the
              <code>GuardrailType</code> enum and the per-type validators.
            </p>

            <h2>What a failure does</h2>
            <p>
              Failure fires <code>VERIFICATION_FAIL</code> hook, which the
              AgenticLoop&apos;s <code>ErrorRecoveryStrategy</code> can catch. The
              default recovery prompts the model with a structured re-ask:
            </p>
            <ul>
              <li>What rule was violated</li>
              <li>The exact failing field</li>
              <li>An expected shape (without giving the answer away)</li>
            </ul>
            <p>
              Up to N retries (configurable). Beyond that, the analyst output is
              marked <code>analyst_failed</code> and the synthesizer skips that
              contributor.
            </p>

            <h2>What guardrails do not cover</h2>
            <p>
              Guardrails check the <em>shape</em> and <em>defensibility</em> of an
              output. They do not check for bias or specialized calibration;
              those belong to external packages. They also do not check
              the cross-LLM consistency that{" "}
              <code>cross_llm.md</code> templates provide via independent
              re-scoring.
            </p>

            <h2>Cause classification (synthesizer-locked)</h2>
            <p>
              After verification, a separate decision tree classifies the cause
              (one of six: <code>conversion_failure</code>,{" "}
              <code>undermarketed</code>, <code>discovery_failure</code>,{" "}
              <code>genre_mismatch</code>, <code>technical_debt</code>,{" "}
              <code>none</code>) and the synthesizer is forbidden from
              re-classifying — it can only narrate. This separation prevents the
              narrative from inventing a cause that contradicts the evidence.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
