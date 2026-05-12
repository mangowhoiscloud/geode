"use client";

import { useLocale, t } from "../locale-context";

const features = [
  {
    title: "Plan-aware quota panel",
    titleKo: "플랜 인식 쿼터 패널",
    body: "BillingError carries provider / plan_id / display_name / upgrade_url / resets_in_seconds. The thin client renders a 3-action panel (wait / switch auth / switch provider) instead of a one-line 'Billing error'. No silent cross-provider failover.",
    bodyKo: "BillingError 에 provider/plan_id/upgrade_url/resets_in 메타가 실려, thin client 가 3-액션 패널 (대기 / 인증 전환 / 프로바이더 전환) 을 렌더한다. 한 줄 'Billing error' 가 아니라. 자동 cross-provider 전환은 명시적 결정으로.",
    since: "v0.53.0",
    file: "core/llm/errors.py:BillingError + ui/agentic_ui.py:emit_quota_exhausted",
  },
  {
    title: "Equivalence-class routing",
    titleKo: "동등성 클래스 라우팅",
    body: "PROVIDER_EQUIVALENCE map declares sibling classes (openai ↔ openai-codex, glm ↔ glm-coding). PLAN_KIND_PRIORITY ranks SUBSCRIPTION → OAUTH_BORROWED → CLOUD → PAYG. resolve_routing() scans siblings, returns first available by priority.",
    bodyKo: "PROVIDER_EQUIVALENCE 맵이 sibling 클래스 (openai ↔ openai-codex, glm ↔ glm-coding) 을 선언. PLAN_KIND_PRIORITY 가 SUBSCRIPTION → OAUTH_BORROWED → CLOUD → PAYG 순서. resolve_routing() 이 sibling 을 스캔해 우선순위 순으로 첫 가용 프로파일 반환.",
    since: "v0.52.4",
    file: "core/auth/plans.py + core/llm/registry.py",
  },
  {
    title: "Credential breadcrumb",
    titleKo: "자격증명 breadcrumb",
    body: "When all profiles for the active provider are rejected, GEODE injects a one-line 'cross-provider: openai-codex(codex-cli); anthropic(default)' into LLM context — letting the LLM (or user) see what other healthy auth exists, without auto-failing-over.",
    bodyKo: "활성 프로바이더의 모든 profile 이 거부됐을 때, 다른 프로바이더의 healthy profile 을 LLM 컨텍스트에 한 줄로 주입 ('cross-provider: openai-codex(codex-cli); anthropic(default)'). LLM/사용자가 등록된 다른 인증의 존재를 볼 수 있게 — 자동 전환은 안 함.",
    since: "v0.52.3",
    file: "core/auth/credential_breadcrumb.py",
  },
  {
    title: "Two-axis /model picker",
    titleKo: "Two-axis /model 피커",
    body: "Cursor ↑↓ for model + ←→ for effort. Per-provider effort enum (Anthropic adaptive: low/medium/high/max/xhigh; OpenAI Responses: none/minimal/low/medium/high/xhigh; GLM hybrid binary: disabled/enabled). Persists to .geode/config.toml + GEODE_AGENTIC_EFFORT env.",
    bodyKo: "↑↓ 모델 / ←→ effort. 프로바이더별 effort enum (Anthropic adaptive: low/medium/high/max/xhigh; OpenAI Responses: 6단; GLM 이진). 선택값은 .geode/config.toml + 환경변수에 영속.",
    since: "v0.59.0",
    file: "core/cli/effort_picker.py + core/cli/commands.py:_apply_model",
  },
  {
    title: "Anthropic 4-breakpoint cache",
    titleKo: "Anthropic 4-breakpoint 캐시",
    body: "system block STATIC/DYNAMIC split (__GEODE_PROMPT_CACHE_BOUNDARY__) + apply_messages_cache_control on last 3 non-system messages. Fills Anthropic's 4 cache_control slots — Hermes system_and_3 parity. Reduces input cost in long multi-turn loops.",
    bodyKo: "시스템 블록 STATIC/DYNAMIC 분할 (__GEODE_PROMPT_CACHE_BOUNDARY__) + 마지막 3 non-system 메시지에 cache_control 적용. Anthropic 의 4 슬롯 모두 활용 — Hermes system_and_3 parity. 긴 멀티턴에서 입력 비용 절감.",
    since: "Unreleased (PR #864)",
    file: "core/llm/providers/anthropic.py:175 + :501",
  },
];

export function RoutingIqSection() {
  const locale = useLocale();
  return (
    <section className="relative py-24 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="mb-10">
          <div className="text-[10px] font-mono uppercase tracking-[0.22em] text-[var(--ink-3)] mb-3">
            {t(locale, "§ 4B. 라우팅", "§ 4B. ROUTING")}
          </div>
          <h2 className="font-display font-bold tracking-tight text-3xl md:text-4xl text-[var(--ink-1)] leading-tight">
            {t(locale, "fallback chain 위의 의사결정 계층.", "A decision layer on top of the fallback chain.")}
          </h2>
          <p className="mt-4 text-[var(--ink-2)] max-w-3xl leading-relaxed text-[15px]">
            {t(
              locale,
              "fallback chain만으로는 멀티 프로바이더 환경의 의사결정을 다룰 수 없습니다. 어느 프로바이더의 어느 플랜으로 호출을 보낼지, 거부 응답이 돌아왔을 때 사용자에게 어떤 옵션을 제시할지, 긴 멀티턴 세션에서 토큰 비용을 어떻게 절감할지 결정해야 합니다. GEODE는 chain 위에 별도의 의사결정 계층을 두어 이 문제를 다룹니다.",
              "A fallback chain alone is not enough to handle decisions in a multi-provider environment. The system has to decide which provider and which plan to call, what options to surface when a request is rejected, and how to control token cost in long multi-turn sessions. GEODE adds a dedicated decision layer on top of the chain to handle this."
            )}
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {features.map((f, i) => (
            <div
              key={i}
              className="rounded-lg border border-[var(--rule)] hover:border-[var(--ink-3)] p-5 transition-colors"
            >
              <div className="flex items-baseline justify-between gap-3 mb-2">
                <h3 className="font-display font-semibold text-[var(--ink-1)] text-[17px] leading-tight">
                  {locale === "ko" ? f.titleKo : f.title}
                </h3>
                <span className="text-[10px] font-mono text-[var(--acc-artifact)] whitespace-nowrap">
                  {f.since}
                </span>
              </div>
              <p className="text-[13px] text-[var(--ink-2)] leading-relaxed mb-3">
                {locale === "ko" ? f.bodyKo : f.body}
              </p>
              <div className="font-mono text-[11px] text-[var(--acc-artifact)]/85">
                {f.file}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
