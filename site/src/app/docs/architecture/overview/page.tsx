"use client";

import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export default function Page() {
  return (
    <DocsShell
      slug="architecture/overview"
      title="4-Layer Stack"
      titleKo="4-계층 스택"
      summary="GEODE's architecture splits into four layers, each with distinct responsibilities and replaceability boundaries."
      summaryKo="GEODE 아키텍처는 책임과 교체 경계가 분리된 4개 계층으로 구성됩니다."
    >
      <pre>{`Layer 4 — Agent      AgenticLoop, while(tool_use), error recovery
Layer 3 — Harness    CLI, Gateway, IPC, Hooks, Lifecycle, UI
Layer 2 — Runtime    LLM router, providers, prompts, tools, MCP, memory, skills
Layer 1 — Model      Anthropic / OpenAI / Codex Plus / GLM (3 chains, 9 models)`}</pre>

      <Bi
        ko={
          <>
            <h2>Layer 1 — Model</h2>
            <p>모델 계층은 외부 네트워크 호출을 가지는 유일한 계층입니다. GEODE 는 3개의 프로바이더 fallback chain 을 사용합니다:</p>
            <ul>
              <li><strong>Anthropic</strong>: Opus 4.7 → Opus 4.6 → Sonnet 4.6 → Haiku 4.5</li>
              <li><strong>OpenAI Responses / Codex Plus</strong>: gpt-5.5 → gpt-5.4 → gpt-5.4-mini → gpt-5-mini</li>
              <li><strong>GLM</strong>: GLM-4.5+ (<code>thinking</code> 필드 활성화)</li>
            </ul>
            <p>
              적응적 thinking depth (effort: <code>low</code>, <code>medium</code>,{" "}
              <code>high</code>, <code>max</code>, <code>xhigh</code>) 는 프로바이더별로
              구현이 다르지만 LLM 라우터를 통해 통일된 인터페이스로 노출됩니다.
            </p>

            <h2>Layer 2 — Runtime</h2>
            <p>
              런타임 계층은 모든 횡단 관심사를 담당합니다: 프롬프트 조립, 도구
              레지스트리, MCP 서버 오케스트레이션, 다층 메모리, 스킬 디스커버리,
              검증 가드레일. 위 하네스 계층에 단일한 일관된 인터페이스를 제공합니다.
            </p>
            <p>주요 서브시스템 (자세한 내역은 <a href="/geode/docs/architecture/system-index">시스템 색인</a> 참조):</p>
            <ul>
              <li><code>core/llm/</code> — 22 모듈, 프롬프트 + 프로바이더 라우터</li>
              <li><code>core/tools/</code> — 16 모듈, 57 도구, 지연 로딩 (6 always-loaded)</li>
              <li><code>core/mcp/</code> — 20 모듈, 16 서버, 25K 토큰 가드</li>
              <li><code>core/memory/</code> — 14 모듈, 5계층 컨텍스트</li>
              <li><code>core/hooks/</code> — 9 모듈, 58 라이프사이클 이벤트</li>
            </ul>

            <h2>Layer 3 — Harness</h2>
            <p>
              사용자가 보는 것: CLI, 데몬(<code>geode serve</code>), thin client
              와 데몬 사이의 IPC 브릿지, 라이프사이클 부트스트랩, GEODE 의 나머지를
              관찰 가능하게 만드는 hook 시스템.
            </p>
            <p>슬래시 명령(<code>/model</code>, <code>/skip</code>, <code>/resume</code>, <code>/clear</code>, <code>/stop</code>, <code>/status</code>) 은 여기에 살며 <code>core/cli/commands.py</code> 에서 dispatch 됩니다.</p>

            <h2>Layer 4 — Agent</h2>
            <p>
              에이전트는 단 하나의 primitive 를 소유하는 얇은 계층:{" "}
              <code>while (response.has_tool_use)</code>. <code>core/agent/loop.py</code>{" "}
              의 <code>AgenticLoop</code> 가 멀티턴 실행을 주도하며, 프롬프트 조립,
              도구 실행, 에러 복구를 모두 아래의 런타임 계층에 위임합니다.
            </p>
            <p>루프의 정확한 의미론은 <a href="/geode/docs/architecture/agentic-loop">Agentic 루프</a> 참조.</p>

            <h2>교체 경계</h2>
            <p>각 계층은 원칙적으로 위 계층을 건드리지 않고 교체 가능합니다:</p>
            <ul>
              <li>새 프로바이더 추가 = <code>core/llm/providers/</code> 에 새 파일 — Layer 1 만</li>
              <li>새 도구 추가 = <code>core/tools/</code> 에 새 도구 정의 — Layer 2 만</li>
              <li>새 슬래시 명령 추가 = <code>core/cli/</code> 에 새 명령 — Layer 3 만</li>
              <li>루프 의미 변경은 드문 Layer 4 변경이며 리뷰 게이트를 거칩니다</li>
            </ul>
          </>
        }
        en={
          <>
            <h2>Layer 1 — Model</h2>
            <p>The model layer is the only layer with external network calls. GEODE uses three provider fallback chains:</p>
            <ul>
              <li><strong>Anthropic</strong>: Opus 4.7 → Opus 4.6 → Sonnet 4.6 → Haiku 4.5</li>
              <li><strong>OpenAI Responses / Codex Plus</strong>: gpt-5.5 → gpt-5.4 → gpt-5.4-mini → gpt-5-mini</li>
              <li><strong>GLM</strong>: GLM-4.5+ with the <code>thinking</code> field enabled</li>
            </ul>
            <p>
              Adaptive thinking depth (effort: <code>low</code>, <code>medium</code>,{" "}
              <code>high</code>, <code>max</code>, <code>xhigh</code>) is provider-specific
              but exposed uniformly through the LLM router.
            </p>

            <h2>Layer 2 — Runtime</h2>
            <p>
              The runtime layer holds all of the cross-cutting machinery: prompt assembly, tool registry, MCP server orchestration, multi-tier memory, skill discovery, and verification guardrails. It exposes a single coherent interface to the harness above.
            </p>
            <p>Notable subsystems (see <a href="/geode/docs/architecture/system-index">System Index</a>):</p>
            <ul>
              <li><code>core/llm/</code> — 22 modules, the prompt + provider router</li>
              <li><code>core/tools/</code> — 16 modules, 57 tools, deferred loading (6 always-loaded)</li>
              <li><code>core/mcp/</code> — 20 modules, 16 servers, 25K token guard</li>
              <li><code>core/memory/</code> — 14 modules, 5-tier context</li>
              <li><code>core/hooks/</code> — 9 modules, 58 lifecycle events</li>
            </ul>

            <h2>Layer 3 — Harness</h2>
            <p>
              The harness is what users see: the CLI, the daemon (<code>geode serve</code>), the IPC bridge between thin client and daemon, lifecycle bootstrap, and the hook system that makes the rest of GEODE observable.
            </p>
            <p>
              Slash commands (<code>/model</code>, <code>/skip</code>, <code>/resume</code>, <code>/clear</code>, <code>/stop</code>, <code>/status</code>) live here, dispatched by <code>core/cli/commands.py</code>.
            </p>

            <h2>Layer 4 — Agent</h2>
            <p>
              The agent is a thin layer that owns one primitive: <code>while (response.has_tool_use)</code>. <code>AgenticLoop</code> in <code>core/agent/loop.py</code> drives the multi-turn execution, delegating prompt assembly, tool execution, and error recovery to the runtime layer below.
            </p>
            <p>See <a href="/geode/docs/architecture/agentic-loop">Agentic Loop</a> for the loop&apos;s exact semantics.</p>

            <h2>Replaceability boundary</h2>
            <p>Each layer can in principle be swapped without touching the layers above:</p>
            <ul>
              <li>Adding a new provider means a new file in <code>core/llm/providers/</code> — Layer 1 only.</li>
              <li>Adding a tool means a new tool definition in <code>core/tools/</code> — Layer 2 only.</li>
              <li>Adding a slash command means a new command in <code>core/cli/</code> — Layer 3 only.</li>
              <li>Changing loop semantics is the rare Layer 4 change and is gated by review.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
