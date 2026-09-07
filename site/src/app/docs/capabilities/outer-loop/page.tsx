import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Crucible bounded search — GEODE Docs" };

function CrucibleLoop({ ko }: { ko: boolean }) {
  const loop = [
    ["Private search head", "refs/crucible/search/<campaign>"],
    ["Candidate producer", "disposable · no remote"],
    ["Import + preflight", "fresh measurement checkout"],
    ["Evaluator", "baseline first · candidate if reachable"],
    ["Pure decide()", "reachability · bootstrap · veto"],
  ];

  return (
    <figure aria-labelledby="crucible-loop-title" className="my-10">
      <figcaption id="crucible-loop-title" className="mb-3 font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
        Crucible bounded search loop
      </figcaption>
      <div className="border-y border-[var(--rule)] py-6">
        <div className="mb-7 grid gap-3 bg-[var(--paper-2)] p-4 md:grid-cols-[10rem_1fr]">
          <strong className="font-mono text-xs uppercase tracking-[0.14em] text-[var(--section-accent)]">prepare_campaign()</strong>
          <span className="text-sm text-[var(--ink-2)]">
            {ko
              ? "task pack · evaluator identity · promotion rule · power · quota · runtime budget 동결"
              : "Freeze task pack · evaluator identity · promotion rule · power · quota · runtime budget"}
          </span>
        </div>

        <div className="flex flex-col items-stretch gap-2 lg:flex-row lg:items-center">
          {loop.map(([title, detail], index) => (
            <div key={title} className="contents">
              <div className="min-w-0 flex-1 border-t border-[var(--rule-soft)] px-3 py-4 lg:min-h-28">
                <span className="font-mono text-[10px] text-[var(--ink-3)]">{String(index + 1).padStart(2, "0")}</span>
                <strong className="mt-2 block text-sm">{title}</strong>
                <span className="mt-1 block break-words font-mono text-[10px] leading-relaxed text-[var(--ink-3)]">{detail}</span>
              </div>
              {index < loop.length - 1 && <span aria-hidden="true" className="hidden shrink-0 text-[var(--ink-3)] lg:block">→</span>}
            </div>
          ))}
        </div>

        <div className="mt-4 grid gap-2 text-xs md:grid-cols-[1fr_auto_1fr_auto_1fr] md:items-center">
          <div className="bg-[var(--paper-2)] p-3"><strong>{ko ? "baseline evidence" : "Baseline evidence"}</strong></div>
          <span aria-hidden="true" className="hidden text-[var(--ink-3)] md:block">→</span>
          <div className="bg-[var(--paper-2)] p-3"><strong>{ko ? "KEEP 도달 가능성" : "KEEP reachability"}</strong></div>
          <span aria-hidden="true" className="hidden text-[var(--ink-3)] md:block">→</span>
          <div className="grid gap-1">
            <span className="bg-[color-mix(in_srgb,var(--section-accent)_9%,transparent)] p-2">
              {ko ? "reachable → candidate 평가" : "Reachable → evaluate candidate"}
            </span>
            <span className="bg-[var(--paper-2)] p-2">
              {ko ? "unreachable → zero-call REJECT" : "Unreachable → zero-call REJECT"}
            </span>
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div className="bg-[color-mix(in_srgb,var(--section-accent)_9%,transparent)] p-4">
            <strong className="text-sm">KEEP</strong>
            <p className="!mb-0 !mt-1 text-sm text-[var(--ink-2)]">{ko ? "CAS로 private search ref 전진" : "CAS advances the private search ref"}</p>
          </div>
          <div className="bg-[var(--paper-2)] p-4">
            <strong className="text-sm">REJECT / INVALID</strong>
            <p className="!mb-0 !mt-1 text-sm text-[var(--ink-2)]">{ko ? "search head 유지" : "Search head remains unchanged"}</p>
          </div>
        </div>

        <div className="mt-3 grid gap-3 border-t border-[var(--rule-soft)] pt-4 md:grid-cols-[1fr_auto_1fr] md:items-center">
          <div>
            <strong className="text-sm">record · ledger · feedback</strong>
            <p className="!mb-0 !mt-1 text-xs text-[var(--ink-3)]">{ko ? "모든 판정과 비용을 append-only 기록" : "Append every verdict and resource receipt"}</p>
          </div>
          <span aria-hidden="true" className="hidden text-[var(--ink-3)] md:block">→</span>
          <div>
            <strong className="text-sm">limits: attempts · wall · cost</strong>
            <p className="!mb-0 !mt-1 text-xs text-[var(--ink-3)]">{ko ? "여유가 있으면 다음 candidate, 소진되면 summary.json" : "Continue with capacity; otherwise write summary.json"}</p>
          </div>
        </div>
      </div>

      <div className="mt-5 border-l-2 border-dashed border-[var(--rule)] pl-4">
        <p className="!m-0 font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
          {ko ? "적응 루프 밖의 권한 경계" : "Authority boundary outside the adaptive loop"}
        </p>
        <p className="!mb-0 !mt-2 text-sm text-[var(--ink-2)]">
          {ko
            ? "train KEEP은 loop-local head만 갱신합니다. disjoint one-shot sealed test가 ELIGIBLE 여부를 기록하고, production release는 별도 승인 경로에 남습니다."
            : "A train KEEP updates only the loop-local head. A disjoint one-shot sealed test records eligibility, while production release stays on a separate approval path."}
          {" "}<code>promotion_authority=none</code>
        </p>
      </div>
    </figure>
  );
}

