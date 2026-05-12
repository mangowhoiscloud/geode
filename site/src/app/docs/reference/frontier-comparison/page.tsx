import { DocsShell } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Frontier Comparison — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="reference/frontier-comparison"
      title="Frontier Comparison"
      summary="GEODE side-by-side with five frontier harnesses — Hermes, OpenClaw, Claude Code, Codex CLI, and Karpathy autoresearch — first at the architectural level, then drilling into prompt-system internals."
    >
      <h2>System-level positioning</h2>
      <p>
        Top-level differences across six harnesses. GEODE is the synthesis —
        each row borrows from at least one frontier system. Patterns specifically
        cited in source: Claude Code <code>while(tool_use)</code>, Codex CLI
        sandbox-default, OpenClaw <code>Policy Chain</code> + <code>Lane Queue</code>,
        Karpathy P1-P10.
      </p>
      <table>
        <thead>
          <tr>
            <th>Axis</th>
            <th>Claude Code</th>
            <th>Codex CLI</th>
            <th>OpenClaw</th>
            <th>Hermes</th>
            <th>autoresearch</th>
            <th>GEODE</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Purpose</td>
            <td>Coding assist</td>
            <td>Code automation</td>
            <td>Multi-channel gateway</td>
            <td>Self-learning agent</td>
            <td>Autonomous ML loop</td>
            <td><strong>Long-running autonomous execution</strong></td>
          </tr>
          <tr>
            <td>Domain</td>
            <td>code</td>
            <td>code</td>
            <td>chat routing</td>
            <td>open-domain</td>
            <td>ML loop</td>
            <td>game IP (today), generalisable via DomainPort</td>
          </tr>
          <tr>
            <td>Main primitive</td>
            <td><code>while(tool_use)</code></td>
            <td>sandbox + approve</td>
            <td>gateway + lane</td>
            <td>skill loop</td>
            <td>branchless dumb platform</td>
            <td>StateGraph + agentic loop</td>
          </tr>
          <tr>
            <td>Memory</td>
            <td>bash session + <code>~/.claude</code></td>
            <td>—</td>
            <td>per-channel store</td>
            <td>persistent + skill catalog</td>
            <td><code>program.md</code></td>
            <td>5-tier (Org / Project / Session / Vault / Breadcrumb)</td>
          </tr>
          <tr>
            <td>Verification</td>
            <td>—</td>
            <td>sandbox</td>
            <td>policy chain</td>
            <td>—</td>
            <td>ratchet</td>
            <td><strong>G1-G4 + BiasBuster + Cross-LLM</strong></td>
          </tr>
          <tr>
            <td>Automation trigger</td>
            <td>hooks (manual)</td>
            <td>—</td>
            <td>cron + standing orders</td>
            <td>skill auto-generate</td>
            <td>overnight loop</td>
            <td>58 events + scheduler</td>
          </tr>
          <tr>
            <td>Multi-LLM</td>
            <td>Anthropic only</td>
            <td>OpenAI only</td>
            <td>8+ providers</td>
            <td>Anthropic-centric</td>
            <td>(single)</td>
            <td>4 providers (Anthropic + Codex + PAYG + GLM)</td>
          </tr>
          <tr>
            <td>Sub-agent</td>
            <td>Task tool</td>
            <td>—</td>
            <td>plugin</td>
            <td>spawn + announce</td>
            <td>—</td>
            <td>Borrowed (Task tool + OpenClaw Spawn+Announce)</td>
          </tr>
          <tr>
            <td>Sandbox</td>
            <td>—</td>
            <td>OS-level</td>
            <td>gateway isolation</td>
            <td>—</td>
            <td>constraint loop</td>
            <td>6-layer Policy Chain</td>
          </tr>
        </tbody>
      </table>

      <h3>What GEODE has that none of the others do</h3>
      <ul>
        <li>
          <strong>BiasBuster</strong> — confirmation / recency / anchoring /
          position / verbosity / self-enhancement bias detection in{" "}
          <code>core/verification/biasbuster.py</code>. Statistical fast path
          (CV-based) plus LLM fallback.
        </li>
        <li>
          <strong>Cause-Action decision tree</strong> — 6 causes →
          5 actions in <code>plugins/game_ip/nodes/synthesizer.py</code>.
          Domain-pluggable.
        </li>
        <li>
          <strong>Calibration via Golden Set</strong> —
          <code>core/verification/calibration.py</code>, fixture comparison
          PASS threshold 80.0.
        </li>
        <li>
          <strong>Equivalence-class fallback</strong> — provider variants
          (e.g. <code>openai-codex</code> ↔ <code>openai</code> PAYG) auto-tried
          in subscription-priority order via{" "}
          <code>core/auth/plan_registry.py:resolve_routing</code>.
        </li>
        <li>
          <strong>ChatGPT Plus JWT verification</strong> — auth claim{" "}
          <code>chatgpt_plan_type</code> extracted at OAuth time and embedded in
          the Plan record (<code>core/auth/oauth_login.py:331</code>); no
          separate API call needed for entitlement check.
        </li>
      </ul>

      <h2>Definition layer</h2>
      <table>
        <thead><tr><th>Axis</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
        <tbody>
          <tr><td>Source location</td><td><code>core/llm/prompts/*.md</code></td><td><code>agent/prompt_builder.py</code> (Python const)</td><td><code>src/agents/system-prompt.ts</code> (TS const)</td><td><code>constants/prompts.ts</code> (TS const)</td></tr>
          <tr><td>Build time</td><td>Module import</td><td>Session start (cached)</td><td>Per-call modular</td><td>Per-turn dynamic</td></tr>
          <tr><td>User memory</td><td>5-tier <code>~/.geode/memory/</code></td><td>Frozen JSON snapshot</td><td>Workspace HEARTBEAT.md</td><td>CLAUDE.md (4-tier)</td></tr>
        </tbody>
      </table>

      <h2>Assembly</h2>
      <table>
        <thead><tr><th>Axis</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
        <tbody>
          <tr><td>Result type</td><td><code>AssembledPrompt(frozen=True)</code></td><td><code>str</code> cached</td><td>String returned</td><td><code>TextBlockParam[]</code></td></tr>
          <tr><td>Override policy</td><td>Append-only by default</td><td>Append via param</td><td>Append via param</td><td>5-priority chain</td></tr>
          <tr><td>Skill format</td><td>Markdown blocks</td><td>XML <code>&lt;available_skills&gt;</code></td><td>XML <code>&lt;available_skills&gt;</code></td><td>XML registry</td></tr>
          <tr><td>Truncation event log</td><td><code>truncation_events</code> in hook</td><td>Logger only</td><td>Report object</td><td>Not tracked</td></tr>
        </tbody>
      </table>

      <h2>Hashing &amp; integrity</h2>
      <table>
        <thead><tr><th>Axis</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
        <tbody>
          <tr><td>Algorithm</td><td>SHA-256[:12]</td><td>None</td><td>SHA-256 (full)</td><td>SHA-256[:3]</td></tr>
          <tr><td>Pin / CI gate</td><td><strong>Yes</strong> — <code>_PINNED_HASHES</code> × 20</td><td>None</td><td>Detection only</td><td>None (attribution only)</td></tr>
          <tr><td>Normalization</td><td>UTF-8 / json sort_keys</td><td>mtime + size manifest</td><td>CRLF strip + sort + lowercase</td><td>(model, toolNames, sysLen) tuple</td></tr>
        </tbody>
      </table>

      <h2>Caching</h2>
      <table>
        <thead><tr><th>Axis</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
        <tbody>
          <tr><td>Anthropic ephemeral</td><td>Yes — system + STATIC/DYNAMIC</td><td>Yes — system_and_3</td><td>Yes — boundary marker</td><td>Yes — global/org scope</td></tr>
          <tr><td>Boundary marker</td><td><code>__GEODE_PROMPT_CACHE_BOUNDARY__</code></td><td>None</td><td><code>&lt;!-- OPENCLAW_CACHE_BOUNDARY --&gt;</code></td><td><code>__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__</code></td></tr>
          <tr><td>Messages history cache</td><td>No (open GAP)</td><td>Yes — last 3</td><td>Yes — last user message</td><td>Yes — last user blocks</td></tr>
          <tr><td>Breakpoints used / 4</td><td>1-2</td><td>4</td><td>2-3</td><td>3-4</td></tr>
        </tbody>
      </table>

      <h2>Observability</h2>
      <table>
        <thead><tr><th>Axis</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
        <tbody>
          <tr><td>Primary channel</td><td><code>PROMPT_ASSEMBLED</code> hook payload</td><td>60-char preview log</td><td><code>cache-trace.ts</code> JSONL</td><td><code>logEvent('tengu_*')</code> telemetry</td></tr>
          <tr><td>External tracing</td><td>LangSmith opt-in</td><td>None</td><td>Self JSONL</td><td>Self telemetry</td></tr>
          <tr><td>Prompt text in trace</td><td>Hashes only</td><td>Stored in session DB</td><td>Hashes by default</td><td>Not in telemetry</td></tr>
        </tbody>
      </table>

      <h2>Security</h2>
      <table>
        <thead><tr><th>Axis</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
        <tbody>
          <tr><td>Prompt-injection scan</td><td>None (open GAP)</td><td><strong>11 patterns</strong> + invisible Unicode</td><td>Path/URL sanitization</td><td>Trusts user intent</td></tr>
          <tr><td>Frozen result</td><td><code>frozen=True</code></td><td>Convention</td><td>Convention</td><td>Convention</td></tr>
          <tr><td>Override security</td><td>Append-only by default</td><td>Append-only</td><td>Append-only</td><td>Priority chain</td></tr>
        </tbody>
      </table>

      <h2>Why GEODE was the only one to ratchet</h2>
      <p>
        GEODE&apos;s prompts live in markdown files. Hermes, OpenClaw, and
        Claude Code keep prompts as inline strings inside their respective
        TypeScript or Python source. Inline strings are subject to
        autoformatter noise, IDE renames, and merge-conflict resolutions in
        ways that fight a hashlib-based ratchet. External markdown makes the
        file the unit of change, and the hash becomes meaningful.
      </p>
      <p>
        The cost: GEODE pays one extra step (the re-pin) for every
        intentional prompt change, but gets a CI-enforced guarantee that
        unintentional changes never ship.
      </p>
    </DocsShell>
  );
}
