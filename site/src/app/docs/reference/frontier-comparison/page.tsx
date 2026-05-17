import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Frontier Comparison — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="reference/frontier-comparison"
      title="Frontier Comparison"
      titleKo="프론티어 비교"
      summary="GEODE side-by-side with five frontier harnesses — Hermes, OpenClaw, Claude Code, Codex CLI, and Karpathy autoresearch — first at the architectural level, then drilling into prompt-system internals."
      summaryKo="GEODE를 다섯 frontier 하네스 (Hermes, OpenClaw, Claude Code, Codex CLI, Karpathy autoresearch)와 나란히 비교. 먼저 아키텍처 수준, 이후 프롬프트 시스템 내부로 파고듭니다."
    >
      <Bi
        ko={
          <>
            <h2>시스템 수준 포지셔닝</h2>
            <p>
              6개 하네스에 걸친 최상위 차이. GEODE는 종합입니다. 각 행은 최소 하나의 frontier
              시스템에서 빌려옵니다. 소스에 명시적으로 인용된 패턴은 다음과 같습니다.
              Claude Code <code>while(tool_use)</code>, Codex CLI sandbox-default, OpenClaw
              <code>Policy Chain</code> + <code>Lane Queue</code>, Karpathy P1-P10.
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
                  <td>domain-neutral core, DomainPort 통해 외부 플러그인 연결</td>
                </tr>
                <tr>
                  <td>주요 기본 단위</td>
                  <td><code>while(tool_use)</code></td>
                  <td>sandbox + approve</td>
                  <td>gateway + lane</td>
                  <td>skill loop</td>
                  <td>branchless dumb platform</td>
                  <td>StateGraph + agentic 루프</td>
                </tr>
                <tr>
                  <td>메모리</td>
                  <td>bash 세션 + <code>~/.claude</code></td>
                  <td>—</td>
                  <td>채널별 저장소</td>
                  <td>persistent + skill 카탈로그</td>
                  <td><code>program.md</code></td>
                  <td>5계층 (Org / Project / Session / Vault / Breadcrumb)</td>
                </tr>
                <tr>
                  <td>검증</td>
                  <td>—</td>
                  <td>sandbox</td>
                  <td>policy chain</td>
                  <td>—</td>
                  <td>ratchet</td>
                  <td><strong>G1-G4 + Cross-LLM + Rights Risk</strong></td>
                </tr>
                <tr>
                  <td>자동화 트리거</td>
                  <td>훅 (수동)</td>
                  <td>—</td>
                  <td>cron + standing order</td>
                  <td>skill auto-generate</td>
                  <td>overnight 루프</td>
                  <td>58 이벤트 + 스케줄러</td>
                </tr>
                <tr>
                  <td>멀티 LLM</td>
                  <td>Anthropic only</td>
                  <td>OpenAI only</td>
                  <td>8+ providers</td>
                  <td>Anthropic-centric</td>
                  <td>(single)</td>
                  <td>4 프로바이더 (Anthropic + Codex + PAYG + GLM)</td>
                </tr>
                <tr>
                  <td>서브 에이전트</td>
                  <td>Task tool</td>
                  <td>—</td>
                  <td>plugin</td>
                  <td>spawn + announce</td>
                  <td>—</td>
                  <td>차용 (Task tool + OpenClaw Spawn+Announce)</td>
                </tr>
                <tr>
                  <td>샌드박스</td>
                  <td>—</td>
                  <td>OS 수준</td>
                  <td>gateway 격리</td>
                  <td>—</td>
                  <td>제약 루프</td>
                  <td>6계층 Policy Chain</td>
                </tr>
              </tbody>
            </table>

            <h3>GEODE만이 가진 것</h3>
            <ul>
              <li>
                <strong>도메인 검증 분리</strong>. 편향 검출과 golden-set 캘리브레이션은
                외부 도메인 플러그인이 소유합니다. GEODE 코어는 G1-G4, Cross-LLM,
                Rights Risk와 런타임 경계만 유지합니다.
              </li>
              <li>
                <strong>Cause-Action 결정 트리</strong>. 6 cause → 5 action이
                외부 도메인 플러그인에서 제공됩니다. 코어는 런타임 경계만 유지합니다.
              </li>
              <li>
                <strong>플러그인 독립 캘리브레이션</strong>. Golden Set, fixture 비교,
                PASS 임계값은 플러그인 패키지에서 버전 관리됩니다.
              </li>
              <li>
                <strong>Equivalence-class 폴백</strong>. 프로바이더 변형 (예)
                <code>openai-codex</code> ↔ <code>openai</code> PAYG)이 구독 우선순위 순서대로
                자동 시도됩니다. <code>core/auth/plan_registry.py:resolve_routing</code> 경유.
              </li>
              <li>
                <strong>ChatGPT Plus JWT 검증</strong>. auth claim <code>chatgpt_plan_type</code>이
                OAuth 시점에 추출되어 Plan 레코드에 임베드됩니다
                (<code>core/auth/oauth_login.py:331</code>). 엔타이틀먼트 확인에 별도 API 호출이
                필요 없습니다.
              </li>
            </ul>

            <h2>정의 계층</h2>
            <table>
              <thead><tr><th>축</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>소스 위치</td><td><code>core/llm/prompts/*.md</code></td><td><code>agent/prompt_builder.py</code> (Python const)</td><td><code>src/agents/system-prompt.ts</code> (TS const)</td><td><code>constants/prompts.ts</code> (TS const)</td></tr>
                <tr><td>빌드 시점</td><td>모듈 임포트</td><td>세션 시작 (캐시)</td><td>호출별 모듈식</td><td>턴별 동적</td></tr>
                <tr><td>사용자 메모리</td><td>5계층 <code>~/.geode/memory/</code></td><td>Frozen JSON 스냅샷</td><td>Workspace HEARTBEAT.md</td><td>CLAUDE.md (4계층)</td></tr>
              </tbody>
            </table>

            <h2>어셈블리</h2>
            <table>
              <thead><tr><th>축</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>결과 타입</td><td><code>AssembledPrompt(frozen=True)</code></td><td><code>str</code> 캐시됨</td><td>String 반환</td><td><code>TextBlockParam[]</code></td></tr>
                <tr><td>오버라이드 정책</td><td>기본 append-only</td><td>파라미터로 append</td><td>파라미터로 append</td><td>5단계 우선순위 체인</td></tr>
                <tr><td>스킬 포맷</td><td>Markdown 블록</td><td>XML <code>&lt;available_skills&gt;</code></td><td>XML <code>&lt;available_skills&gt;</code></td><td>XML 레지스트리</td></tr>
                <tr><td>Truncation 이벤트 로그</td><td>훅의 <code>truncation_events</code></td><td>로거만</td><td>Report 객체</td><td>추적 안 함</td></tr>
              </tbody>
            </table>

            <h2>해싱 및 무결성</h2>
            <table>
              <thead><tr><th>축</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>알고리즘</td><td>SHA-256[:12]</td><td>None</td><td>SHA-256 (전체)</td><td>SHA-256[:3]</td></tr>
                <tr><td>핀 / CI 게이트</td><td><strong>예</strong>. <code>_PINNED_HASHES</code> × 18</td><td>None</td><td>탐지만</td><td>None (attribution만)</td></tr>
                <tr><td>정규화</td><td>UTF-8 / json sort_keys</td><td>mtime + size manifest</td><td>CRLF strip + sort + lowercase</td><td>(model, toolNames, sysLen) tuple</td></tr>
              </tbody>
            </table>

            <h2>캐싱</h2>
            <table>
              <thead><tr><th>축</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>Anthropic ephemeral</td><td>예. system + STATIC/DYNAMIC</td><td>예. system_and_3</td><td>예. 경계 마커</td><td>예. global/org scope</td></tr>
                <tr><td>경계 마커</td><td><code>__GEODE_PROMPT_CACHE_BOUNDARY__</code></td><td>None</td><td><code>&lt;!-- OPENCLAW_CACHE_BOUNDARY --&gt;</code></td><td><code>__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__</code></td></tr>
                <tr><td>메시지 히스토리 캐시</td><td>No (오픈 GAP)</td><td>예. 직전 3</td><td>예. 직전 user 메시지</td><td>예. 직전 user 블록</td></tr>
                <tr><td>사용 breakpoint / 4</td><td>1-2</td><td>4</td><td>2-3</td><td>3-4</td></tr>
              </tbody>
            </table>

            <h2>관측성</h2>
            <table>
              <thead><tr><th>축</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>주 채널</td><td><code>PROMPT_ASSEMBLED</code> 훅 payload</td><td>60자 preview 로그</td><td><code>cache-trace.ts</code> JSONL</td><td><code>logEvent('tengu_*')</code> 텔레메트리</td></tr>
                <tr><td>외부 트레이싱</td><td>OTLP optional</td><td>None</td><td>자체 JSONL</td><td>자체 텔레메트리</td></tr>
                <tr><td>트레이스의 프롬프트 텍스트</td><td>해시만</td><td>세션 DB에 저장</td><td>기본은 해시</td><td>텔레메트리에 없음</td></tr>
              </tbody>
            </table>

            <h2>보안</h2>
            <table>
              <thead><tr><th>축</th><th>GEODE</th><th>Hermes</th><th>OpenClaw</th><th>Claude Code</th></tr></thead>
              <tbody>
                <tr><td>프롬프트 인젝션 스캔</td><td>없음 (오픈 GAP)</td><td><strong>11 패턴</strong> + invisible Unicode</td><td>경로 / URL 정화</td><td>사용자 의도 신뢰</td></tr>
                <tr><td>Frozen 결과</td><td><code>frozen=True</code></td><td>관례</td><td>관례</td><td>관례</td></tr>
                <tr><td>오버라이드 보안</td><td>기본 append-only</td><td>append-only</td><td>append-only</td><td>우선순위 체인</td></tr>
              </tbody>
            </table>

            <h2>왜 GEODE만이 ratchet으로 갈 수 있었나</h2>
            <p>
              GEODE의 프롬프트는 markdown 파일에 살고 있습니다. Hermes, OpenClaw, Claude Code는
              프롬프트를 각각 TypeScript 또는 Python 소스 내부의 인라인 문자열로 유지합니다.
              인라인 문자열은 자동 포맷터 노이즈, IDE 리네임, 머지 충돌 해소 과정에서
              hashlib 기반 ratchet과 싸우게 됩니다. 외부 markdown은 파일을 변경 단위로 만들고,
              그래서 해시가 의미를 갖게 됩니다.
            </p>
            <p>
              비용은 이렇습니다. GEODE는 의도된 프롬프트 변경 시 한 단계 (재핀)를 더 지불하지만,
              그 대가로 의도하지 않은 변경이 절대 출시되지 않는다는 CI 강제 보장을 얻습니다.
            </p>
          </>
        }
        en={
          <>
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
                  <td>domain-neutral core, external plugins via DomainPort</td>
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
                  <td><strong>G1-G4 + Cross-LLM + Rights Risk</strong></td>
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
                <strong>Domain verification separation</strong> — bias detection
                and golden-set calibration are owned by external domain plugins.
                GEODE core keeps G1-G4, Cross-LLM, Rights Risk, and the runtime
                boundary.
              </li>
              <li>
                <strong>Cause-Action decision tree</strong> — 6 causes →
                5 actions supplied by external domain plugins. Core keeps the
                runtime boundary only.
              </li>
              <li>
                <strong>Plugin-owned calibration</strong> — Golden Sets, fixture
                comparisons, and PASS thresholds are versioned with the plugin
                package.
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
                <tr><td>Pin / CI gate</td><td><strong>Yes</strong> — <code>_PINNED_HASHES</code> × 18</td><td>None</td><td>Detection only</td><td>None (attribution only)</td></tr>
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
                <tr><td>External tracing</td><td>Optional OTLP</td><td>None</td><td>Self JSONL</td><td>Self telemetry</td></tr>
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
          </>
        }
      />
    </DocsShell>
  );
}
