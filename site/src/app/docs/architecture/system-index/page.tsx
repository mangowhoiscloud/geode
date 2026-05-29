"use client";

import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import { GEODE_SOT } from "@/data/geode/sot";

export default function Page() {
  return (
    <DocsShell
      slug="architecture/system-index"
      title="System Index"
      titleKo="시스템 색인"
      summary={`Every first-class subsystem in GEODE v${GEODE_SOT.version}. Root path and main entry point per subsystem.`}
      summaryKo={`GEODE v${GEODE_SOT.version}의 모든 1급 서브시스템. 서브시스템별 루트 경로와 주요 진입점.`}
    >
      <Bi
        ko={
          <>
            <h2>L4 Agent</h2>
            <table>
              <thead><tr><th>서브시스템</th><th>루트</th><th>진입점</th></tr></thead>
              <tbody>
                <tr><td><strong>agent</strong></td><td><code>core/agent/</code></td><td><code>loop.py:162 AgenticLoop</code></td></tr>
              </tbody>
            </table>

            <h2>L3 Harness</h2>
            <table>
              <thead><tr><th>서브시스템</th><th>루트</th><th>진입점</th></tr></thead>
              <tbody>
                <tr><td>cli</td><td><code>core/cli/</code></td><td><code>commands.py:41 ModelProfile</code></td></tr>
                <tr><td>gateway</td><td><code>core/cli/serve/</code></td><td><code>geode serve</code></td></tr>
                <tr><td>hooks</td><td><code>core/hooks/</code></td><td><code>system.py:200 HookSystem</code></td></tr>
                <tr><td>wiring</td><td><code>core/wiring/</code></td><td>bootstrap entry (v0.87.0 lifecycle → wiring rename)</td></tr>
                <tr><td>channels</td><td><code>core/channels/</code></td><td>adapter classes</td></tr>
                <tr><td>ui</td><td><code>core/ui/</code></td><td>spinners, progress</td></tr>
              </tbody>
            </table>

            <h2>L2 Runtime</h2>
            <table>
              <thead><tr><th>서브시스템</th><th>루트</th><th>진입점</th></tr></thead>
              <tbody>
                <tr><td>llm</td><td><code>core/llm/</code></td><td><code>agentic_response.py:46</code></td></tr>
                <tr><td>llm/prompts</td><td><code>core/llm/prompts/</code></td><td><code>__init__.py</code></td></tr>
                <tr><td>llm/providers</td><td><code>core/llm/providers/</code></td><td><code>anthropic.py</code></td></tr>
                <tr><td>tools</td><td><code>core/tools/</code></td><td><code>base.py:35 Tool</code></td></tr>
                <tr><td>mcp</td><td><code>core/mcp/</code></td><td><code>manager.py MCPManager</code></td></tr>
                <tr><td>memory</td><td><code>core/memory/</code></td><td><code>context.py:46</code></td></tr>
                <tr><td>skills</td><td><code>core/skills/</code></td><td><code>skill_registry.py</code></td></tr>
                <tr><td>verification</td><td><code>core/verification/</code></td><td><code>guardrails.py</code></td></tr>
                <tr><td>scheduler</td><td><code>core/scheduler/</code></td><td><code>scheduler.py:76</code></td></tr>
                <tr><td>automation</td><td><code>core/automation/</code></td><td><code>model_registry.py</code></td></tr>
                <tr><td>orchestration</td><td><code>core/orchestration/</code></td><td><code>graph.py</code></td></tr>
                <tr><td>auth</td><td><code>core/auth/</code></td><td>OAuth profile rotator</td></tr>
              </tbody>
            </table>

            <h2>번들 플러그인</h2>
            <table>
              <thead><tr><th>플러그인</th><th>루트</th><th>주요 구성</th></tr></thead>
              <tbody>
                <tr>
                  <td><strong>petri_audit</strong></td>
                  <td><code>plugins/petri_audit/</code></td>
                  <td>Petri × GEODE alignment audit runner, seed catalog, judge dimensions</td>
                </tr>
              </tbody>
            </table>
          </>
        }
        en={
          <>
            <h2>L4 Agent</h2>
            <table>
              <thead><tr><th>Subsystem</th><th>Root</th><th>Entry</th></tr></thead>
              <tbody>
                <tr><td><strong>agent</strong></td><td><code>core/agent/</code></td><td><code>loop.py:162 AgenticLoop</code></td></tr>
              </tbody>
            </table>

            <h2>L3 Harness</h2>
            <table>
              <thead><tr><th>Subsystem</th><th>Root</th><th>Entry</th></tr></thead>
              <tbody>
                <tr><td>cli</td><td><code>core/cli/</code></td><td><code>commands.py:41 ModelProfile</code></td></tr>
                <tr><td>gateway</td><td><code>core/cli/serve/</code></td><td><code>geode serve</code></td></tr>
                <tr><td>hooks</td><td><code>core/hooks/</code></td><td><code>system.py:200 HookSystem</code></td></tr>
                <tr><td>wiring</td><td><code>core/wiring/</code></td><td>bootstrap entry (v0.87.0 lifecycle → wiring rename)</td></tr>
                <tr><td>channels</td><td><code>core/channels/</code></td><td>adapter classes</td></tr>
                <tr><td>ui</td><td><code>core/ui/</code></td><td>spinners, progress</td></tr>
              </tbody>
            </table>

            <h2>L2 Runtime</h2>
            <table>
              <thead><tr><th>Subsystem</th><th>Root</th><th>Entry</th></tr></thead>
              <tbody>
                <tr><td>llm</td><td><code>core/llm/</code></td><td><code>agentic_response.py:46</code></td></tr>
                <tr><td>llm/prompts</td><td><code>core/llm/prompts/</code></td><td><code>__init__.py</code></td></tr>
                <tr><td>llm/providers</td><td><code>core/llm/providers/</code></td><td><code>anthropic.py</code></td></tr>
                <tr><td>tools</td><td><code>core/tools/</code></td><td><code>base.py:35 Tool</code></td></tr>
                <tr><td>mcp</td><td><code>core/mcp/</code></td><td><code>manager.py MCPManager</code></td></tr>
                <tr><td>memory</td><td><code>core/memory/</code></td><td><code>context.py:46</code></td></tr>
                <tr><td>skills</td><td><code>core/skills/</code></td><td><code>skill_registry.py</code></td></tr>
                <tr><td>verification</td><td><code>core/verification/</code></td><td><code>guardrails.py</code></td></tr>
                <tr><td>scheduler</td><td><code>core/scheduler/</code></td><td><code>scheduler.py:76</code></td></tr>
                <tr><td>automation</td><td><code>core/automation/</code></td><td><code>model_registry.py</code></td></tr>
                <tr><td>orchestration</td><td><code>core/orchestration/</code></td><td><code>graph.py</code></td></tr>
                <tr><td>auth</td><td><code>core/auth/</code></td><td>OAuth profile rotator</td></tr>
              </tbody>
            </table>

            <h2>Bundled Plugins</h2>
            <table>
              <thead><tr><th>Plugin</th><th>Root</th><th>Highlights</th></tr></thead>
              <tbody>
                <tr>
                  <td><strong>petri_audit</strong></td>
                  <td><code>plugins/petri_audit/</code></td>
                  <td>Petri × GEODE alignment audit runner, seed catalog, judge dimensions</td>
                </tr>
              </tbody>
            </table>
          </>
        }
      />
    </DocsShell>
  );
}
