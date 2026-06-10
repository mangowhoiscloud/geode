import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Frontier comparison — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="reference/frontier-comparison"
      title="Frontier comparison"
      titleKo="프론티어 비교"
      summary="GEODE side by side with Hermes, OpenClaw, Claude Code, Codex CLI, and Karpathy autoresearch: architecture first, then prompt-system internals."
      summaryKo="GEODE를 Hermes, OpenClaw, Claude Code, Codex CLI, Karpathy autoresearch와 나란히 놓습니다. 아키텍처부터 프롬프트 시스템 내부까지 비교합니다."
    >
      <Bi
        ko={
          <>
            <h2>시스템 수준 포지셔닝</h2>
            <p>
              GEODE는 종합입니다. 아래 표의 각 행은 적어도 하나의 frontier
              시스템에서 빌려온 패턴입니다. 소스에 명시적으로 인용된 것은
              Claude Code의 <code>while(tool_use)</code>, Codex CLI의
              sandbox-default, OpenClaw의 Policy Chain과 Lane Queue, Karpathy
              P1-P10입니다.
            </p>
            <table>
              <thead>
                <tr>
                  <th>축</th>
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
                  <td>목적</td>
                  <td>Coding assist</td>
                  <td>Code automation</td>
                  <td>Multi-channel gateway</td>
                  <td>Self-learning agent</td>
                  <td>Autonomous ML loop</td>
                  <td><strong>장기 실행 자율 실행</strong></td>
                </tr>
                <tr>
                  <td>도메인</td>
                  <td>code</td>
                  <td>code</td>
                  <td>chat routing</td>
                  <td>open-domain</td>
                  <td>ML loop</td>
                  <td>범용. 리서치, 분석, 자동화, 스케줄</td>
                </tr>
                <tr>
                  <td>주요 기본 단위</td>
                  <td><code>while(tool_use)</code></td>
                  <td>sandbox + approve</td>
                  <td>gateway + lane</td>
                  <td>skill loop</td>
                  <td>branchless dumb platform</td>
                  <td><code>while(tool_use)</code> AgenticLoop + LaneQueue</td>
                </tr>
                <tr>
                  <td>계층 구조</td>
                  <td>단일 CLI</td>
                  <td>단일 CLI</td>
                  <td>gateway 중심</td>
                  <td>agent + skills</td>
                  <td>3-파일 계약</td>
                  <td>5계층. Model / Runtime / Harness / Agent / Self-Improving</td>
                </tr>
                <tr>
                  <td>메모리</td>
                  <td>bash 세션 + <code>~/.claude</code></td>
                  <td>없음</td>
                  <td>채널별 저장소</td>
                  <td>persistent + skill 카탈로그</td>
                  <td><code>program.md</code></td>
                  <td>5-tier. Identity / User Profile / Org / Project / Session (<code>core/memory/context.py</code>)</td>
                </tr>
                <tr>
                  <td>자기 검증</td>
                  <td>없음</td>
                  <td>sandbox</td>
                  <td>policy chain</td>
                  <td>없음</td>
                  <td>ratchet</td>
                  <td>Petri 적대 감사 + margin 게이트 + 프롬프트 해시 ratchet</td>
                </tr>
                <tr>
                  <td>자동화 트리거</td>
                  <td>훅 (수동)</td>
                  <td>없음</td>
                  <td>cron + standing order</td>
                  <td>skill auto-generate</td>
                  <td>overnight 루프</td>
                  <td>훅 이벤트 + 스케줄러 + auto-trigger 사이드카</td>
                </tr>
                <tr>
                  <td>멀티 LLM</td>
                  <td>Anthropic only</td>
                  <td>OpenAI only</td>
                  <td>8+ providers</td>
                  <td>Anthropic-centric</td>
                  <td>(single)</td>
                  <td>3-프로바이더 라우팅 (Anthropic / OpenAI+Codex / GLM), PAYG·OAuth·CLI 어댑터 레인</td>
                </tr>
                <tr>
                  <td>서브에이전트</td>
                  <td>Task tool</td>
                  <td>없음</td>
                  <td>plugin</td>
                  <td>spawn + announce</td>
                  <td>없음</td>
                  <td>차용. Task tool + OpenClaw Spawn+Announce (<code>core/agent/sub_agent.py</code>)</td>
                </tr>
                <tr>
                  <td>샌드박스</td>
                  <td>없음</td>
                  <td>OS 수준</td>
                  <td>gateway 격리</td>
                  <td>없음</td>
                  <td>제약 루프</td>
                  <td>6계층 PolicyChain (<code>core/tools/policy.py</code>)</td>
                </tr>
              </tbody>
            </table>

            <h3>GEODE만의 조합</h3>
            <ul>
              <li>
                <strong>명시적 자기개선 계층</strong>. 다섯 번째 계층이 일곱
                behaviour kinds의 스캐폴드를 변이하고, Petri 22-dim 감사와
                margin 게이트로 선택하며, 계보를 git champion chain으로
                보존합니다(<code>core/self_improving/</code>). 가중치나
                파라미터 갱신은 없습니다. 메커니즘은 선택입니다.
              </li>
              <li>
                <strong>MCP 양방향</strong>. <code>core/mcp/</code>가 외부 MCP
                서버를 붙이는 클라이언트이고, <code>geode-mcp</code>
                (<code>core/mcp_server.py</code>)가 GEODE 자체를 외부 호스트의
                도구로 노출하는 1급 서버입니다. 비교 대상 중 같은 런타임이 양
                방향을 모두 출하하는 시스템은 없습니다.
              </li>
              <li>
                <strong>폴백 없는 기본값</strong>. <code>[model.fallbacks]</code>의
                기본값은 전부 빈 배열입니다. 프라이머리 실패는 조용한
                교차-프로바이더 스왑 대신 정직한 오류로 표면화되고, 체인은{" "}
                <code>~/.geode/routing.toml</code>에서 opt-in합니다
                (<code>core/llm/router/calls/_failover.py</code>).
              </li>
              <li>
                <strong>ChatGPT Plus JWT 검증</strong>. OAuth 시점에 access
                token의 <code>chatgpt_plan_type</code> claim을 추출해 플랜
                레코드에 임베드합니다(<code>core/auth/oauth_login.py</code>).
                엔타이틀먼트 확인에 별도 API 호출이 없습니다.
              </li>
            </ul>

            <h2>프롬프트 정의 계층</h2>
            <table>
              <thead><tr><th>축</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>소스 위치</td><td><code>core/llm/prompts/*.md</code> (외부 markdown)</td><td><code>agent/prompt_builder.py</code> (Python const)</td><td><code>src/agents/system-prompt.ts</code> (TS const)</td><td><code>constants/prompts.ts</code> (TS const)</td></tr>
                <tr><td>빌드 시점</td><td>모듈 임포트 시 해시, 턴마다 조립</td><td>세션 시작 (캐시)</td><td>호출별 모듈식</td><td>턴별 동적</td></tr>
                <tr><td>사용자 메모리</td><td>5-tier <code>~/.geode/memory/</code></td><td>Frozen JSON 스냅샷</td><td>Workspace HEARTBEAT.md</td><td>CLAUDE.md (4계층)</td></tr>
                <tr><td>스킬 포맷</td><td>Markdown 블록 (<code>{`{skill_context}`}</code>, <code>core/agent/loop/_context.py</code>)</td><td>XML <code>&lt;available_skills&gt;</code></td><td>XML <code>&lt;available_skills&gt;</code></td><td>XML 레지스트리</td></tr>
              </tbody>
            </table>

            <h2>해싱과 무결성</h2>
            <table>
              <thead><tr><th>축</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>알고리즘</td><td>SHA-256[:12]</td><td>없음</td><td>SHA-256 (전체)</td><td>SHA-256[:3]</td></tr>
                <tr><td>핀 / CI 게이트</td><td><strong>예</strong>. <code>_PINNED_HASHES</code> + <code>verify_prompt_integrity</code> (<code>core/llm/prompts/__init__.py</code>)</td><td>없음</td><td>탐지만</td><td>없음 (attribution만)</td></tr>
                <tr><td>정규화</td><td>UTF-8 / json sort_keys</td><td>mtime + size manifest</td><td>CRLF strip + sort + lowercase</td><td>(model, toolNames, sysLen) tuple</td></tr>
              </tbody>
            </table>

            <h2>프롬프트 캐싱</h2>
            <table>
              <thead><tr><th>축</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>Anthropic ephemeral</td><td>예. static/dynamic 경계 분할</td><td>예. system_and_3</td><td>예. 경계 마커</td><td>예. global/org scope</td></tr>
                <tr><td>경계 마커</td><td><code>PROMPT_CACHE_BOUNDARY</code> = <code>&lt;dynamic_context&gt;</code> (<code>core/agent/system_prompt.py</code>)</td><td>없음</td><td><code>&lt;!-- OPENCLAW_CACHE_BOUNDARY --&gt;</code></td><td><code>__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__</code></td></tr>
                <tr><td>메시지 히스토리 캐시</td><td>예. 최근 user 메시지 rolling breakpoint (<code>apply_messages_cache_control</code>, <code>core/llm/providers/anthropic.py</code>)</td><td>예. 직전 3</td><td>예. 직전 user 메시지</td><td>예. 직전 user 블록</td></tr>
              </tbody>
            </table>
            <p>
              캐시 안정성의 나머지 반쪽은 시스템 리마인더 위치입니다. GEODE는
              리마인더를 요청별 사본의 마지막 메시지로 append합니다
              (<code>core/agent/system_injection.py</code>). 공유 히스토리를
              건드리지 않아 prefix가 라운드 간 바이트 단위로 안정됩니다.
            </p>

            <h2>관측성</h2>
            <table>
              <thead><tr><th>축</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>주 채널</td><td><code>PROMPT_ASSEMBLED</code> 훅 payload (<code>core/agent/loop/agent_loop.py</code>)</td><td>60자 preview 로그</td><td><code>cache-trace.ts</code> JSONL</td><td><code>logEvent(&apos;tengu_*&apos;)</code> 텔레메트리</td></tr>
                <tr><td>외부 트레이싱</td><td>OTLP optional (<code>core/observability/otel_export.py</code>)</td><td>없음</td><td>자체 JSONL</td><td>자체 텔레메트리</td></tr>
              </tbody>
            </table>

            <h2>보안</h2>
            <table>
              <thead><tr><th>축</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>프롬프트 인젝션 스캔</td><td>없음 (열린 GAP)</td><td><strong>11 패턴</strong> + invisible Unicode</td><td>경로 / URL 정화</td><td>사용자 의도 신뢰</td></tr>
                <tr><td>오버라이드 정책</td><td>append-only (호출자 <code>system_suffix</code>)</td><td>append-only</td><td>append-only</td><td>우선순위 체인</td></tr>
              </tbody>
            </table>

            <h2>왜 GEODE만 ratchet으로 갈 수 있었나</h2>
            <p>
              GEODE의 프롬프트는 markdown 파일에 삽니다. Hermes, OpenClaw,
              Claude Code는 프롬프트를 TypeScript나 Python 소스의 인라인
              문자열로 유지합니다. 인라인 문자열은 자동 포맷터, IDE 리네임,
              머지 충돌 해소 과정에서 해시 기반 ratchet과 싸우게 됩니다. 외부
              markdown은 파일을 변경 단위로 만들고, 그래서 해시가 의미를
              갖습니다.
            </p>
            <p>
              비용도 분명합니다. 의도된 프롬프트 변경마다 재핀 커밋 한 단계를
              더 지불합니다. 그 대가로 의도하지 않은 변경이 출시되지 않는다는
              CI 강제 보장을 얻습니다. 자세한 형태는{" "}
              <a href="/geode/docs/explanation/ratchet">왜 ratchet 규율인가</a>에
              있습니다.
            </p>
          </>
        }
        en={
          <>
            <h2>System-level positioning</h2>
            <p>
              GEODE is a synthesis: each row below borrows from at least one
              frontier system. Patterns explicitly cited in source: Claude
              Code&apos;s <code>while(tool_use)</code>, Codex CLI&apos;s
              sandbox-default, OpenClaw&apos;s Policy Chain and Lane Queue, and
              Karpathy&apos;s P1-P10.
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
                  <td>General purpose: research, analysis, automation, schedules</td>
                </tr>
                <tr>
                  <td>Main primitive</td>
                  <td><code>while(tool_use)</code></td>
                  <td>sandbox + approve</td>
                  <td>gateway + lane</td>
                  <td>skill loop</td>
                  <td>branchless dumb platform</td>
                  <td><code>while(tool_use)</code> AgenticLoop + LaneQueue</td>
                </tr>
                <tr>
                  <td>Layering</td>
                  <td>single CLI</td>
                  <td>single CLI</td>
                  <td>gateway-centric</td>
                  <td>agent + skills</td>
                  <td>3-file contract</td>
                  <td>5 layers: Model / Runtime / Harness / Agent / Self-Improving</td>
                </tr>
                <tr>
                  <td>Memory</td>
                  <td>bash session + <code>~/.claude</code></td>
                  <td>none</td>
                  <td>per-channel store</td>
                  <td>persistent + skill catalog</td>
                  <td><code>program.md</code></td>
                  <td>5-tier: Identity / User Profile / Org / Project / Session (<code>core/memory/context.py</code>)</td>
                </tr>
                <tr>
                  <td>Self-verification</td>
                  <td>none</td>
                  <td>sandbox</td>
                  <td>policy chain</td>
                  <td>none</td>
                  <td>ratchet</td>
                  <td>Petri adversarial audit + margin gate + prompt-hash ratchet</td>
                </tr>
                <tr>
                  <td>Automation trigger</td>
                  <td>hooks (manual)</td>
                  <td>none</td>
                  <td>cron + standing orders</td>
                  <td>skill auto-generate</td>
                  <td>overnight loop</td>
                  <td>hook events + scheduler + the auto-trigger sidecar</td>
                </tr>
                <tr>
                  <td>Multi-LLM</td>
                  <td>Anthropic only</td>
                  <td>OpenAI only</td>
                  <td>8+ providers</td>
                  <td>Anthropic-centric</td>
                  <td>(single)</td>
                  <td>3-provider routing (Anthropic / OpenAI+Codex / GLM) with PAYG, OAuth, and CLI adapter lanes</td>
                </tr>
                <tr>
                  <td>Sub-agent</td>
                  <td>Task tool</td>
                  <td>none</td>
                  <td>plugin</td>
                  <td>spawn + announce</td>
                  <td>none</td>
                  <td>Borrowed: Task tool + OpenClaw Spawn+Announce (<code>core/agent/sub_agent.py</code>)</td>
                </tr>
                <tr>
                  <td>Sandbox</td>
                  <td>none</td>
                  <td>OS-level</td>
                  <td>gateway isolation</td>
                  <td>none</td>
                  <td>constraint loop</td>
                  <td>6-layer PolicyChain (<code>core/tools/policy.py</code>)</td>
                </tr>
              </tbody>
            </table>

            <h3>The combination only GEODE ships</h3>
            <ul>
              <li>
                <strong>An explicit self-improving layer</strong>. The fifth
                layer mutates a scaffold of seven behaviour kinds, selects via
                Petri 22-dim audits and a margin gate, and preserves lineage as
                a git champion chain (<code>core/self_improving/</code>). No
                weight or parameter updates anywhere; the mechanism is
                selection.
              </li>
              <li>
                <strong>MCP in both directions</strong>. <code>core/mcp/</code>{" "}
                is the client that attaches external MCP servers, and{" "}
                <code>geode-mcp</code> (<code>core/mcp_server.py</code>) is the
                first-class server that exposes GEODE itself as a tool to
                external hosts. None of the compared systems ships both
                directions from one runtime.
              </li>
              <li>
                <strong>No-fallback default</strong>.{" "}
                <code>[model.fallbacks]</code> ships empty: a primary failure
                surfaces as an honest error instead of a silent cross-provider
                swap, and chains are opt-in via{" "}
                <code>~/.geode/routing.toml</code>{" "}
                (<code>core/llm/router/calls/_failover.py</code>).
              </li>
              <li>
                <strong>ChatGPT Plus JWT verification</strong>. The{" "}
                <code>chatgpt_plan_type</code> claim is extracted from the
                access token at OAuth time and embedded in the plan record
                (<code>core/auth/oauth_login.py</code>); no separate API call
                for the entitlement check.
              </li>
            </ul>

            <h2>Prompt definition layer</h2>
            <table>
              <thead><tr><th>Axis</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>Source location</td><td><code>core/llm/prompts/*.md</code> (external markdown)</td><td><code>agent/prompt_builder.py</code> (Python const)</td><td><code>src/agents/system-prompt.ts</code> (TS const)</td><td><code>constants/prompts.ts</code> (TS const)</td></tr>
                <tr><td>Build time</td><td>Hashed at module import, assembled per turn</td><td>Session start (cached)</td><td>Per-call modular</td><td>Per-turn dynamic</td></tr>
                <tr><td>User memory</td><td>5-tier <code>~/.geode/memory/</code></td><td>Frozen JSON snapshot</td><td>Workspace HEARTBEAT.md</td><td>CLAUDE.md (4-tier)</td></tr>
                <tr><td>Skill format</td><td>Markdown block (<code>{`{skill_context}`}</code> in <code>core/agent/loop/_context.py</code>)</td><td>XML <code>&lt;available_skills&gt;</code></td><td>XML <code>&lt;available_skills&gt;</code></td><td>XML registry</td></tr>
              </tbody>
            </table>

            <h2>Hashing and integrity</h2>
            <table>
              <thead><tr><th>Axis</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>Algorithm</td><td>SHA-256[:12]</td><td>None</td><td>SHA-256 (full)</td><td>SHA-256[:3]</td></tr>
                <tr><td>Pin / CI gate</td><td><strong>Yes</strong>: <code>_PINNED_HASHES</code> + <code>verify_prompt_integrity</code> (<code>core/llm/prompts/__init__.py</code>)</td><td>None</td><td>Detection only</td><td>None (attribution only)</td></tr>
                <tr><td>Normalization</td><td>UTF-8 / json sort_keys</td><td>mtime + size manifest</td><td>CRLF strip + sort + lowercase</td><td>(model, toolNames, sysLen) tuple</td></tr>
              </tbody>
            </table>

            <h2>Prompt caching</h2>
            <table>
              <thead><tr><th>Axis</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>Anthropic ephemeral</td><td>Yes: static/dynamic boundary split</td><td>Yes: system_and_3</td><td>Yes: boundary marker</td><td>Yes: global/org scope</td></tr>
                <tr><td>Boundary marker</td><td><code>PROMPT_CACHE_BOUNDARY</code> = <code>&lt;dynamic_context&gt;</code> (<code>core/agent/system_prompt.py</code>)</td><td>None</td><td><code>&lt;!-- OPENCLAW_CACHE_BOUNDARY --&gt;</code></td><td><code>__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__</code></td></tr>
                <tr><td>Messages history cache</td><td>Yes: rolling breakpoints on recent user messages (<code>apply_messages_cache_control</code>, <code>core/llm/providers/anthropic.py</code>)</td><td>Yes: last 3</td><td>Yes: last user message</td><td>Yes: last user blocks</td></tr>
              </tbody>
            </table>
            <p>
              The other half of cache stability is reminder placement: GEODE
              appends the system reminder as the last message on a per-request
              copy (<code>core/agent/system_injection.py</code>), so the shared
              history prefix stays byte-stable across rounds.
            </p>

            <h2>Observability</h2>
            <table>
              <thead><tr><th>Axis</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>Primary channel</td><td><code>PROMPT_ASSEMBLED</code> hook payload (<code>core/agent/loop/agent_loop.py</code>)</td><td>60-char preview log</td><td><code>cache-trace.ts</code> JSONL</td><td><code>logEvent(&apos;tengu_*&apos;)</code> telemetry</td></tr>
                <tr><td>External tracing</td><td>Optional OTLP (<code>core/observability/otel_export.py</code>)</td><td>None</td><td>Self JSONL</td><td>Self telemetry</td></tr>
              </tbody>
            </table>

            <h2>Security</h2>
            <table>
              <thead><tr><th>Axis</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>Prompt-injection scan</td><td>None (open GAP)</td><td><strong>11 patterns</strong> + invisible Unicode</td><td>Path/URL sanitization</td><td>Trusts user intent</td></tr>
                <tr><td>Override policy</td><td>Append-only (caller <code>system_suffix</code>)</td><td>Append-only</td><td>Append-only</td><td>Priority chain</td></tr>
              </tbody>
            </table>

            <h2>Why GEODE was the only one to ratchet</h2>
            <p>
              GEODE&apos;s prompts live in markdown files. Hermes, OpenClaw, and
              Claude Code keep prompts as inline strings inside TypeScript or
              Python source. Inline strings fight a hash-based ratchet through
              autoformatter noise, IDE renames, and merge-conflict resolutions.
              External markdown makes the file the unit of change, and the hash
              becomes meaningful.
            </p>
            <p>
              The cost is explicit too: every intentional prompt change pays one
              extra re-pin commit. In exchange, unintentional changes never
              ship, enforced by CI. The full shape is in{" "}
              <a href="/geode/docs/explanation/ratchet">Why ratchet discipline</a>.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
