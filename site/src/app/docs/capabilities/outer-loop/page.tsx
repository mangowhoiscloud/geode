import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Outer-loop configuration — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="capabilities/outer-loop"
      title="Outer-loop configuration"
      titleKo="아우터 루프 설정"
      summary="The shared schema and loader for autoresearch, seed generation, Petri roles, and the auto-trigger scheduler. Strict by default."
      summaryKo="autoresearch, seed 생성, Petri 역할, auto-trigger 스케줄러가 공유하는 스키마와 로더입니다. 기본은 strict 검증입니다."
    >
      <Bi
        ko={
          <>
            <h2>왜 아우터 루프 설정이 한 곳에 있나</h2>
            <p>
              아우터 루프는 역할이 많습니다. auditor, target, judge, mutator가
              각각 모델과 자격 lane을 갖고, seed 풀과 promote 정책과 스케줄러
              knob이 더해집니다. 이것이 env, 모듈 상수, 별도 TOML로 흩어지면
              &quot;지금 루프가 실제로 무엇으로 도는가&quot;를 답할 수 없게 됩니다.
              그래서 전부 <code>~/.geode/config.toml</code>의{" "}
              <code>[self_improving_loop]</code> 섹션 한 곳에 모았고, 로더는{" "}
              <code>core/config/self_improving.py</code>의{" "}
              <code>load_self_improving_loop_config</code>입니다.
            </p>

            <h2>스키마 스케치</h2>
            <pre>{`[self_improving_loop]
fallback_to_payg = false      # subscription 소진 시 PAYG 폴백 차단
warn_threshold = 0.5          # 사용량 경고 임계값
abort_threshold = 0.9         # 사용량 중단 임계값

[self_improving_loop.autoresearch]
budget_minutes = 5            # 실험 1회 벽시계 예산
seed_limit = 10               # 감사 1회당 seed 수
seed_select = "plugins/petri_audit/seeds"
dim_set = "subset"            # 22-dim 루브릭
max_turns = 10
promote_policy = "gate"       # gate / random / never
replicate = 1                 # 감사 반복 M

[self_improving_loop.autoresearch.target]    # judge / auditor 동일 형태
model = "..."
source = "claude_cli"         # 자격 lane

[self_improving_loop.autoresearch.mutator]
default_model = "..."
source = "auto"

[self_improving_loop.seed_generation]
candidates_default = 15
# roles.<role> = { model, source, ... } 바인딩

[self_improving_loop.scheduler]
enabled = false
cron = "0 */6 * * *"
min_interval_minutes = 60`}</pre>
            <p>
              정확한 필드 정의와 docstring은{" "}
              <code>core/config/self_improving.py</code>가 SoT입니다. 위 값들은
              스키마의 기본값입니다.
            </p>

            <h2>로드 경로와 strict 검증</h2>
            <p>
              해석 순서는 (1) 명시적 path 인자, (2){" "}
              <code>GEODE_CONFIG_TOML</code> env, (3){" "}
              <code>~/.geode/config.toml</code>입니다. 파일이나 섹션이 없으면
              기본값으로 채운 모델을 돌려주지만, 섹션이 존재하는데 모르는
              필드가 있으면 모든 모델이 <code>extra=&quot;forbid&quot;</code>라
              즉시 <code>ValueError</code>로 실패합니다. 오타가 조용히
              무시되는 것보다 시끄럽게 죽는 쪽이 측정 인프라에서는 옳습니다.
            </p>

            <h2>레거시 마이그레이션과 디버깅</h2>
            <ul>
              <li>
                <code>geode config migrate-petri-toml</code>. 옛{" "}
                <code>~/.geode/petri.toml</code> 역할 override를{" "}
                <code>[self_improving_loop.autoresearch.&lt;role&gt;]</code>로
                옮깁니다. 기본은 dry-run입니다.
              </li>
              <li>
                <code>geode config explain</code>. 어떤 레이어(CLI, env,
                project toml, global toml)가 값을 이기고 있는지 보여줍니다.
                &quot;설정을 바꿨는데 그대로&quot;의 답입니다.
              </li>
            </ul>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/capabilities/autoresearch">Closed-Loop</a>. 이 설정을 소비하는 루프 본체.</li>
              <li><a href="/geode/docs/config/reference">설정 레퍼런스</a>. config.toml 전체 표면.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Why the outer loop has one config root</h2>
            <p>
              The outer loop juggles many roles: auditor, target, judge, and
              mutator each carry a model and a credential lane, plus seed
              pools, promote policy, and scheduler knobs. Scattered across env
              vars, module constants, and side TOML files, the question
              &quot;what is the loop actually running with right now&quot;
              becomes unanswerable. So everything lives in the{" "}
              <code>[self_improving_loop]</code> section of{" "}
              <code>~/.geode/config.toml</code>, loaded by{" "}
              <code>load_self_improving_loop_config</code> in{" "}
              <code>core/config/self_improving.py</code>.
            </p>

            <h2>Schema sketch</h2>
            <pre>{`[self_improving_loop]
fallback_to_payg = false      # deny PAYG fallback on subscription exhaust
warn_threshold = 0.5          # usage warning threshold
abort_threshold = 0.9         # usage abort threshold

[self_improving_loop.autoresearch]
budget_minutes = 5            # wall-clock budget per experiment
seed_limit = 10               # seeds per audit
seed_select = "plugins/petri_audit/seeds"
dim_set = "subset"            # the 22-dim rubric
max_turns = 10
promote_policy = "gate"       # gate / random / never
replicate = 1                 # audit replicates M

[self_improving_loop.autoresearch.target]    # judge / auditor same shape
model = "..."
source = "claude_cli"         # credential lane

[self_improving_loop.autoresearch.mutator]
default_model = "..."
source = "auto"

[self_improving_loop.seed_generation]
candidates_default = 15
# roles.<role> = { model, source, ... } bindings

[self_improving_loop.scheduler]
enabled = false
cron = "0 */6 * * *"
min_interval_minutes = 60`}</pre>
            <p>
              The exact field definitions and docstrings live in{" "}
              <code>core/config/self_improving.py</code>; the values above are
              the schema defaults.
            </p>

            <h2>Load path and strict validation</h2>
            <p>
              Resolution order: (1) explicit path argument, (2) the{" "}
              <code>GEODE_CONFIG_TOML</code> env, (3){" "}
              <code>~/.geode/config.toml</code>. A missing file or section
              returns a fully-defaulted model, but if the section exists and
              contains an unknown field, every model is{" "}
              <code>extra=&quot;forbid&quot;</code> and the loader raises{" "}
              <code>ValueError</code> verbatim. For measurement infrastructure,
              dying loudly beats a silently ignored typo.
            </p>

            <h2>Legacy migration and debugging</h2>
            <ul>
              <li>
                <code>geode config migrate-petri-toml</code>. Moves legacy{" "}
                <code>~/.geode/petri.toml</code> role overrides into{" "}
                <code>[self_improving_loop.autoresearch.&lt;role&gt;]</code>.
                Dry-run by default.
              </li>
              <li>
                <code>geode config explain</code>. Shows which layer (CLI, env,
                project toml, global toml) wins for a setting. The answer to
                &quot;I changed the config and nothing moved&quot;.
              </li>
            </ul>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/capabilities/autoresearch">Closed-Loop</a>. The loop body these settings drive.</li>
              <li><a href="/geode/docs/config/reference">Config reference</a>. The full config.toml surface.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
