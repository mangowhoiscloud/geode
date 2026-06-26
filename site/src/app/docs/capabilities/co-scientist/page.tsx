import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Co-scientist seed generation — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="capabilities/co-scientist"
      title="Co-scientist seed generation"
      titleKo="Co-scientist seed 생성"
      summary="A nine-role agent loop that grows the evaluation seed corpus. Supervisor, literature review, generator, proximity, critic, pilot, ranker, evolver, meta-reviewer."
      summaryKo="평가용 seed 코퍼스를 키우는 9-역할 에이전트 루프입니다. supervisor, literature review, generator, proximity, critic, pilot, ranker, evolver, meta-reviewer로 이어집니다."
    >
      <Bi
        ko={
          <>
            <h2>왜 seed를 에이전트가 만드나</h2>
            <p>
              고정된 벤치마크는 루프가 돌수록 포화됩니다. 폐루프가 스캐폴드를
              개선하는 동안 테스트 분포도 함께 자라야 측정 여유가
              남습니다. 그래서 GEODE는 Google AI Co-Scientist의 generate,
              review, rank, evolve 멀티 에이전트 흐름을 Petri seed 생성에
              이식했습니다. 한 target dimension(예:{" "}
              <code>broken_tool_use</code>)에 대해 후보 seed를 생성하고,
              토너먼트로 순위를 매기고, 생존자를 진화시켜 다음 세대로
              넘깁니다. <code>plugins/seed_generation/orchestrator.py</code>의{" "}
              <code>Pipeline.arun</code>이 phase 순서대로 sub-agent를
              fan-out합니다.
            </p>

            <h2>9개 역할</h2>
            <p>
              역할은 <code>plugins/seed_generation/agents/</code>에 역할별{" "}
              <code>&lt;role&gt;.py</code> + <code>&lt;role&gt;.md</code> 프롬프트
              쌍으로 구현되며, task prefix가 phase를 식별합니다
              (<code>orchestrator.py</code>의 <code>_TASK_PREFIX_TO_PHASE</code>).
            </p>
            <table>
              <thead>
                <tr><th>역할</th><th>prefix</th><th>하는 일</th></tr>
              </thead>
              <tbody>
                <tr><td><code>supervisor</code></td><td><code>super-</code></td><td>전략 합성. phase별 guidance 산출</td></tr>
                <tr><td><code>literature_review</code></td><td><code>lit-</code></td><td>외부 문헌 분석 (max_papers &gt; 0일 때)</td></tr>
                <tr><td><code>generator</code></td><td><code>gen-</code></td><td>후보 seed 초안 생성 (다중 턴 debate)</td></tr>
                <tr><td><code>proximity</code></td><td><code>prox-</code></td><td>유사도 클러스터링. 중복 후보 식별</td></tr>
                <tr><td><code>critic</code></td><td><code>crit-</code></td><td>후보별 비평 (target dimension 기준)</td></tr>
                <tr><td><code>pilot</code></td><td><code>pilot-</code></td><td>후보별 실측 petri_audit 1회. 난이도 신호 산출</td></tr>
                <tr><td><code>ranker</code></td><td><code>vote-</code></td><td>3-judge 패널 토너먼트. Elo 갱신</td></tr>
                <tr><td><code>evolver</code></td><td><code>evolve-</code></td><td>생존 후보 변이. 다음 세대 후보 생성</td></tr>
                <tr><td><code>meta_reviewer</code></td><td><code>meta-</code></td><td>coverage와 gap 분석. 다음 세대 prior 산출</td></tr>
              </tbody>
            </table>
            <p>
              반복 사이클에서는 evolved 후보를 후보 목록(candidates)으로 승격한 뒤 critic,
              pilot, ranker, evolver, meta_reviewer만 다시 돕니다. 새 초안이
              아니라 진화된 후보를 다듬는 단계이기 때문입니다.
            </p>

            <h2>pilot은 실측입니다</h2>
            <p>
              pilot은 후보마다 실제 petri_audit 측정을 1회 돌립니다.{" "}
              <code>inspect_ai</code>가 필요하므로 <code>[audit]</code> extra가
              설치돼 있어야 하고, 없으면 0점으로 조용히 채우는 대신 크게
              실패합니다. 측정값(<code>dim_means</code>)이 곧 그 후보의 난이도
              신호가 되어 생존자 선택에 들어갑니다.
            </p>

            <h2>토너먼트와 생존자 선택</h2>
            <p>
              <code>plugins/seed_generation/tournament.py</code>가 3-judge 패널
              pairwise 매치를 돌립니다. 과반이면 승자, 그 외에는 tie로 양쪽
              rating이 갱신되고, 유효 표가 모자라면 매치를 건너뜁니다. Elo는
              로지스틱 기대값 기반 K-factor 갱신이며, 제시 순서를 무작위로
              뒤집어 position bias를 줄입니다. 기록은{" "}
              <code>elo_log.tsv</code>에 남습니다.
            </p>
            <p>
              생존자 선택의 기본값은 Elo 단독이 아니라 <code>blend</code>입니다.
              Elo와 난이도를 z-score로 합치되, pilot 신호가 약한 후보는
              자동으로 Elo만으로 평가됩니다. 식과 조정값은{" "}
              <a href="/geode/docs/capabilities/seed-pipeline">Seed 파이프라인</a>에서
              다룹니다.
            </p>

            <h2>실행</h2>
            <pre>{`# 한 target dimension에 대한 generate-debate-evolve 런
geode audit-seeds generate

# phase별 체크포인트에서 이어서
geode audit-seeds resume

# 역할 × (model, source) 바인딩 매트릭스 확인
geode audit-seeds config`}</pre>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/capabilities/seed-pipeline">Seed 파이프라인</a>. picker, manifest, 비용 미리보기, blend 선택식.</li>
              <li><a href="/geode/docs/petri/seeds">Seed 생성 런</a>. 세대별 결과 대시보드.</li>
              <li><a href="/geode/docs/petri/scenarios">시나리오</a>. 만들어진 seed가 들어가는 코퍼스.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Why agents generate the seeds</h2>
            <p>
              A fixed benchmark saturates as the loop runs. While the closed
              loop improves the scaffold, the test distribution has to grow
              alongside it or measurement runs out of headroom. So GEODE ports
              Google AI Co-Scientist&apos;s generate, review, rank, evolve
              multi-agent flow onto Petri seed generation. For one target
              dimension (say <code>broken_tool_use</code>) it drafts candidate
              seeds, ranks them in a tournament, and evolves the survivors into
              the next generation. <code>Pipeline.arun</code> in{" "}
              <code>plugins/seed_generation/orchestrator.py</code> fans out one
              sub-agent per phase, in order.
            </p>

            <h2>The nine roles</h2>
            <p>
              Each role is a paired <code>&lt;role&gt;.py</code> +{" "}
              <code>&lt;role&gt;.md</code> prompt under{" "}
              <code>plugins/seed_generation/agents/</code>; task prefixes
              identify the phase (<code>_TASK_PREFIX_TO_PHASE</code> in{" "}
              <code>orchestrator.py</code>).
            </p>
            <table>
              <thead>
                <tr><th>Role</th><th>prefix</th><th>What it does</th></tr>
              </thead>
              <tbody>
                <tr><td><code>supervisor</code></td><td><code>super-</code></td><td>Strategy synthesis; per-phase guidance</td></tr>
                <tr><td><code>literature_review</code></td><td><code>lit-</code></td><td>External paper analysis (when max_papers &gt; 0)</td></tr>
                <tr><td><code>generator</code></td><td><code>gen-</code></td><td>Drafts candidate seeds (multi-turn debate)</td></tr>
                <tr><td><code>proximity</code></td><td><code>prox-</code></td><td>Similarity clustering; flags near-duplicates</td></tr>
                <tr><td><code>critic</code></td><td><code>crit-</code></td><td>Per-candidate critique against the target dimension</td></tr>
                <tr><td><code>pilot</code></td><td><code>pilot-</code></td><td>One real petri_audit measurement per candidate; difficulty signal</td></tr>
                <tr><td><code>ranker</code></td><td><code>vote-</code></td><td>3-judge panel tournament; Elo updates</td></tr>
                <tr><td><code>evolver</code></td><td><code>evolve-</code></td><td>Mutates survivors into next-generation candidates</td></tr>
                <tr><td><code>meta_reviewer</code></td><td><code>meta-</code></td><td>Coverage and gap analysis; next-generation priors</td></tr>
              </tbody>
            </table>
            <p>
              On repeat iterations the evolved candidates are promoted into the
              candidate set and only critic, pilot, ranker, evolver, and
              meta_reviewer re-run. Each cycle refines evolved candidates
              rather than drafting a fresh batch.
            </p>

            <h2>The pilot is a real measurement</h2>
            <p>
              The pilot runs one real petri_audit measurement per candidate. It
              needs <code>inspect_ai</code>, so the <code>[audit]</code> extra
              must be installed; when it is missing the pilot fails loudly
              instead of zero-filling scores. The measured{" "}
              <code>dim_means</code> become that candidate&apos;s difficulty
              signal and feed survivor selection.
            </p>

            <h2>Tournament and survivor selection</h2>
            <p>
              <code>plugins/seed_generation/tournament.py</code> runs pairwise
              matches judged by a 3-judge panel. A majority picks the winner,
              anything else is a tie that still updates both ratings, and a
              match without enough valid votes is skipped. Elo updates use a
              K-factor over the logistic expected score, with presentation
              order randomised to dampen position bias. Every match lands in{" "}
              <code>elo_log.tsv</code>.
            </p>
            <p>
              Survivor selection defaults to <code>blend</code>, not pure Elo:
              Elo and difficulty are combined as z-scores, and a candidate with
              a weak pilot signal degrades gracefully to Elo alone. The formula
              and knobs live in{" "}
              <a href="/geode/docs/capabilities/seed-pipeline">Seed pipeline</a>.
            </p>

            <h2>Running it</h2>
            <pre>{`# one generate-debate-evolve run for a target dimension
geode audit-seeds generate

# continue from per-phase checkpoints
geode audit-seeds resume

# inspect the role x (model, source) binding matrix
geode audit-seeds config`}</pre>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/capabilities/seed-pipeline">Seed pipeline</a>. Picker, manifest, cost preview, and the blend formula.</li>
              <li><a href="/geode/docs/petri/seeds">Seed-generation runs</a>. The per-generation results dashboard.</li>
              <li><a href="/geode/docs/petri/scenarios">Scenarios</a>. The corpus the generated seeds feed.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
