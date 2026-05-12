import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Automation — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/automation"
      title="Automation Sidecar"
      titleKo="자동화 사이드카"
      summary="Drift detection, model promotion, expert panel voting. The sidecar between agent and runtime that keeps the system improving over time."
      summaryKo="drift 감지, 모델 프로모션, 전문가 패널 투표. 시간이 지나면서 시스템이 계속 개선되도록 에이전트(L4)와 런타임(L2) 사이에 자리한 사이드카."
    >
      <Bi
        ko={
          <>
            <h2>왜 사이드카인가</h2>
            <p>
              에이전트(L4)는 실행합니다. 런타임(L2)은 인프라를 제공합니다. Automation은
              두 계층 사이에서 결과를 관찰하고 그 아래 런타임을 회전시키는 사이드카입니다.
              더 나은 모델을 승격시키고, drift된 모델을 deprecate하고, 전문가 피드백을
              수집합니다. 4-계층 스택 자체에는 포함되지 않습니다.
            </p>

            <h2>파일</h2>
            <ul>
              <li><code>core/automation/model_registry.py:36</code>. <code>class PromotionStage</code> (development, staging, production).</li>
              <li><code>core/automation/feedback_loop.py</code>. phase FSM.</li>
              <li><code>core/automation/drift_detector.py</code>. correlation 및 severity 분석.</li>
              <li><code>core/automation/expert_panel.py</code>. junior/senior/principal 투표 티어.</li>
            </ul>

            <h2>프로모션 단계</h2>
            <pre>{`development → staging → production
   ↑              ↑              │
   │              │              ▼
   └──────────────┴──── drift detected → rollback`}</pre>

            <h2>drift 감지</h2>
            <p>
              drift 심각도는 <code>low</code> /{" "}
              <code>medium</code> / <code>high</code> / <code>critical</code>로
              등급화됩니다. production 모델의 critical drift는 즉시 이전 staging
              스냅샷으로 롤백을 트리거합니다. 더 낮은 심각도는 메트릭으로
              기록되고 전문가 패널을 기다립니다.
            </p>

            <h2>전문가 패널 투표</h2>
            <p>
              모델 출력에 이의가 제기되면 가상 전문가 패널 (junior, senior,
              principal 티어)이 출력 수용 여부에 투표합니다. 표는 티어로 가중치가
              매겨지고 결과는 모델 레지스트리로 피드백됩니다.
            </p>

            <h2>발화되는 훅 이벤트</h2>
            <ul>
              <li><code>DRIFT_DETECTED</code></li>
              <li><code>MODEL_PROMOTED</code></li>
              <li><code>OUTCOME_COLLECTED</code></li>
              <li><code>EXPERT_VOTE_CAST</code></li>
              <li><code>FEEDBACK_PHASE_CHANGED</code></li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Why a sidecar</h2>
            <p>
              The agent (L4) executes. The runtime (L2) provides infrastructure.
              Automation is the sidecar that sits between them, watching outcomes
              and rotating the underlying runtime: promoting better models,
              deprecating drifted ones, and collecting expert feedback. It is
              not part of the 4-layer stack itself.
            </p>

            <h2>Files</h2>
            <ul>
              <li><code>core/automation/model_registry.py:36</code> — <code>class PromotionStage</code> (development, staging, production)</li>
              <li><code>core/automation/feedback_loop.py</code> — phase FSM</li>
              <li><code>core/automation/drift_detector.py</code> — correlation + severity analysis</li>
              <li><code>core/automation/expert_panel.py</code> — junior/senior/principal voting tiers</li>
            </ul>

            <h2>Promotion stages</h2>
            <pre>{`development → staging → production
   ↑              ↑              │
   │              │              ▼
   └──────────────┴──── drift detected → rollback`}</pre>

            <h2>Drift detection</h2>
            <p>
              Drift severity is graded <code>low</code> /{" "}
              <code>medium</code> / <code>high</code> / <code>critical</code>.
              Critical drift on a production model triggers immediate rollback to
              the previous staging snapshot. Lower severity records a metric and
              waits for the expert panel.
            </p>

            <h2>Expert panel voting</h2>
            <p>
              When a model output is contested, a virtual expert panel (junior,
              senior, principal tiers) votes on whether the output should be
              accepted. Votes are weighted by tier and the result feeds back to
              the model registry.
            </p>

            <h2>Hook events fired</h2>
            <ul>
              <li><code>DRIFT_DETECTED</code></li>
              <li><code>MODEL_PROMOTED</code></li>
              <li><code>OUTCOME_COLLECTED</code></li>
              <li><code>EXPERT_VOTE_CAST</code></li>
              <li><code>FEEDBACK_PHASE_CHANGED</code></li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
