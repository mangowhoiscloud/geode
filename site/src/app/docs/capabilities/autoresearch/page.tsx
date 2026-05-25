import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Autoresearch — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="capabilities/autoresearch"
      title="Autoresearch"
      titleKo="자가 ML 실험 루프"
      summary="Karpathy autoresearch fork wired into GEODE. Closed-loop generation runner with G1-G6 stability gates and a 9-column tsv results stream."
      summaryKo="Karpathy autoresearch fork 를 GEODE 안 에 통합. G1-G6 안정성 게이트 + 9-col tsv 결과 스트림으로 동작하는 closed-loop generation runner."
    >
      <Bi
        ko={
          <>
            <h2>위치 + 진입점</h2>
            <ul>
              <li><code>autoresearch/train.py</code>. 메인 루프</li>
              <li><code>autoresearch/prepare.py</code>. 데이터/모델 준비</li>
              <li><code>autoresearch/program.md</code>. 매 generation 마다 LLM 이 읽는 program 문서</li>
              <li><code>autoresearch/state/</code>. 누적 결과 (results.tsv, failure_log)</li>
            </ul>

            <h2>Closed-loop 안정성 게이트 (G1-G6)</h2>
            <p>
              Session 60 의 outer-loop 안정화 sprint (#1187 + #1189 + #1190) 에서 G1-G6 closed-loop fix 가 들어왔습니다. 직전 generation 의 결과가 다음 generation 의 입력에 정확히 반영되도록 강제하는 사다리.
            </p>
            <pre>{`G1: closed loop 자체. results.tsv 가 program.md 에 feedback
G2: cross-axis penalty. 한 axis 만 좋아지는 overfit 차단
G3: stability stderr. 분산이 너무 큰 generation 폐기
G4: (예약)
G5: (예약)
G6: 9-col tsv. eval_id, gen_id, seed_id, axis × 5 의 schema 강제`}</pre>

            <h2>실행</h2>
            <pre>{`# generation 0 baseline 실행
cd autoresearch && python train.py --gen 0

# state 확인
cat autoresearch/state/results.tsv | tail -10`}</pre>

            <h2>제약</h2>
            <p>
              real-mode generation 0 baseline 은 Anthropic credit 잔액 의존이며, 현재 BLOCKED. mock-mode 는 항상 동작.
            </p>

            <p className="text-white/40 text-sm"><em>참조</em>: `autoresearch/program.md`, `autoresearch/state/`, `project_autoresearch_outer_loop` memory.</p>
          </>
        }
        en={
          <>
            <h2>Where it lives</h2>
            <ul>
              <li><code>autoresearch/train.py</code>. main loop</li>
              <li><code>autoresearch/prepare.py</code>. data + model setup</li>
              <li><code>autoresearch/program.md</code>. the program doc the LLM rereads each generation</li>
              <li><code>autoresearch/state/</code>. cumulative state (results.tsv, failure_log)</li>
            </ul>

            <h2>Closed-loop stability gates (G1-G6)</h2>
            <p>
              Session 60's outer-loop stabilization sprint (#1187, #1189, #1190) added a ladder of gates so each generation's output actually feeds the next.
            </p>
            <pre>{`G1: closed loop. results.tsv → program.md feedback
G2: cross-axis penalty. blocks single-axis overfit
G3: stability stderr. discards high-variance generations
G4: reserved
G5: reserved
G6: 9-col tsv schema. eval_id, gen_id, seed_id, axis x 5`}</pre>

            <h2>How to run</h2>
            <pre>{`# generation-0 baseline
cd autoresearch && python train.py --gen 0

# inspect state
cat autoresearch/state/results.tsv | tail -10`}</pre>

            <h2>Caveats</h2>
            <p>
              The real-mode gen-0 baseline depends on Anthropic credit balance, currently BLOCKED. Mock mode always works.
            </p>

            <p className="text-white/40 text-sm"><em>References</em>: `autoresearch/program.md`, `autoresearch/state/`, `project_autoresearch_outer_loop` memory.</p>
          </>
        }
      />
    </DocsShell>
  );
}
