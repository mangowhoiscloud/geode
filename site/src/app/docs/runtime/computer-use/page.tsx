import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Computer Use — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/computer-use"
      title="Computer Use"
      summary="Provider-agnostic desktop automation. PyAutoGUI backend, screenshot + click + type primitives, opt-in via tool registry."
    >
      <h2>Two backends, one interface</h2>
      <p>
        Anthropic&apos;s computer-use API and OpenAI&apos;s computer-use
        beta are different protocols with similar primitives. GEODE
        wraps both behind a single tool definition (
        <code>computer</code>) and routes to the appropriate provider
        backend based on the active model.
      </p>

      <h2>Primitives</h2>
      <ul>
        <li><strong>screenshot</strong> — capture the active display</li>
        <li><strong>click</strong> — mouse click at (x, y)</li>
        <li><strong>type</strong> — keyboard input</li>
        <li><strong>key</strong> — modifier + key (Cmd+Tab, etc.)</li>
        <li><strong>scroll</strong> — direction + amount</li>
        <li><strong>cursor_position</strong> — read current</li>
      </ul>

      <h2>Activation</h2>
      <p>
        The computer-use tool is opt-in via{" "}
        <code>is_computer_use_enabled()</code> — gated by config flag and
        the active provider supporting it. When enabled, the Anthropic
        agentic adapter injects <code>_COMPUTER_USE_TOOL</code> into the
        tool list at <code>core/llm/providers/anthropic.py</code>.
      </p>

      <h2>Safety</h2>
      <p>
        Every <code>click</code> and <code>type</code> action fires{" "}
        <code>TOOL_APPROVAL_REQUEST</code> by default. The HITL gate can be
        relaxed per session (<code>--no-approve</code>) or per-tool, but
        the default is human-in-the-loop for any side-effect on the
        desktop.
      </p>

      <h2>Files</h2>
      <ul>
        <li><code>core/tools/computer_use.py</code> — primitive implementations</li>
        <li><code>core/llm/providers/anthropic.py</code> — <code>_COMPUTER_USE_TOOL</code> definition + injection</li>
        <li><code>core/llm/providers/openai.py</code> — OpenAI beta path</li>
      </ul>

    </DocsShell>
  );
}