export default function Page() {
  return (
    <DocsShell
      wide
      slug="capabilities/outer-loop"
      title="Crucible bounded search"
      titleKo="Crucible 제한형 탐색"
      summary="A bounded private search loop with frozen admission, paired evaluation, CAS advancement, and a separate sealed-test boundary."
      summaryKo="동결된 admission, paired 평가, CAS 전진, 별도 sealed-test 경계를 갖춘 제한형 private search 루프입니다."
    >
      <Bi
        ko={
          <>
            <h2>Crucible bounded search</h2>
            <p>
              Crucible은 후보 생성, 신뢰된 paired 평가, 판정, private ref 갱신을
              하나의 제한된 반복으로 묶습니다. 실행 전에 측정 정체성과 자원을
              동결하고, 각 반복의 KEEP·REJECT·INVALID와 비용을 원장에 남깁니다.
            </p>
            <CrucibleLoop ko />
            <p>
              실행 진입점은 <code>geode-evolve crucible loop &lt;config&gt;</code>입니다.
              <code>geode-evolve crucible prepare</code>가 선언형 명세를 검증해
              campaign 설정을 준비합니다. 이 설정은 아래의 스캐폴드·Petri용 TOML과
              별개이며, KEEP은 private search head만 갱신하고 배포를 승인하지 않습니다.
            </p>

            <h2>스캐폴드 탐색과 Petri의 공통 설정</h2>
            <p>
              스캐폴드 탐색과 Petri 감사는 역할이 많습니다. auditor, target, judge, mutator가
              각각 모델과 자격 lane을 갖고, seed 풀과 promote 정책과 스케줄러
              knob이 더해집니다. 이것이 env, 모듈 상수, 별도 TOML로 흩어지면
              &quot;지금 루프가 실제로 무엇으로 도는가&quot;를 답할 수 없게 됩니다.
              이 역할 설정과 기본값은 <code>~/.geode/config.toml</code>의{" "}
              <code>[self_improving_loop]</code> 섹션 한 곳에 모았고, 로더는{" "}
              <code>evals/config.py</code>의{" "}
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
seed_select = "bundled"
dim_set = "subset"            # 22-dim 루브릭
max_turns = 10
promote_policy = "gate"       # gate / random / never
replicate = 1                 # 감사 반복 M

[self_improving_loop.autoresearch.target]    # judge / auditor 동일 형태
model = "..."
source = "api_key"            # 자격 lane

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
              <code>evals/config.py</code>가 SoT입니다. 위 수치와 정책은
              스키마 기본값이며, <code>model = &quot;...&quot;</code>은 실제 모델 ID로
              교체해야 하는 자리 표시자입니다.
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
                <code>geode-eval config migrate-petri-toml</code>. 옛{" "}
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
              <li><a href="/geode/docs/capabilities/autoresearch">스캐폴드 탐색</a>. 공통 TOML 설정을 소비하는 루프.</li>
              <li><a href="/geode/docs/config/reference">설정 레퍼런스</a>. config.toml 전체 표면.</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Crucible bounded search</h2>
            <p>
              Crucible joins candidate production, trusted paired evaluation,
              decision, and private-ref advancement in one bounded loop. It
              freezes measurement identity and resources before execution, then
              records every KEEP, REJECT, INVALID, and resource receipt.
            </p>
            <CrucibleLoop ko={false} />
            <p>
              The execution entry point is <code>geode-evolve crucible loop &lt;config&gt;</code>.
              <code>geode-evolve crucible prepare</code> validates a declarative spec
              and prepares the campaign configuration. This is separate from the
              scaffold/Petri TOML below. KEEP advances only the private search head;
              it does not authorize a release.
            </p>

            <h2>Shared scaffold-search and Petri configuration</h2>
            <p>
              Scaffold search and Petri audits use several roles: auditor, target, judge, and
              mutator each carry a model and a credential lane, plus seed
              pools, promote policy, and scheduler knobs. Scattered across env
              vars, module constants, and side TOML files, the question
              &quot;what is the loop actually running with right now&quot;
              becomes unanswerable. These role settings and defaults live in the{" "}
              <code>[self_improving_loop]</code> section of{" "}
              <code>~/.geode/config.toml</code>, loaded by{" "}
              <code>load_self_improving_loop_config</code> in{" "}
              <code>evals/config.py</code>.
            </p>

            <h2>Schema sketch</h2>
            <pre>{`[self_improving_loop]
fallback_to_payg = false      # deny PAYG fallback on subscription exhaust
warn_threshold = 0.5          # usage warning threshold
abort_threshold = 0.9         # usage abort threshold

[self_improving_loop.autoresearch]
budget_minutes = 5            # wall-clock budget per experiment
seed_limit = 10               # seeds per audit
seed_select = "bundled"
dim_set = "subset"            # the 22-dim rubric
max_turns = 10
promote_policy = "gate"       # gate / random / never
replicate = 1                 # audit replicates M

[self_improving_loop.autoresearch.target]    # judge / auditor same shape
model = "..."
source = "api_key"            # credential lane

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
              <code>evals/config.py</code>. Numeric and policy values above are
              schema defaults; <code>model = &quot;...&quot;</code> is a placeholder
              that requires a real model ID.
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
                <code>geode-eval config migrate-petri-toml</code>. Moves legacy{" "}
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
              <li><a href="/geode/docs/capabilities/autoresearch?lang=en">Scaffold search</a>. The loop that consumes the shared TOML settings.</li>
              <li><a href="/geode/docs/config/reference?lang=en">Config reference</a>. The full config.toml surface.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
