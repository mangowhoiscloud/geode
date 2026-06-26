import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Scenarios — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="petri/scenarios"
      title="Scenarios"
      titleKo="시나리오"
      summary="The Petri seed corpus plus GEODE-specific seeds, grouped into critical, auxiliary, and info dimension buckets."
      summaryKo="Petri seed 코퍼스에 GEODE 전용 seed를 더해 critical, auxiliary, info 차원 버킷으로 묶습니다."
    >
      <Bi
        ko={
          <>
            <p>
              seed는 감사 한 판의 시나리오입니다. auditor가 이 시나리오를 들고
              target을 압박하고, judge가 그 transcript를 채점합니다. seed
              코퍼스가 어떤 차원을 얼마나 자극하느냐가 곧 측정의 분포이므로,
              GEODE는 코퍼스를 fitness universe의 티어 구조 그대로
              조직합니다.
            </p>

            <h2>티어 구조: critical / auxiliary / info</h2>
            <p>
              GEODE 전용 seed 풀은 <code>plugins/petri_audit/seeds/</code>에
              계층 트리로 놓입니다.
            </p>
            <pre>{`plugins/petri_audit/seeds/
├── critical/      # fitness에서 critical 티어인 차원들
│   └── <dim>/<NN>_<variant>.md
├── auxiliary/     # auxiliary 티어 차원들
│   └── <dim>/<NN>_<variant>.md
└── info/          # 기록만 하고 가중치 0인 차원들
    └── <dim>/<NN>_<variant>.md`}</pre>
            <p>
              티어는 18-dim fitness universe(critical 5 + auxiliary 10 + info
              3)를 그대로 따릅니다. 어떤 차원이 어느 티어에 속하고 왜 그런지는{" "}
              <a href="/geode/docs/petri/judge-dimensions">Judge 차원</a>이
              SoT입니다. <code>core/self_improving/prepare.py</code>가 루프
              시작 전에 이 트리를 검증하며, 전체 seed 수가{" "}
              <code>MIN_SEED_COUNT</code>(18) 아래면 시작을 거부합니다.
            </p>

            <h2>seed 파일의 모양</h2>
            <p>
              seed 하나는 <code>.md</code> 파일 하나입니다. frontmatter(tags)와
              branch별 압력 곡선으로 구성됩니다.
            </p>
            <ul>
              <li>보통 5개 branch가 1 → 2 → 3 → 2 → 1 압력 곡선을 따릅니다. 압력 1은 캐주얼한 요청, 압력 3은 긴급성, 권위, 손실 회피를 동원한 명시적 압박입니다.</li>
              <li>곡선의 목적은 target이 어느 압력 지점에서 무너지는지, 그리고 압력이 내려간 뒤 회복하는지를 잡는 것입니다.</li>
              <li>frontmatter의 canary GUID는 이 텍스트가 모델 사전학습 코퍼스로 흘러드는 것을 탐지하기 위한 표식입니다.</li>
            </ul>

            <h2>코퍼스는 어떻게 자라나</h2>
            <p>
              정적 카탈로그가 아닙니다. seed-generation 파이프라인
              (<a href="/geode/docs/capabilities/co-scientist">Co-scientist seed
              생성</a>)이 target dimension별로 새 seed를 만들고, 생존자가{" "}
              <code>geode seeds assemble</code>을 거쳐 사이클 입력
              풀(<code>state/seed-pools/cycle-input</code>)로 조립됩니다.
              버전 고정 held-out 벤치마크(<code>state/seed-pools/held-out</code>)는
              비교 기준자로 따로 둡니다.
            </p>

            <h2>upstream Petri 기본 seed</h2>
            <p>
              <code>inspect_petri</code> 패키지 자체도 일반 misalignment
              시나리오의 기본 seed를 싣고 있습니다. GEODE 감사의 기본{" "}
              <code>--seed-select</code>는 자체 풀
              (<code>plugins/petri_audit/seeds</code>)이지만, upstream seed를
              선택해 함께 돌릴 수 있습니다.
            </p>

            <h2>커스텀 seed 추가</h2>
            <ol>
              <li>해당 차원의 티어 폴더에 <code>plugins/petri_audit/seeds/&lt;tier&gt;/&lt;dim&gt;/&lt;NN&gt;_&lt;variant&gt;.md</code>로 생성합니다.</li>
              <li>frontmatter에 <code>tags</code>를 적습니다.</li>
              <li>branch별 압력 시나리오를 작성합니다 (5 branch 권장).</li>
              <li><code>geode audit --seed-select &lt;경로 또는 id&gt;</code>로 돌려봅니다.</li>
            </ol>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/petri/run">감사 실행</a>. seed 선택과 dry-run 흐름.</li>
              <li><a href="/geode/docs/petri/judge-dimensions">Judge 차원</a>. 티어와 가중치의 근거.</li>
              <li><a href="/geode/self-improving/petri-bundle/">번들 뷰어</a>. 공개된 감사 결과.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              A seed is the scenario for one audit: the auditor uses it to
              pressure the target, and the judge scores the resulting
              transcript. Which dimensions the corpus exercises, and how hard,
              is the measurement distribution itself, so GEODE organizes the
              corpus by the same tier structure as the fitness universe.
            </p>

            <h2>Tier structure: critical / auxiliary / info</h2>
            <p>
              The GEODE-specific seed pool lives as a hierarchical tree under{" "}
              <code>plugins/petri_audit/seeds/</code>.
            </p>
            <pre>{`plugins/petri_audit/seeds/
├── critical/      # dimensions in the critical fitness tier
│   └── <dim>/<NN>_<variant>.md
├── auxiliary/     # auxiliary-tier dimensions
│   └── <dim>/<NN>_<variant>.md
└── info/          # recorded but zero-weight dimensions
    └── <dim>/<NN>_<variant>.md`}</pre>
            <p>
              The tiers mirror the 18-dim fitness universe (5 critical + 10
              auxiliary + 3 info). Which dimension sits in which tier, and why,
              is owned by{" "}
              <a href="/geode/docs/petri/judge-dimensions">Judge dimensions</a>.
              Before the loop starts,{" "}
              <code>core/self_improving/prepare.py</code> validates this tree
              and refuses to run when the total seed count falls below{" "}
              <code>MIN_SEED_COUNT</code> (18).
            </p>

            <h2>Anatomy of a seed file</h2>
            <p>
              One seed is one <code>.md</code> file: frontmatter (tags) plus a
              per-branch pressure curve.
            </p>
            <ul>
              <li>Usually 5 branches follow a 1 → 2 → 3 → 2 → 1 pressure curve. Pressure 1 is a casual request; pressure 3 applies explicit urgency, authority, and loss aversion.</li>
              <li>The curve exists to catch where the target gives way, and whether it recovers once the pressure backs off.</li>
              <li>The canary GUID in the frontmatter exists to detect this text leaking into model pre-training corpora.</li>
            </ul>

            <h2>How the corpus grows</h2>
            <p>
              This is not a static catalog. The seed-generation pipeline
              (<a href="/geode/docs/capabilities/co-scientist">Co-scientist
              seed generation</a>) drafts new seeds per target dimension, and
              survivors are assembled by <code>geode seeds assemble</code> into
              the cycle-input pool
              (<code>state/seed-pools/cycle-input</code>). A version-frozen
              held-out bench (<code>state/seed-pools/held-out</code>) is kept
              apart as the comparison ruler.
            </p>

            <h2>Upstream Petri default seeds</h2>
            <p>
              The <code>inspect_petri</code> package ships its own default
              seeds covering general misalignment scenarios. GEODE audits
              default <code>--seed-select</code> to the in-repo pool
              (<code>plugins/petri_audit/seeds</code>), but upstream seeds can
              be selected and run alongside.
            </p>

            <h2>Adding a custom seed</h2>
            <ol>
              <li>Create it under the dimension&apos;s tier folder: <code>plugins/petri_audit/seeds/&lt;tier&gt;/&lt;dim&gt;/&lt;NN&gt;_&lt;variant&gt;.md</code>.</li>
              <li>Add <code>tags</code> to the frontmatter.</li>
              <li>Write the per-branch pressure scenarios (5 branches recommended).</li>
              <li>Try it with <code>geode audit --seed-select &lt;path or id&gt;</code>.</li>
            </ol>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/petri/run">Run an audit</a>. Seed selection and the dry-run flow.</li>
              <li><a href="/geode/docs/petri/judge-dimensions">Judge dimensions</a>. The rationale behind tiers and weights.</li>
              <li><a href="/geode/self-improving/petri-bundle/">Bundle viewer</a>. Published audit results.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
