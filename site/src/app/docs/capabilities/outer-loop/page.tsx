import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Outer-Loop Config — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="capabilities/outer-loop"
      title="Outer-Loop Config"
      titleKo="아우터 루프 설정"
      summary="The autoresearch + seed-pipeline + petri trio share one config root in ~/.geode/config.toml. Pydantic v2 schema, strict mode by default."
      summaryKo="autoresearch + seed-pipeline + petri 세 축의 outer-loop 설정을 ~/.geode/config.toml 한 곳에 모았습니다. pydantic v2 스키마, strict mode 가 기본."
    >
      <Bi
        ko={
          <>
            <h2>왜 outer-loop 설정이 분리되어 있나</h2>
            <p>
              `core/config/outer_loop.py` 는 inner-loop (AgenticLoop, model selection) 와 분리된 outer-loop 의 설정 root 입니다. autoresearch (자가 ML 실험 루프) + seed-pipeline (재귀적 seed 생성) + petri (alignment audit) 세 시스템이 공유하는 임계값을 한 곳에 둠으로써 8 군데에 흩어져 있던 설정(모듈 상수 2 + TOML 2 + env vars + manifest + auth.toml + codex auth.json) 을 단일 SOT 로 통합합니다.
            </p>

            <h2>스키마</h2>
            <pre>{`[outer_loop]
fallback_to_payg = false      # subscription 소진 시 PAYG api_key 폴백 차단 (strict)
warn_threshold = 0.5          # 사용량 50% 시 노란 경고
abort_threshold = 0.9         # 사용량 90% 시 abort

[outer_loop.autoresearch]
# autoresearch/train.py 의 9-col tsv outer-loop 임계값

[outer_loop.petri]
credential_source = "oauth"   # OAuth subscription 만 사용

[outer_loop.seed_pipeline]
# Session 63 cycle 의 generation 임계값

[outer_loop.bindings]
# slack/discord/telegram poller binding`}</pre>

            <h2>로드 경로</h2>
            <p>
              `load_outer_loop_config(path?)` 가 우선순위: (1) 명시적 path 인자, (2) `GEODE_CONFIG_TOML` env, (3) `~/.geode/config.toml`. 파일/섹션 누락 시 기본값 모델 반환. `extra='forbid'` 로 오타는 즉시 에러.
            </p>

            <h2>Phase α-ζ 작업</h2>
            <p>
              본 페이지가 다루는 PR-α1 (#1308) 은 schema + loader 만. 후속 Phase β/γ/δ/ε/ζ 는 subscription guard + FE warning UX (prompt_toolkit bottom_toolbar 3-tier) + SessionCheckpoint resume + idempotency-key cache. 자세한 로드맵은 `docs/plans/2026-05-19-outer-loop-config-consolidation.md`.
            </p>

            <h2>관련 코드 + 참조</h2>
            <ul>
              <li><code>core/config/outer_loop.py</code> (PR-α1 #1308, 16 unit tests)</li>
              <li><code>docs/architecture/outer-loop-resume-decision.md</code> (Phase ζ ADR)</li>
              <li><code>docs/plans/2026-05-19-outer-loop-config-consolidation.md</code></li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Why the outer loop has its own config</h2>
            <p>
              `core/config/outer_loop.py` is the config root for the outer loop, separate from the inner AgenticLoop. autoresearch (self-driving ML loop), seed-pipeline (recursive seed generation), and petri (alignment audit) share the same thresholds. Before PR-α1 (#1308) those settings lived in eight surfaces. They now collapse into one TOML file.
            </p>

            <h2>Schema</h2>
            <pre>{`[outer_loop]
fallback_to_payg = false      # deny PAYG api_key fallback on subscription exhaust
warn_threshold = 0.5
abort_threshold = 0.9

[outer_loop.autoresearch]
[outer_loop.petri]
credential_source = "oauth"
[outer_loop.seed_pipeline]
[outer_loop.bindings]`}</pre>

            <h2>Load path</h2>
            <p>
              `load_outer_loop_config(path?)` resolves in order: explicit arg, `GEODE_CONFIG_TOML` env, `~/.geode/config.toml`. Missing file or section returns the default-filled model. `extra='forbid'` rejects typos.
            </p>

            <h2>Phase α-ζ work</h2>
            <p>
              This page covers PR-α1 (#1308). Remaining phases add subscription guard, prompt_toolkit bottom_toolbar warning UX, SessionCheckpoint resume, and idempotency-key cache. The full plan lives in `docs/plans/2026-05-19-outer-loop-config-consolidation.md`.
            </p>

            <h2>Code references</h2>
            <ul>
              <li><code>core/config/outer_loop.py</code> (PR-α1 #1308, 16 unit tests)</li>
              <li><code>docs/architecture/outer-loop-resume-decision.md</code> (Phase ζ ADR)</li>
              <li><code>docs/plans/2026-05-19-outer-loop-config-consolidation.md</code></li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
