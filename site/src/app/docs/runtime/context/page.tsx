import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Context System — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/context"
      title="Context System"
      titleKo="컨텍스트 시스템"
      summary="5-tier memory hierarchy plus 5-layer prompt assembly plus 200K token guard. Every LLM call's context is built here."
      summaryKo="5계층 메모리 + 5층 프롬프트 어셈블리 + 200K 토큰 가드. 모든 LLM 호출의 컨텍스트가 여기서 조립됩니다."
    >
      <Bi
        ko={
          <>
            <p>
              <strong>Reference:</strong> GEODE의 컨텍스트 시스템은 4개의 분리된 메커니즘이 합쳐진 결과입니다.
              메모리 계층(5-tier), 프롬프트 어셈블리(5-layer), 토큰 예산 가드(200K), Clean Context 패턴(anchoring 방지).
              모든 LLM 호출 직전에 이 4개가 차례로 작동해 단일 <code>AssembledPrompt</code>를 만들어 모델에 전달합니다.
            </p>

            <h2>1. 메모리 계층 (5-tier)</h2>
            <p>
              하위 tier가 상위 tier를 override합니다. Claude Code의 3-tier memory를 5-tier로 일반화한 형태.
            </p>
            <table>
              <thead><tr><th>Tier</th><th>이름</th><th>위치</th><th>역할</th></tr></thead>
              <tbody>
                <tr><td><strong>0</strong></td><td>Agent Identity</td><td><code>GEODE.md</code></td><td>에이전트 정체성, 제약, 도메인 규칙. 항상 첫머리에 들어감.</td></tr>
                <tr><td><strong>1</strong></td><td>User Profile</td><td><code>~/.geode/profile.md</code></td><td>사용자 역할, 전문성, 학습된 패턴. bidirectional learning이 갱신.</td></tr>
                <tr><td><strong>2</strong></td><td>Organization</td><td><code>~/.geode/org/</code></td><td>cross-project 공유 데이터. 다수 프로젝트가 공통 참조.</td></tr>
                <tr><td><strong>3</strong></td><td>Project</td><td><code>./.geode/memory/PROJECT.md</code></td><td>현 프로젝트의 50개 insight. LRU 회전.</td></tr>
                <tr><td><strong>4</strong></td><td>Session</td><td>in-memory</td><td>현재 대화 history. 200-turn sliding window.</td></tr>
              </tbody>
            </table>
            <p>
              토큰 예산 (default): Identity 10%, Profile 5%, Org 25%, Project 25%, Session 35%. 합 100%, 200K 컨텍스트 윈도 기준.
            </p>

            <h2>2. 프롬프트 어셈블리 (5-layer)</h2>
            <p>
              <code>core/llm/prompt_assembler.py:PromptAssembler.assemble()</code>이 6 단계로 프롬프트를 조립합니다.
              결과는 불변(<code>frozen=True</code>) <code>AssembledPrompt</code> 객체.
            </p>
            <pre>{`@dataclass(frozen=True)
class AssembledPrompt:
    system: str                 # 최종 시스템 프롬프트
    user: str                   # 최종 사용자 프롬프트
    assembled_hash: str         # SHA-256[:12] of (system + user)
    base_template_hash: str     # SHA-256[:12] of original base_system
    fragment_count: int
    total_chars: int
    fragments_used: list[str]   # 추적용 식별자`}</pre>
            <table>
              <thead><tr><th>Layer</th><th>내용</th><th>출처</th></tr></thead>
              <tbody>
                <tr><td>L1</td><td>Agent base persona</td><td>node-specific base_system (analyst, evaluator, ...)</td></tr>
                <tr><td>L2</td><td>Memory injection</td><td>5-tier memory 위 표</td></tr>
                <tr><td>L3</td><td>Skill injection</td><td><code>SkillRegistry</code>의 활성 스킬</td></tr>
                <tr><td>L4</td><td>Tool definitions</td><td><code>core/tools/definitions.json</code> (deferred 도구 제외)</td></tr>
                <tr><td>L5</td><td>Cache boundary marker</td><td><code>__GEODE_PROMPT_CACHE_BOUNDARY__</code> 또는 <code>&lt;dynamic_context&gt;</code> XML (v0.93+)</td></tr>
              </tbody>
            </table>
            <p>
              어셈블 직후 <code>PROMPT_ASSEMBLED</code> hook이 발화되어 어셈블된 프롬프트의 fingerprint(hash, fragment_count, total_chars)가 관측 stack에 흐릅니다.
            </p>

            <h2>3. 200K 절대 토큰 가드 (v0.40+)</h2>
            <p>
              200K 윈도 모델이라도 percent 기반 threshold (80%, 95%) 와 별도로 절대 200K ceiling을 둡니다.
              GLM처럼 정확 윈도가 202_752인 경우에도 200_000 cap을 적용해 rate-limit pool 분리 회피.
            </p>
            <ul>
              <li><strong>80% threshold</strong>: Phase 1 compaction. 도구 결과를 요약 텍스트로 압축.</li>
              <li><strong>95% threshold</strong>: Phase 2 compaction. 70% adaptive prune (oldest 메시지 우선).</li>
              <li><strong>200K 절대 cap</strong>: graceful drain. 진행 중 도구 호출 마감 후 종료.</li>
              <li><strong>25K MCP 결과 가드</strong>: 한 도구 호출의 결과가 25K 토큰 넘으면 HTML→Markdown 폴백.</li>
            </ul>
            <p>
              v0.94.0에서 GLM context window를 200_000 flat → 정확 202_752로 정정. 200K guard는 그대로 유지되며 절대 ceiling으로 동작합니다.
            </p>

            <h2>4. Clean Context (anchoring 방지)</h2>
            <p>
              병렬 Analyst들이 같은 입력으로 동시 호출될 때, 한 Analyst의 결과를 다른 Analyst의 컨텍스트에 노출하면
              <strong>anchoring bias</strong>가 발생합니다. GEODE는 병렬 분석에 들어가는 컨텍스트에서 <code>analyses</code> 필드를 제외합니다.
            </p>
            <p>
              구현: <code>core/agent/loop.py</code>의 Send API 호출 시 <code>state.copy(exclude={"analyses"})</code>로 노드 입력을 정제.
              검증: <code>verify_independence</code> 가드가 Analyst 결과의 cross-correlation (CV &lt; 0.05) 을 확인하고 anchoring 의심 시 RESCORE.
            </p>

            <h2>5. 캐싱 인터페이스</h2>
            <p>
              어셈블된 프롬프트의 STATIC 영역(L1+L2+L3+L4)과 DYNAMIC 영역(L5 이후 turn별 변경분)을 경계로 분리해 cache_control을 적용.
            </p>
            <ul>
              <li><strong>Anthropic</strong>. system 블록 <code>cache_control: ephemeral</code> + 직전 3개 non-system 메시지의 <code>apply_messages_cache_control()</code>. 4-breakpoint.</li>
              <li><strong>OpenAI</strong>. 서버 측 자동 캐싱. v0.94+ <code>prompt_cache_key</code> 자동 도출.</li>
              <li><strong>GLM, Codex</strong>. 프로바이더 관리.</li>
            </ul>
            <p>
              자세히: <a href="/docs/runtime/llm/prompt-caching">Prompt Caching</a>.
            </p>

            <h2>다른 시스템 비교</h2>
            <table>
              <thead><tr><th>시스템</th><th>memory tier</th><th>prompt 조립</th><th>토큰 가드</th></tr></thead>
              <tbody>
                <tr><td><strong>GEODE</strong></td><td>5-tier (Identity → Profile → Org → Project → Session)</td><td>5-layer + Hook 관측</td><td>200K 절대 + 80/95% phase + 25K MCP</td></tr>
                <tr><td>Claude Code</td><td>4-tier (managed → user → project → local) CLAUDE.md</td><td>도구 정의 + system prompt 직접 조립</td><td>200K window 안의 자동 compaction</td></tr>
                <tr><td>LangChain Memory</td><td>BufferMemory / ConversationBufferWindowMemory 등 9종</td><td>수동 prompt template</td><td>token_limit 옵션 (수동)</td></tr>
                <tr><td>LlamaIndex Context</td><td>Index → Retriever → Synthesizer</td><td>response_synthesizer로 prompt</td><td>chunk_size + chunk_overlap 수동</td></tr>
              </tbody>
            </table>

            <h2>관련 문서</h2>
            <ul>
              <li>cache 메커니즘: <a href="/docs/runtime/llm/prompt-caching">Prompt Caching</a></li>
              <li>해시 ratchet: <a href="/docs/runtime/llm/prompt-hashing">Prompt Hashing</a></li>
              <li>system prompt 변형: <a href="/docs/runtime/llm/system-prompt-modes">System Prompt Modes</a></li>
              <li>장기 실행 가드: <a href="/docs/ops/long-running">Long-running Safety</a></li>
              <li>외부 사료: <code>mango-wiki/.../concepts/geode-memory-system.md</code>, <code>geode-prompt-assembly.md</code>, <code>geode-context-guard.md</code>, <code>geode-context-overflow-prevention.md</code></li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              <strong>Reference:</strong> GEODE's context system is the union of four separate mechanisms.
              Memory hierarchy (5 tiers), prompt assembly (5 layers), token budget guards (200K), and the Clean Context
              pattern (anchoring prevention). Every LLM call runs these four in order to produce a single
              <code> AssembledPrompt</code> that is then sent to the model.
            </p>

            <h2>1. Memory hierarchy (5 tiers)</h2>
            <p>
              Lower tiers override higher tiers. This generalizes Claude Code's 3-tier CLAUDE.md memory model into 5 tiers.
            </p>
            <table>
              <thead><tr><th>Tier</th><th>Name</th><th>Location</th><th>Role</th></tr></thead>
              <tbody>
                <tr><td><strong>0</strong></td><td>Agent Identity</td><td><code>GEODE.md</code></td><td>Identity, constraints, domain rules. Always at the top of the prompt.</td></tr>
                <tr><td><strong>1</strong></td><td>User Profile</td><td><code>~/.geode/profile.md</code></td><td>User role, expertise, learned patterns. Updated by bidirectional learning.</td></tr>
                <tr><td><strong>2</strong></td><td>Organization</td><td><code>~/.geode/org/</code></td><td>Cross-project shared data. Several projects can read.</td></tr>
                <tr><td><strong>3</strong></td><td>Project</td><td><code>./.geode/memory/PROJECT.md</code></td><td>50 insights for the current project. LRU rotation.</td></tr>
                <tr><td><strong>4</strong></td><td>Session</td><td>in-memory</td><td>Current conversation history. 200-turn sliding window.</td></tr>
              </tbody>
            </table>
            <p>
              Default token budget: Identity 10%, Profile 5%, Org 25%, Project 25%, Session 35%. Sums to 100% inside a
              200K context window.
            </p>

            <h2>2. Prompt assembly (5 layers)</h2>
            <p>
              <code>core/llm/prompt_assembler.py:PromptAssembler.assemble()</code> runs through six steps. The output is
              a frozen <code>AssembledPrompt</code>.
            </p>
            <pre>{`@dataclass(frozen=True)
class AssembledPrompt:
    system: str                 # final system prompt
    user: str                   # final user prompt
    assembled_hash: str         # SHA-256[:12] of (system + user)
    base_template_hash: str     # SHA-256[:12] of the original base_system
    fragment_count: int
    total_chars: int
    fragments_used: list[str]   # trace identifiers`}</pre>
            <table>
              <thead><tr><th>Layer</th><th>Content</th><th>Source</th></tr></thead>
              <tbody>
                <tr><td>L1</td><td>Agent base persona</td><td>Node-specific base_system (analyst, evaluator, ...).</td></tr>
                <tr><td>L2</td><td>Memory injection</td><td>5-tier memory above.</td></tr>
                <tr><td>L3</td><td>Skill injection</td><td>Active skills from <code>SkillRegistry</code>.</td></tr>
                <tr><td>L4</td><td>Tool definitions</td><td><code>core/tools/definitions.json</code> (excluding deferred tools).</td></tr>
                <tr><td>L5</td><td>Cache boundary marker</td><td><code>__GEODE_PROMPT_CACHE_BOUNDARY__</code> or <code>&lt;dynamic_context&gt;</code> XML since v0.93.</td></tr>
              </tbody>
            </table>
            <p>
              Right after assembly, the <code>PROMPT_ASSEMBLED</code> hook fires and emits the assembled prompt's
              fingerprint (hash, fragment_count, total_chars) into the observability stack.
            </p>

            <h2>3. 200K absolute token guard (since v0.40)</h2>
            <p>
              Even for 200K-window models, an absolute 200K ceiling lives next to the percent-based thresholds (80%,
              95%). GLM's exact window is 202_752, but the 200_000 cap is still applied to avoid rate-limit pool
              splits.
            </p>
            <ul>
              <li><strong>80% threshold</strong>: Phase 1 compaction. Tool results are summarized.</li>
              <li><strong>95% threshold</strong>: Phase 2 compaction. 70% adaptive prune (oldest messages first).</li>
              <li><strong>200K absolute cap</strong>: graceful drain. Finish active tool calls and exit.</li>
              <li><strong>25K MCP result guard</strong>: if a single tool result exceeds 25K, HTML to Markdown fallback fires.</li>
            </ul>
            <p>
              v0.94.0 corrected the GLM context window from a flat 200_000 to the exact 202_752. The 200K guard stays
              in place as the absolute ceiling.
            </p>

            <h2>4. Clean Context (anchoring prevention)</h2>
            <p>
              When parallel Analysts run on the same input, exposing one Analyst's result to another in the context
              creates <strong>anchoring bias</strong>. GEODE strips the <code>analyses</code> field from the context
              passed into parallel analysis nodes.
            </p>
            <p>
              Implementation: <code>core/agent/loop.py</code> calls Send API with <code>state.copy(exclude=\"analyses\")</code>.
              Verification: a <code>verify_independence</code> guard checks the cross-correlation
              (CV &lt; 0.05) of Analyst results, and triggers RESCORE on suspected anchoring.
            </p>

            <h2>5. Caching interface</h2>
            <p>
              The assembled prompt's STATIC region (L1+L2+L3+L4) and DYNAMIC region (L5 and turn-dependent suffix) split
              at the boundary marker, enabling cache_control.
            </p>
            <ul>
              <li><strong>Anthropic</strong>: <code>cache_control: ephemeral</code> on the system block plus <code>apply_messages_cache_control()</code> over the last three non-system messages, for a 4-breakpoint setup.</li>
              <li><strong>OpenAI</strong>: server-side automatic caching. Since v0.94 a <code>prompt_cache_key</code> is auto-derived.</li>
              <li><strong>GLM, Codex</strong>: provider-managed.</li>
            </ul>
            <p>
              Details: <a href="/docs/runtime/llm/prompt-caching">Prompt Caching</a>.
            </p>

            <h2>Comparison with other systems</h2>
            <table>
              <thead><tr><th>System</th><th>Memory tiers</th><th>Prompt assembly</th><th>Token guard</th></tr></thead>
              <tbody>
                <tr><td><strong>GEODE</strong></td><td>5 tiers (Identity → Profile → Org → Project → Session)</td><td>5 layers + Hook observability</td><td>200K absolute + 80/95% phases + 25K MCP</td></tr>
                <tr><td>Claude Code</td><td>4 tiers (managed → user → project → local) CLAUDE.md</td><td>Tool definitions plus system prompt assembled directly</td><td>Automatic compaction within the 200K window</td></tr>
                <tr><td>LangChain Memory</td><td>BufferMemory / ConversationBufferWindowMemory and seven more</td><td>Manual prompt templates</td><td><code>token_limit</code> option (manual)</td></tr>
                <tr><td>LlamaIndex Context</td><td>Index → Retriever → Synthesizer</td><td>response_synthesizer prompt</td><td>Manual <code>chunk_size</code> plus <code>chunk_overlap</code></td></tr>
              </tbody>
            </table>

            <h2>Related</h2>
            <ul>
              <li>Cache mechanism: <a href="/docs/runtime/llm/prompt-caching">Prompt Caching</a></li>
              <li>Hash ratchet: <a href="/docs/runtime/llm/prompt-hashing">Prompt Hashing</a></li>
              <li>System prompt variants: <a href="/docs/runtime/llm/system-prompt-modes">System Prompt Modes</a></li>
              <li>Long-running guards: <a href="/docs/ops/long-running">Long-running Safety</a></li>
              <li>External sources: <code>mango-wiki/.../concepts/geode-memory-system.md</code>, <code>geode-prompt-assembly.md</code>, <code>geode-context-guard.md</code>, <code>geode-context-overflow-prevention.md</code></li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
