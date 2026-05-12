"use client";

import { useLocale, t } from "../locale-context";

const mappings = [
  {
    karpathy: "LLM (kernel/CPU)",
    geode: "Layer 1 — Model",
    geodeDetail: "4 providers × 14 models",
    geodeFile: "core/llm/providers/{anthropic,openai,codex,glm}.py",
  },
  {
    karpathy: "Tools (browser, calc, python)",
    geode: "Layer 2 — Tools",
    geodeDetail: "57 tools (6 always-loaded + 51 deferred)",
    geodeFile: "core/tools/registry.py:209",
  },
  {
    karpathy: "File system (memory)",
    geode: "Layer 2 — Memory",
    geodeDetail: "5-tier ContextAssembler",
    geodeFile: "core/memory/context.py:46",
  },
  {
    karpathy: "Network",
    geode: "Layer 2 — MCP",
    geodeDetail: "16 MCP servers + 25K token guard",
    geodeFile: "core/mcp/manager.py",
  },
  {
    karpathy: "Other LLMs (parallel)",
    geode: "Layer 4 — Sub-agents",
    geodeDetail: "MAX_CONCURRENT=5 + SessionLane",
    geodeFile: "core/agent/loop.py + core/agent/subagent.py",
  },
  {
    karpathy: "Embedding spaces",
    geode: "experimental/",
    geodeDetail: "RAPTOR + progressive compression (opt-in)",
    geodeFile: "experimental/embeddings.py",
  },
  {
    karpathy: "I/O (audio, video)",
    geode: "Computer Use",
    geodeDetail: "Anthropic + OpenAI unified",
    geodeFile: "core/tools/computer_use.py",
  },
  {
    karpathy: "(implicit) Init / PID 1",
    geode: "Layer 3 — Serve daemon",
    geodeDetail: "Thin CLI → IPC → serve",
    geodeFile: "core/server/ + core/cli/",
  },
  {
    karpathy: "(implicit) Shell + syscall ABI",
    geode: "Layer 3 — Slash commands + Tool protocol",
    geodeDetail: "/model /stop /clean /uninstall /status + 57 tools",
    geodeFile: "core/cli/commands.py:41 + core/tools/base.py:35",
  },
  {
    karpathy: "(implicit) IPC / dbus / journald",
    geode: "Layer 3 — Hooks + IPC events",
    geodeDetail: "58 hook events + structured IPC",
    geodeFile: "core/hooks/system.py:28",
  },
];

export function OsPrimitivesMapSection() {
  const locale = useLocale();
  return (
    <section className="relative py-24 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="mb-10">
          <div className="text-[10px] font-mono uppercase tracking-[0.22em] text-[var(--ink-3)] mb-3">
            {t(locale, "§ 2. 구성요소 매핑", "§ 2. PRIMITIVES MAPPING")}
          </div>
          <h2 className="font-display font-bold tracking-tight text-3xl md:text-4xl text-[var(--ink-1)] leading-tight">
            {t(locale, "LLM-OS 다이어그램을 코드로 매핑.", "Mapping the LLM-OS diagram to code.")}
          </h2>
          <p className="mt-4 text-[var(--ink-2)] max-w-3xl leading-relaxed text-[15px]">
            {t(
              locale,
              "카르파시가 제시한 LLM-OS 다이어그램의 각 구성요소를 GEODE의 실제 모듈에 매핑한 결과입니다. 13개 구성요소가 모두 코드베이스에 존재하며, 거의 일대일 대응 관계를 보입니다. 운영체제 등급의 시스템이라는 표현이 비유로 끝나지 않는 근거입니다.",
              "Each component from Karpathy's LLM-OS diagram is mapped here to an actual module in GEODE. All 13 components exist in the codebase with near one-to-one correspondence. This is the basis for treating “OS-grade system” as more than a metaphor."
            )}
          </p>
        </div>

        <div className="rounded-lg border border-[var(--rule)] overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-[var(--rule)] bg-[var(--paper-2)]">
                <th className="text-left p-3 font-mono uppercase tracking-wider text-[10px] text-[var(--ink-2)] w-[28%]">
                  {t(locale, "Karpathy LLM OS (2023)", "Karpathy LLM OS (2023)")}
                </th>
                <th className="text-left p-3 font-mono uppercase tracking-wider text-[10px] text-[var(--ink-2)] w-[22%]">
                  {t(locale, "GEODE Layer", "GEODE Layer")}
                </th>
                <th className="text-left p-3 font-mono uppercase tracking-wider text-[10px] text-[var(--ink-2)] w-[28%]">
                  {t(locale, "구현 디테일", "Implementation")}
                </th>
                <th className="text-left p-3 font-mono uppercase tracking-wider text-[10px] text-[var(--ink-2)] w-[22%]">
                  {t(locale, "파일", "File")}
                </th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((row, i) => (
                <tr key={i} className="border-b border-[var(--rule-soft)] hover:bg-[var(--paper-2)] transition-colors">
                  <td className="p-3 text-[var(--ink-1)]">{row.karpathy}</td>
                  <td className="p-3 text-[var(--acc-artifact)] font-medium">{row.geode}</td>
                  <td className="p-3 text-[var(--ink-2)]">{row.geodeDetail}</td>
                  <td className="p-3 font-mono text-[11px] text-[var(--acc-artifact)]/85">{row.geodeFile}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="mt-4 text-[12px] text-[var(--ink-3)]">
          {t(
            locale,
            "참고: Andrej Karpathy, “[1hr Talk] Intro to Large Language Models” (2023년 11월).",
            "Reference: Andrej Karpathy, “[1hr Talk] Intro to Large Language Models” (November 2023)."
          )}
        </p>
      </div>
    </section>
  );
}
