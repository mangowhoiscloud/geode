import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "The closed loop — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="capabilities/autoresearch"
      title="The closed loop"
      titleKo="폐루프"
      summary="The outer loop end to end. Mutate the scaffold, audit with Petri, gate the fitness gain on a margin, then promote or revert. No model weight or parameter ever changes."
      summaryKo="바깥쪽 루프의 전체 흐름입니다. 스캐폴드를 변이하고, Petri로 감사하고, fitness 이득을 margin 게이트로 검증해 승격하거나 되돌립니다. 모델 가중치와 파라미터는 일절 바꾸지 않습니다."
    >
      <Bi
        ko={
          <>
            <p>
              자기개선 루프의 정확한 정체는 비모수적(non-parametric)
              자기개선입니다. 모델 가중치나 파라미터는 일절 갱신하지 않습니다.
              갱신 대상은 모델을 감싼 스캐폴드, 곧 시스템 프롬프트
              섹션(<code>WRAPPER_PROMPT_SECTIONS</code>)과 7개 behaviour
              kinds입니다. 메커니즘은 선택(selection)입니다. 변이를 만들고,
              적대적 안전 감사로 측정하고, 통계적으로 유의한 개선만 승격합니다.
            </p>
            <pre>{`변이(mutate)
  → 적대적 안전 감사 (Petri, 22-dim judge)
  → fitness 스칼라 (18-dim universe)
  → margin 게이트
  → 승격(promote) 또는 되돌림(revert)
       옵티마이저 = git champion chain`}</pre>

            <h2>모듈 구성: 루프 드라이버와 장비의 분리</h2>
            <p>
              왜 한 파일이 아닌가. 측정 장비를 루프가 스스로 고칠 수 있으면
              측정 자체를 신뢰할 수 없기 때문입니다. S-5 원형 복원에서 측정
              코드는 <code>train.py</code>에서 동작 0-diff로 추출되어 4개의
              형제 모듈이 되었고, <code>program.md</code>는 자기개선 에이전트가
              이 4개 모듈을 수정하는 것을 금지합니다. 장비를 바꾸면 측정
              대상이 아니라 측정 기준이 바뀝니다.
            </p>
            <table>
              <thead>
                <tr><th>모듈</th><th>역할</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>core/self_improving/train.py</code></td>
                  <td>루프 드라이버. 호출 1회 = 감사 1회. 에이전트가 수정하는 유일한 파일이며 <code>WRAPPER_PROMPT_SECTIONS</code>를 소유합니다.</td>
                </tr>
                <tr>
                  <td><code>core/self_improving/measure.py</code></td>
                  <td>감사 실행. <code>geode audit</code> 서브프로세스를 조립해 돌리고, 마지막 줄 JSON <code>{`{"dim_means", "dim_stderr"}`}</code>을 파싱합니다.</td>
                </tr>
                <tr>
                  <td><code>core/self_improving/fitness.py</code></td>
                  <td>fitness 명세와 계산. 축 티어, 가중치, 안정성 축.</td>
                </tr>
                <tr>
                  <td><code>core/self_improving/gate.py</code></td>
                  <td>승격 게이트. margin 규칙, 거부 시 SoT 되돌림, 하드 tool-call 계약 거부권.</td>
                </tr>
                <tr>
                  <td><code>core/self_improving/ledger.py</code></td>
                  <td>런 장부. <code>baseline.json</code>, <code>baseline_archive.jsonl</code>, results 행, 에폭 스탬프.</td>
                </tr>
                <tr>
                  <td><code>core/self_improving/loop/</code></td>
                  <td>Mode B 런타임. <code>mutate/</code>(제안과 적용), <code>observe/</code>(귀속과 provenance), <code>inject/</code>(in-context 슬롯).</td>
                </tr>
              </tbody>
            </table>
            <p>
              <code>train.py</code>라는 파일명은 Karpathy autoresearch의 3-파일
              관습(<code>prepare</code> / <code>train</code> / <code>program.md</code>)을
              빌린 것이며, 이 파일에서 training은 일어나지 않습니다.
            </p>

            <h2>변이 표면: 7개 behaviour kinds</h2>
            <p>
              변이 가능한 표면은 <code>core/self_improving/loop/mutate/policies.py</code>의
              <code>TARGET_KINDS</code>가 고정합니다. 목록에 없는 kind는
              <code>parse_mutation</code>에서 fail-closed로 거부됩니다.
            </p>
            <table>
              <thead>
                <tr><th>kind</th><th>SoT 형태</th></tr>
              </thead>
              <tbody>
                <tr><td><code>prompt</code></td><td>시스템 프롬프트 섹션 dict (wrapper-sections)</td></tr>
                <tr><td><code>tool_policy</code></td><td>flat</td></tr>
                <tr><td><code>decomposition</code></td><td>flat</td></tr>
                <tr><td><code>reflection</code></td><td>flat</td></tr>
                <tr><td><code>skill_catalog</code></td><td>nested (스킬별 description, user_invocable)</td></tr>
                <tr><td><code>agent_contract</code></td><td>nested (role, system_prompt, tools. <code>model</code> 필드는 안전 불변식으로 제외)</td></tr>
                <tr><td><code>tool_descriptions</code></td><td>nested (도구별 description, hints)</td></tr>
              </tbody>
            </table>

            <h2>측정: Petri 감사</h2>
            <p>
              <code>measure.py</code>가 <code>geode audit</code> 서브프로세스를
              띄우면서 후보 스캐폴드를 <code>GEODE_WRAPPER_OVERRIDE</code> env로
              주입합니다. 감사 대상이 정확히 그 후보인지가 측정의 전부이므로 이
              경로는 strict입니다. 파일이 없거나 파싱에 실패하면 조용히 기본
              스캐폴드로 떨어지는 대신 즉시 실패합니다. 역할 분리도
              엄격합니다. 무엇을 측정하는가(루브릭, judge, dim 추출)는 Petri가
              소유하고, 측정이 어떻게 선택 신호로 쌓이는가(티어, 가중치,
              게이트)는 train과 fitness가 소유합니다. 자세한 측정 계층은{" "}
              <a href="/geode/docs/petri/overview">Petri × GEODE</a>를 보세요.
            </p>

            <h2>게이트: margin 규칙</h2>
            <p>
              <code>gate.py</code>의 <code>_should_promote</code>는 순서대로
              판정합니다.
            </p>
            <ol>
              <li>하드 tool-call 계약 거부권. <code>required_tool_path</code>와 <code>args_shape_valid</code> 계약을 어긴 후보는 점수와 무관하게 즉시 거부됩니다.</li>
              <li>이전 baseline이 없으면 부트스트랩 승격.</li>
              <li>critical 축이 퇴행하면 fitness가 0.0으로 붕괴되어 거부됩니다.</li>
              <li>
                fitness 이득이 margin을 넘어야 승격됩니다.
                margin = max(1.0σ × √(σ_prior² + σ_current²), floor)이며 fitness
                스케일에서 계산합니다. floor는 0.005, 이전 baseline의 critical
                dim 중 표본이 1개뿐이면 0.05입니다.
              </li>
            </ol>
            <p>
              승격 정책은 3개 arm으로 나뉩니다. <code>gate</code>(기본, 선택),
              <code>random</code>(시드 고정 동전 던지기),
              <code>never</code>(무변이 바닥선). 이득이 선택에서 왔는지 judge
              노이즈에서 왔는지를 대조군으로 귀속하기 위한 설계입니다. env
              knob은 <code>GEODE_PROMOTE_POLICY</code>입니다.
            </p>

            <h2>승격, 되돌림, champion chain</h2>
            <p>
              승격되면 <code>state/autoresearch/baseline.json</code>이 갱신되고
              <code>baseline_archive.jsonl</code>에 baseline 행이 추가됩니다.
              <code>baseline.json</code>은 승격된 챔피언의 SoT이지 최신 측정
              결과가 아닙니다. 거부되면 <code>_revert_sot_after_reject</code>가
              <code>mutations.jsonl</code>의 apply 행에 기록된 변이 전 값으로
              SoT를 복원합니다. 승격된 스캐폴드 상태의 계보가 git-tracked
              장부로 이어지는 것, 이것이 &quot;git이 옵티마이저&quot;라는 말의
              의미입니다. 거부된 변이는 체인에 남지 않습니다.
            </p>
            <p>
              결과 행의 <code>verdict</code>는 게이트 결과에서 파생됩니다.
              <code>promote</code> / <code>reject</code>, dry-run에서는
              <code>dry-run</code>입니다. <code>AUTORESEARCH_VERDICT</code>
              env는 명시적 override 훅으로만 남아 있습니다.
            </p>

            <h2>실행</h2>
            <pre>{`# 단일 사이클 (변이 1회 + 감사 1회 + 게이트)
uv run python -m core.self_improving.train

# 3-arm 캠페인 (gen-0 baseline K회 → never / random / gate)
geode campaign --n 10 --k 5 --dry-run

# 세션 안에서 상태 확인
/self-improving status`}</pre>
            <p>
              튜너블(<code>BUDGET_MINUTES</code>, <code>SEED_LIMIT</code>,
              promote_policy 등)은 <code>~/.geode/config.toml</code>의
              <code>[self_improving_loop.autoresearch]</code>에서 읽습니다.
              스키마는 <a href="/geode/docs/capabilities/outer-loop">아우터 루프 설정</a>을
              보세요.
            </p>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/petri/judge-dimensions">Judge 차원</a>. 18-dim fitness universe와 critical floor.</li>
              <li><a href="/geode/docs/capabilities/co-scientist">Co-scientist seed 생성</a>. 테스트 분포를 함께 키우는 쪽.</li>
              <li><a href="/geode/docs/capabilities/lineage">계보와 좌표</a>. 이 루프가 문헌 어디에 서 있는지.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              The self-improving loop is, precisely, non-parametric
              self-improvement. No model weight or parameter is ever updated.
              What gets updated is the scaffold around the model: the
              system-prompt sections (<code>WRAPPER_PROMPT_SECTIONS</code>) and
              seven behaviour kinds. The mechanism is selection: produce a
              variation, measure it with an adversarial safety audit, and
              promote only statistically significant improvement.
            </p>
            <pre>{`mutate
  → adversarial safety audit (Petri, 22-dim judge)
  → fitness scalar (18-dim universe)
  → margin gate
  → promote or revert
       optimiser = git champion chain`}</pre>

            <h2>Module layout: loop driver vs measurement gear</h2>
            <p>
              Why not one file? Because a loop that can edit its own measuring
              equipment cannot be trusted to measure anything. The S-5 split
              extracted the measurement code out of <code>train.py</code> with
              zero behaviour diff into four sibling modules, and
              <code>program.md</code> forbids the self-improving agent from
              modifying them. Changing the gear changes what is being measured,
              not the system under test.
            </p>
            <table>
              <thead>
                <tr><th>Module</th><th>Role</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><code>core/self_improving/train.py</code></td>
                  <td>Loop driver. One invocation, one audit. The single file the agent modifies; owns <code>WRAPPER_PROMPT_SECTIONS</code>.</td>
                </tr>
                <tr>
                  <td><code>core/self_improving/measure.py</code></td>
                  <td>Audit execution. Assembles and runs the <code>geode audit</code> subprocess, parses the last-line JSON <code>{`{"dim_means", "dim_stderr"}`}</code>.</td>
                </tr>
                <tr>
                  <td><code>core/self_improving/fitness.py</code></td>
                  <td>Fitness spec and computation. Axis tiers, weights, stability axis.</td>
                </tr>
                <tr>
                  <td><code>core/self_improving/gate.py</code></td>
                  <td>Promote gate. Margin rule, reject-and-revert, hard tool-call contract veto.</td>
                </tr>
                <tr>
                  <td><code>core/self_improving/ledger.py</code></td>
                  <td>Run ledgers. <code>baseline.json</code>, <code>baseline_archive.jsonl</code>, results rows, epoch stamping.</td>
                </tr>
                <tr>
                  <td><code>core/self_improving/loop/</code></td>
                  <td>Mode B runtime. <code>mutate/</code> (propose and apply), <code>observe/</code> (attribution and provenance), <code>inject/</code> (in-context slots).</td>
                </tr>
              </tbody>
            </table>
            <p>
              The filename <code>train.py</code> borrows the Karpathy
              autoresearch three-file convention (<code>prepare</code> /{" "}
              <code>train</code> / <code>program.md</code>). No training happens
              in this file.
            </p>

            <h2>The mutation surface: 7 behaviour kinds</h2>
            <p>
              The mutable surface is pinned by <code>TARGET_KINDS</code> in{" "}
              <code>core/self_improving/loop/mutate/policies.py</code>. Any
              kind outside the list is rejected fail-closed at{" "}
              <code>parse_mutation</code>.
            </p>
            <table>
              <thead>
                <tr><th>kind</th><th>SoT shape</th></tr>
              </thead>
              <tbody>
                <tr><td><code>prompt</code></td><td>system-prompt section dict (wrapper-sections)</td></tr>
                <tr><td><code>tool_policy</code></td><td>flat</td></tr>
                <tr><td><code>decomposition</code></td><td>flat</td></tr>
                <tr><td><code>reflection</code></td><td>flat</td></tr>
                <tr><td><code>skill_catalog</code></td><td>nested (per-skill description, user_invocable)</td></tr>
                <tr><td><code>agent_contract</code></td><td>nested (role, system_prompt, tools; the <code>model</code> field is excluded as a safety invariant)</td></tr>
                <tr><td><code>tool_descriptions</code></td><td>nested (per-tool description, hints)</td></tr>
              </tbody>
            </table>

            <h2>Measurement: the Petri audit</h2>
            <p>
              <code>measure.py</code> spawns a <code>geode audit</code>{" "}
              subprocess and injects the candidate scaffold through the{" "}
              <code>GEODE_WRAPPER_OVERRIDE</code> env. The whole point of the
              measurement is that the audited thing is exactly that candidate,
              so this path is strict: a missing or unparseable file fails
              loudly instead of silently auditing the default scaffold. The
              role split is equally strict. Petri owns what gets measured (the
              rubric, the judge, the dim extraction); train and fitness own how
              measurement accrues into a selection signal (tiers, weights, the
              gate). See <a href="/geode/docs/petri/overview">Petri × GEODE</a>{" "}
              for the measurement layer.
            </p>

            <h2>The gate: margin rule</h2>
            <p>
              <code>_should_promote</code> in <code>gate.py</code> decides in
              order:
            </p>
            <ol>
              <li>Hard tool-call contract veto. A candidate that fails the <code>required_tool_path</code> or <code>args_shape_valid</code> contract is rejected outright, regardless of score.</li>
              <li>No prior baseline: bootstrap promote.</li>
              <li>A critical-axis regression collapses fitness to 0.0: reject.</li>
              <li>
                The fitness gain must exceed the margin:
                margin = max(1.0σ × √(σ_prior² + σ_current²), floor), computed
                on the fitness scale. The floor is 0.005, raised to 0.05 when
                the prior baseline has a single sample on any critical dim.
              </li>
            </ol>
            <p>
              Promote policy runs as three control arms: <code>gate</code>{" "}
              (default, selection), <code>random</code> (seeded coin-flip), and{" "}
              <code>never</code> (no-mutation floor), so that gains attribute to
              selection rather than judge noise or drift. The env knob is{" "}
              <code>GEODE_PROMOTE_POLICY</code>.
            </p>

            <h2>Promote, revert, and the champion chain</h2>
            <p>
              A promote updates <code>state/autoresearch/baseline.json</code>{" "}
              and appends a baseline row to <code>baseline_archive.jsonl</code>.
              <code>baseline.json</code> is the promoted champion&apos;s SoT,
              not the latest measurement. A reject runs{" "}
              <code>_revert_sot_after_reject</code>, restoring the SoT to the
              pre-mutation value recorded in the matching apply row of{" "}
              <code>mutations.jsonl</code>. The lineage of promoted scaffold
              states lives in git-tracked ledgers; that is what &quot;git as
              the optimiser&quot; means. Rejected mutations never enter the
              chain.
            </p>
            <p>
              The <code>verdict</code> on each results row is derived from the
              gate outcome: <code>promote</code> / <code>reject</code>, or{" "}
              <code>dry-run</code> under <code>--dry-run</code>. The{" "}
              <code>AUTORESEARCH_VERDICT</code> env remains only as an explicit
              override hook.
            </p>

            <h2>Running it</h2>
            <pre>{`# one cycle (one mutation + one audit + the gate)
uv run python -m core.self_improving.train

# 3-arm campaign (K gen-0 baselines, then never / random / gate)
geode campaign --n 10 --k 5 --dry-run

# in-session status
/self-improving status`}</pre>
            <p>
              Tunables (<code>BUDGET_MINUTES</code>, <code>SEED_LIMIT</code>,
              promote policy, and friends) load from{" "}
              <code>[self_improving_loop.autoresearch]</code> in{" "}
              <code>~/.geode/config.toml</code>. Schema details live in{" "}
              <a href="/geode/docs/capabilities/outer-loop">Outer-loop
              configuration</a>.
            </p>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/petri/judge-dimensions">Judge dimensions</a>. The 18-dim fitness universe and the critical floor.</li>
              <li><a href="/geode/docs/capabilities/co-scientist">Co-scientist seed generation</a>. The side that grows the test distribution.</li>
              <li><a href="/geode/docs/capabilities/lineage">Lineage and positioning</a>. Where this loop sits in the literature.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
