import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "System Index — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="architecture/system-index"
      title="System Index"
      summary="Every first-class subsystem in GEODE v0.64.0, with module count and main entry point."
    >
      <h2>Project statistics</h2>
      <pre>{`$ find core/ -name "*.py" | wc -l        # 223
$ find plugins/ -name "*.py" | wc -l     # 13
$ find tests/ -name "test_*.py" | wc -l  # ~229`}</pre>

      <h2>L4 Agent (1)</h2>
      <table>
        <thead><tr><th>Subsystem</th><th>Root</th><th>Modules</th><th>Entry</th></tr></thead>
        <tbody>
          <tr><td><strong>agent</strong></td><td><code>core/agent/</code></td><td>14</td><td><code>loop.py:162 AgenticLoop</code></td></tr>
        </tbody>
      </table>

      <h2>L3 Harness (6)</h2>
      <table>
        <thead><tr><th>Subsystem</th><th>Root</th><th>Modules</th><th>Entry</th></tr></thead>
        <tbody>
          <tr><td>cli</td><td><code>core/cli/</code></td><td>30</td><td><code>commands.py:41 ModelProfile</code></td></tr>
          <tr><td>gateway</td><td><code>core/cli/serve/</code></td><td>—</td><td><code>geode serve</code></td></tr>
          <tr><td>hooks</td><td><code>core/hooks/</code></td><td>7</td><td><code>system.py:200 HookSystem</code></td></tr>
          <tr><td>lifecycle</td><td><code>core/lifecycle/</code></td><td>5</td><td>bootstrap entry</td></tr>
          <tr><td>channels</td><td><code>core/channels/</code></td><td>4</td><td>adapter classes</td></tr>
          <tr><td>ui</td><td><code>core/ui/</code></td><td>8</td><td>spinners, progress</td></tr>
        </tbody>
      </table>

      <h2>L2 Runtime (13)</h2>
      <table>
        <thead><tr><th>Subsystem</th><th>Root</th><th>Modules</th><th>Entry</th></tr></thead>
        <tbody>
          <tr><td>llm</td><td><code>core/llm/</code></td><td>15</td><td><code>agentic_response.py:46</code></td></tr>
          <tr><td>llm/prompts</td><td><code>core/llm/prompts/</code></td><td>2 + .md</td><td><code>__init__.py</code></td></tr>
          <tr><td>llm/providers</td><td><code>core/llm/providers/</code></td><td>5</td><td><code>anthropic.py</code></td></tr>
          <tr><td>tools</td><td><code>core/tools/</code></td><td>16</td><td><code>base.py:35 Tool</code></td></tr>
          <tr><td>mcp</td><td><code>core/mcp/</code></td><td>20</td><td><code>manager.py MCPManager</code></td></tr>
          <tr><td>memory</td><td><code>core/memory/</code></td><td>14</td><td><code>context.py:46</code></td></tr>
          <tr><td>skills</td><td><code>core/skills/</code></td><td>6</td><td><code>skill_registry.py</code></td></tr>
          <tr><td>verification</td><td><code>core/verification/</code></td><td>7</td><td><code>guardrails.py</code></td></tr>
          <tr><td>scheduler</td><td><code>core/scheduler/</code></td><td>6</td><td><code>scheduler.py:76</code></td></tr>
          <tr><td>automation</td><td><code>core/automation/</code></td><td>8</td><td><code>model_registry.py</code></td></tr>
          <tr><td>orchestration</td><td><code>core/orchestration/</code></td><td>17</td><td><code>graph.py</code></td></tr>
          <tr><td>auth</td><td><code>core/auth/</code></td><td>14</td><td>OAuth profile rotator</td></tr>
          <tr><td>domains</td><td><code>core/domains/</code></td><td>3</td><td><code>port.py:18 DomainPort</code></td></tr>
        </tbody>
      </table>

      <h2>Plugins (1)</h2>
      <table>
        <thead><tr><th>Plugin</th><th>Root</th><th>Modules</th><th>Highlights</th></tr></thead>
        <tbody>
          <tr>
            <td><strong>game_ip</strong></td>
            <td><code>plugins/game_ip/</code></td>
            <td>13</td>
            <td>4 Analysts + 3 Evaluators + Synthesizer + BiasBuster, 14-axis PSM scoring</td>
          </tr>
        </tbody>
      </table>

      <h2>Inventory totals</h2>
      <table>
        <tbody>
          <tr><th>Core modules</th><td>223</td></tr>
          <tr><th>Plugin modules</th><td>13</td></tr>
          <tr><th>Tests</th><td>~229 files (memory 83, llm 62, tools 59, hooks 31, agent 30)</td></tr>
          <tr><th>Hook events</th><td>58 (12 groups)</td></tr>
          <tr><th>Tools</th><td>57 (6 always-loaded + 51 deferred via <code>tool_search</code>)</td></tr>
          <tr><th>MCP servers</th><td>16</td></tr>
          <tr><th>Slash commands</th><td>15+</td></tr>
          <tr><th>Prompt templates pinned</th><td>20 (17 .md + 3 axes)</td></tr>
        </tbody>
      </table>
    </DocsShell>
  );
}
