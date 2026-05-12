"use client";

import { useLocale, t } from "../locale-context";

export function TwoAppsSection() {
  const locale = useLocale();
  return (
    <section className="relative py-24 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="mb-10">
          <div className="text-[10px] font-mono uppercase tracking-[0.22em] text-[var(--ink-3)] mb-3">
            {t(locale, "§ 5. 적용 사례", "§ 5. APPLICATIONS")}
          </div>
          <h2 className="font-display font-bold tracking-tight text-3xl md:text-4xl text-[var(--ink-1)] leading-tight">
            {t(locale, "동일 하네스로 검증한 두 도메인.", "Two domains validated on the same harness.")}
          </h2>
          <p className="mt-4 text-[var(--ink-2)] max-w-3xl leading-relaxed text-[15px]">
            {t(
              locale,
              "운영체제 등급의 시스템이라는 주장은 다른 도메인을 위에 올려 검증할 수 있을 때 의미가 있습니다. GEODE의 Layer 2(Runtime)와 Layer 3(Harness)는 두 앱 사이에서 코드 수정 없이 이전되었습니다. 변경한 부분은 도메인 어댑터뿐입니다.",
              "An OS-grade claim has meaning only when it can be validated by running a different domain on top. GEODE's Layer 2 (Runtime) and Layer 3 (Harness) were transferred between two apps without code modification. Only the domain adapter changed."
            )}
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="rounded-lg border border-[var(--rule)] hover:border-[var(--ink-3)] p-6 transition-colors">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[10px] font-mono uppercase tracking-widest text-[var(--acc-artifact)]">
                {t(locale, "APP 1", "APP 1")} · in-tree plugin
              </span>
            </div>
            <h3 className="font-display font-bold text-2xl text-[var(--ink-1)] mb-2">
              Game IP
            </h3>
            <p className="text-[var(--ink-2)] text-[14px] leading-relaxed mb-4">
              {t(
                locale,
                "저평가 IP를 발굴하는 도메인 플러그인. 4 Analyst (game_mechanics / player_experience / growth_potential / discovery) → 3 Evaluator (quality_judge / hidden_value / community_momentum) → BiasBuster (6 편향) → Synthesizer. 14축 PSM scoring (ATT, Z-value, Rosenbaum Γ).",
                "A plugin for discovering undervalued IP. 4 Analysts → 3 Evaluators → BiasBuster (6 biases) → Synthesizer. 14-axis PSM scoring (ATT, Z-value, Rosenbaum Γ)."
              )}
            </p>
            <div className="space-y-1.5 font-mono text-[12px] text-[var(--ink-2)] mb-4">
              <div><span className="text-[var(--ink-3)]">location · </span>plugins/game_ip/</div>
              <div><span className="text-[var(--ink-3)]">since · </span>v0.6.0 → v0.64.0 plugin split</div>
              <div><span className="text-[var(--ink-3)]">fixtures · </span>3 (Berserk / Cowboy Bebop / Ghost in the Shell)</div>
            </div>
            <div className="rounded border border-[var(--rule)] bg-[var(--code-bg)] p-3 font-mono text-[11.5px] space-y-1">
              <div className="text-[var(--ink-2)]">$ uv run geode analyze &quot;Cowboy Bebop&quot; --dry-run</div>
              <div className="text-[var(--acc-artifact)]/85">→ A (68.4) — undermarketed</div>
              <div className="text-[var(--ink-2)]">$ uv run geode analyze &quot;Berserk&quot; --verbose</div>
              <div className="text-[var(--acc-artifact)]/85">→ S (81.2) — conversion_failure</div>
            </div>
          </div>

          <div className="rounded-lg border border-[var(--rule)] hover:border-[var(--ink-3)] p-6 transition-colors">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[10px] font-mono uppercase tracking-widest text-[var(--acc-line)]">
                {t(locale, "APP 2", "APP 2")} · forked harness
              </span>
            </div>
            <h3 className="font-display font-bold text-2xl text-[var(--ink-1)] mb-2">
              Migration / REODE
            </h3>
            <p className="text-[var(--ink-2)] text-[14px] leading-relaxed mb-4">
              {t(
                locale,
                "GEODE v0.12 fork → Java 1.8 → 22 자율 마이그레이션 에이전트. OpenRewrite (70%, 결정론적) + LLM (30%, 컨텍스트 의존) 하이브리드. 모듈별 자율 세션 격리 + 빌드 기반 피드백 루프.",
                "GEODE v0.12 fork → autonomous Java 1.8 → 22 migration agent. OpenRewrite (70%, deterministic) + LLM (30%, context-dependent) hybrid. Module-isolated autonomous sessions + build-driven feedback loop."
              )}
            </p>
            <div className="space-y-1.5 font-mono text-[12px] text-[var(--ink-2)] mb-4">
              <div><span className="text-[var(--ink-3)]">files · </span>5,523 migrated</div>
              <div><span className="text-[var(--ink-3)]">build · </span>83 / 83 modules pass</div>
              <div><span className="text-[var(--ink-3)]">runtime · </span>5h 48m wall clock</div>
              <div><span className="text-[var(--ink-3)]">cost · </span>$388 LLM</div>
              <div><span className="text-[var(--ink-3)]">sessions · </span>33 autonomous · 1,133 LLM rounds · 34 rounds/module avg</div>
            </div>
            <div className="rounded border border-[var(--rule)] bg-[var(--code-bg)] p-3 font-mono text-[11.5px] space-y-1">
              <div className="text-[var(--ink-2)]">phase 1 — assess</div>
              <div className="text-[var(--ink-2)]">phase 2 — plan</div>
              <div className="text-[var(--ink-2)]">phase 3 — transform (OpenRewrite + LLM)</div>
              <div className="text-[var(--ink-2)]">phase 4 — validate (build + test)</div>
              <div className="text-[var(--acc-artifact)]/85">→ 83 / 83 build pass · 0 manual intervention</div>
            </div>
          </div>
        </div>

        <p className="mt-8 text-[var(--ink-2)] max-w-3xl leading-relaxed text-[14px]">
          {t(
            locale,
            "두 사례는 같은 결론을 가리킵니다. 도메인 어댑터는 교체 가능하며, 그 위의 모든 계층(LLM 라우터, 도구 레지스트리, MCP, 메모리, 검증, hook)은 변경되지 않았습니다. 하네스 일반화 + 도메인 플러그인화라는 설계 가설을 두 데이터 포인트로 검증했습니다.",
            "Both cases reach the same conclusion. The domain adapter is interchangeable, while every layer above it — LLM router, tool registry, MCP, memory, verification, and hooks — was left unchanged. This validates the design hypothesis of harness generalization plus domain pluggability with two data points."
          )}
        </p>
      </div>
    </section>
  );
}
