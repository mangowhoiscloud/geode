"use client";

import { useLocale, t } from "../locale-context";

const wires = [
  {
    provider: "Anthropic",
    model: "Opus 4.7",
    effortKwarg: "output_config.effort = \"xhigh\"",
    summaryKwarg: "thinking.display = \"summarized\"",
    replay: "thinking blocks (always-replayed)",
    geode: "v0.56.0 R4-mini",
    note: "Opus 4.7 only; 4.6 / Sonnet 4.6 reject xhigh → downgrade to max",
  },
  {
    provider: "OpenAI Responses (PAYG)",
    model: "gpt-5.5",
    effortKwarg: "reasoning.effort = \"high\" / \"xhigh\"",
    summaryKwarg: "reasoning.summary = \"auto\"",
    replay: "include=[\"reasoning.encrypted_content\"]",
    geode: "v0.60.0 R3-mini",
    note: "store=False explicit; matches Codex Plus parity",
  },
  {
    provider: "OpenAI Codex Plus (subscription)",
    model: "gpt-5.5 / gpt-5.4 / mini",
    effortKwarg: "reasoning.effort",
    summaryKwarg: "(server adds reasoning_summaries)",
    replay: "codex_reasoning_items sidecar replay",
    geode: "v0.55.0 R1",
    note: "shared inject_reasoning_replay() walker (also used by R3-mini PAYG)",
  },
  {
    provider: "GLM (Zhipu)",
    model: "GLM-4.5+ family",
    effortKwarg: "(hybrid binary)",
    summaryKwarg: "extra_body.thinking.type = \"enabled\"",
    replay: "message.reasoning_content (clear_thinking=False)",
    geode: "v0.58.0 R2",
    note: "GEODE-only globally — Hermes / OpenClaw / Claude Code don't activate this field",
  },
];

export function ComputeAbiSection() {
  const locale = useLocale();
  return (
    <section className="relative py-24 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="mb-10">
          <div className="text-[10px] font-mono uppercase tracking-[0.22em] text-[var(--ink-3)] mb-3">
            {t(locale, "§ 4A. 추론 ABI", "§ 4A. REASONING ABI")}
          </div>
          <h2 className="font-display font-bold tracking-tight text-3xl md:text-4xl text-[var(--ink-1)] leading-tight">
            {t(locale, "프로바이더 4종을 단일 ABI로 정렬.", "Aligning four providers under a single ABI.")}
          </h2>
          <p className="mt-4 text-[var(--ink-2)] max-w-3xl leading-relaxed text-[15px]">
            {t(
              locale,
              "v0.55부터 v0.62까지 9차례 reasoning depth audit을 진행했습니다. 네 프로바이더가 reasoning 정보를 와이어에 싣는 방식이 서로 달라, 같은 모델도 어댑터에 따라 노출되는 사고 깊이가 일관되지 않았습니다. R1부터 R9까지 9차례 사이클로 이 차이를 정렬했습니다. R6에서는 사고 요약을 IPC 이벤트로 스트리밍해 ‘thinking…’ 상태를 사용자에게 실시간으로 표시하도록 했고, R9에서는 라이브 와이어 테스트로 전체 변경을 회귀 검증했습니다.",
              "From v0.55 to v0.62, 9 reasoning depth audit cycles were shipped. The four providers carry reasoning data on the wire differently, and the same model showed inconsistent reasoning depth depending on the adapter. R1 to R9 aligned these differences. R6 streams reasoning summaries over IPC events, surfacing the “thinking…” state to the user in real time. R9 covers all changes with live wire regression tests."
            )}
          </p>
        </div>

        <div className="rounded-lg border border-[var(--rule)] overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-[var(--rule)] bg-[var(--paper-2)]">
                <th className="text-left p-3 font-mono uppercase tracking-wider text-[10px] text-[var(--ink-2)]">
                  {t(locale, "Provider / 모델", "Provider / Model")}
                </th>
                <th className="text-left p-3 font-mono uppercase tracking-wider text-[10px] text-[var(--ink-2)]">
                  Effort
                </th>
                <th className="text-left p-3 font-mono uppercase tracking-wider text-[10px] text-[var(--ink-2)]">
                  Summary surface
                </th>
                <th className="text-left p-3 font-mono uppercase tracking-wider text-[10px] text-[var(--ink-2)]">
                  Multi-turn replay
                </th>
                <th className="text-left p-3 font-mono uppercase tracking-wider text-[10px] text-[var(--ink-2)]">
                  GEODE
                </th>
              </tr>
            </thead>
            <tbody>
              {wires.map((w, i) => (
                <tr key={i} className="border-b border-[var(--rule-soft)] hover:bg-[var(--paper-2)] transition-colors align-top">
                  <td className="p-3">
                    <div className="text-[var(--ink-1)] font-medium">{w.provider}</div>
                    <div className="text-[var(--ink-2)] text-[12px] mt-0.5">{w.model}</div>
                  </td>
                  <td className="p-3 font-mono text-[11.5px] text-[var(--acc-artifact)]">{w.effortKwarg}</td>
                  <td className="p-3 font-mono text-[11.5px] text-[var(--acc-artifact)]">{w.summaryKwarg}</td>
                  <td className="p-3 font-mono text-[11.5px] text-[var(--acc-artifact)]/85">{w.replay}</td>
                  <td className="p-3">
                    <div className="font-mono text-[11px] text-[var(--acc-artifact)]">{w.geode}</div>
                    <div className="text-[var(--ink-2)] text-[11px] mt-1 leading-snug">{w.note}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="mt-6 text-[var(--ink-2)] max-w-3xl leading-relaxed text-[14px]">
          {t(
            locale,
            "GLM의 thinking 필드를 활성화한 사례는 다른 프론티어 시스템에서 확인되지 않았습니다. Hermes는 GLM을 일반 chat_completions 경로로 라우팅하고, OpenClaw는 GLM 플러그인이 없으며, Claude Code는 Anthropic만 지원합니다. v0.58.0의 R2 사이클에서 GEODE가 이 기능을 도입했습니다.",
            "No other frontier system was found activating GLM's thinking field. Hermes routes GLM through a generic chat_completions path, OpenClaw has no GLM plugin, and Claude Code only supports Anthropic. GEODE introduced this in the R2 cycle (v0.58.0)."
          )}
        </p>
      </div>
    </section>
  );
}
