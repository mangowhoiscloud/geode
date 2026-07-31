import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";
import architectureBaseline from "@/data/geode/architecture-baseline.json";

export const metadata = { title: "Hooks and middleware — GEODE Docs" };

const hookContracts = [
  { name: "UserPromptSubmit", payload: "user_input", actions: "continue · rewrite · block" },
  { name: "PreToolUse", payload: "tool_name, arguments", actions: "continue · rewrite · block · request_permission" },
  { name: "PermissionRequest", payload: "tool_name, safety_level, detail", actions: "allow · deny · ask" },
  { name: "PostToolUse", payload: "tool_name, arguments, result, has_error, executed", actions: "continue · add_context · block" },
  { name: "PreCompact", payload: "model, provider, message_count, keep_recent, trigger, hard", actions: "continue · rewrite · defer" },
  { name: "PostCompact", payload: "model, provider, original_message_count, new_message_count, keep_recent, trigger, persisted", actions: "continue" },
  { name: "SessionStart", payload: "model, provider, resumed, status", actions: "continue" },
  { name: "SessionEnd", payload: "reason, status", actions: "continue" },
  { name: "SubagentStart", payload: "task_id, task_type, description, child_session_key, parent_session_key", actions: "continue" },
  { name: "SubagentStop", payload: "task_id, task_type, success, status, duration_ms, error, child_session_key", actions: "continue" },
  { name: "PreVerify", payload: "termination_reason, rounds, tool_call_count, candidate_summary", actions: "continue · strengthen" },
  { name: "PostVerify", payload: "passed, mode, score, rubric_misses, termination_reason, rounds, tool_call_count, candidate_summary", actions: "accept · revise · escalate" },
  { name: "Stop", payload: "PostVerify fields + policy_action, evidence_refs", actions: "finalize · continue" },
];

const schemaExample = `from core.hooks import HookName, public_hook_schema

schema = public_hook_schema(HookName.POST_VERIFY)
print(schema["properties"]["payload"])
print(schema["properties"]["decision"])`;

export default function Page() {
  return (
    <DocsShell
      slug="harness/hooks"
      title="Hooks and middleware"
      titleKo="훅과 미들웨어"
      summary="Three extension surfaces: a small public contract, four trusted execution join points, and internal runtime telemetry."
      summaryKo="작은 공개 계약, 네 개의 신뢰 실행 결합점, 내부 런타임 텔레메트리로 나뉜 세 확장 표면입니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE의 확장 표면은 하나의 거대한 이벤트 목록이 아닙니다. 외부
              통합이 의존할 수 있는 <code>HookName</code>, 실행을 감싸는 신뢰
              표면 <code>MiddlewareRegistry</code>, 운영 관측을 위한{" "}
              <code>RuntimeEvent</code>로 역할과 권한을 분리합니다.
            </p>

            <h2>세 표면</h2>
            <table>
              <thead><tr><th>표면</th><th>용도</th><th>권한</th></tr></thead>
              <tbody>
                <tr><td>공개 훅</td><td>사용자 입력, 도구, 압축, 세션, 서브에이전트, 검증 경계</td><td>이름별로 허용된 typed decision만 반환</td></tr>
                <tr><td>신뢰 미들웨어</td><td>도구·LLM 요청 변환과 실제 실행 래핑</td><td>요청 단계는 변환, 실행 단계는 감싸기·단축 반환</td></tr>
                <tr><td>런타임 이벤트</td><td>메트릭, 감사, 저장, 운영 진단</td><td>내부 관측 전용. 실행 제어 계약이 아님</td></tr>
              </tbody>
            </table>

            <h2>공개 훅 13종</h2>
            <p>
              공개 목록은 의도적으로 작고 버전이 고정됩니다. 와일드카드 구독은
              없으며, 입력은 크기 제한·JSON 안전화·비밀값 제거를 거칩니다.
            </p>
            <table>
              <thead><tr><th>훅</th><th>필수 payload</th><th>허용 action</th></tr></thead>
              <tbody>
                {hookContracts.map((hook) => (
                  <tr key={hook.name}>
                    <td><code>{hook.name}</code></td>
                    <td><code>{hook.payload}</code></td>
                    <td>{hook.actions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p>
              이 allowlist 밖의 action과 payload 필드는 거부됩니다. 실패한 내장 검증을
              외부 훅이 pass로 뒤집을 수도 없습니다. <code>rewrite</code>는 비어 있지
              않은 <code>updates</code>, <code>PostVerify.revise</code>와
              <code>Stop.continue</code>는 비어 있지 않은 <code>instruction</code>이
              필요합니다.
            </p>

            <h2>공통 envelope와 제한</h2>
            <table>
              <thead><tr><th>항목</th><th>계약</th></tr></thead>
              <tbody>
                <tr><td>버전</td><td><code>geode.public-hook.v1</code></td></tr>
                <tr><td>상관관계</td><td><code>session_id</code>, <code>turn_id</code>, <code>run_id</code>, session generation, verify attempt, tool/LLM call ID</td></tr>
                <tr><td>payload 상한</td><td>문자열 4,096자, JSON 32 KiB, collection 64개, depth 8</td></tr>
                <tr><td>decision 상한</td><td>reason 1,024자, instruction 4,096자, evidence reference 32개</td></tr>
                <tr><td>기본 timeout</td><td>handler별 10초. sync handler는 event loop 밖에서 실행</td></tr>
                <tr><td>오류</td><td>현재 handler 오류를 기록하고 다음 handler를 계속 실행</td></tr>
              </tbody>
            </table>
            <p>
              각 hook의 Draft 2020-12 JSON Schema는 런타임에서 직접 조회합니다.
              문서 표와 직렬화 계약이 다르면 런타임 schema가 정본입니다.
            </p>
            <pre>{schemaExample}</pre>

            <h2>PostVerify와 외부 루프</h2>
            <p>
              <code>PostVerify</code>는 이미 실행된 부수 효과를 재생하지 않고,
              완성된 후보와 내장 검증 결과를 외부 평가기·CI 정책·오케스트레이터가
              판정하게 합니다. revise는 구체적인 후속 지시가 있어야 하며 최대 2회
              연속 시도로 제한됩니다. 최종 결과에는 모든 시도의 rounds, tool calls,
              usage가 합산된 뒤 증거와 체크포인트가 저장됩니다. escalate는 단순
              telemetry가 아니라 delivery gate입니다. 세션을 pause하고 후보를
              외부 소유자에게만 pending_text로 반환하며 terminal
              <code>session.ended</code>를 만들지 않습니다.
            </p>

            <h2>신뢰 미들웨어 4개 결합점</h2>
            <table>
              <thead><tr><th>결합점</th><th>계약</th></tr></thead>
              <tbody>
                <tr><td><code>tool_request</code></td><td>승인 전 도구명·인자를 순차 변환하고 다시 스키마 검증</td></tr>
                <tr><td><code>tool_execution</code></td><td>승인된 요청을 변경하지 않고 실제 executor를 async onion으로 감쌈</td></tr>
                <tr><td><code>llm_request</code></td><td>조립된 adapter request를 순차 변환. 캐시 prefix 변경은 명시 권한과 사유가 필요</td></tr>
                <tr><td><code>llm_execution</code></td><td>요청을 변경하지 않고 provider 실행을 감싸거나 단축 반환</td></tr>
              </tbody>
            </table>
            <p>
              실행 미들웨어의 <code>next_call</code>은 한 번만 호출할 수 있습니다.
              변환이 필요하면 반드시 request 결합점을 사용합니다.
            </p>

            <h2>내부 이벤트와 저장</h2>
            <p>
              현재 <code>RuntimeEvent</code>는{" "}
              {architectureBaseline.hook_events.count}개의 내부 관측 이벤트를
              가집니다. <code>HookEvent</code>/<code>HookSystem</code>은 기존
              통합을 위한 타입 별칭이며, 새 코드는{" "}
              <code>RuntimeEvent</code>/<code>RuntimeEventBus</code>를 사용합니다.
            </p>
            <table>
              <thead><tr><th>저장소</th><th>동작</th></tr></thead>
              <tbody>
                <tr><td>SQLite activity store</td><td>운영 이벤트의 정본. 공개 훅과 미들웨어 호출도 <code>extension.invoked</code> 행으로 저장</td></tr>
                <tr><td>RunTimeline <code>events.jsonl</code></td><td>활성 run projection이 있을 때만 같은 typed activity row를 미러링</td></tr>
              </tbody>
            </table>
            <p>
              확장 호출 행은 표면, 이름, 확장자, 상태, 지연, 상관 ID만 보존합니다.
              원문 사용자 입력, 전체 요청·응답, 개인 데이터, 비밀값은 저장하지
              않습니다.
            </p>

            <h2>도구 경계 순서</h2>
            <pre>{`tool_request → schema validation → PreToolUse → revalidation
→ hard deny / policy → PermissionRequest
→ tool_execution → TOOL_EXEC_STARTED → executor exactly once
→ TOOL_EXEC_ENDED or TOOL_EXEC_FAILED → PostToolUse`}</pre>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/guides/register-hook">공개 훅과 미들웨어 등록</a></li>
              <li><a href="/geode/docs/architecture/agentic-loop">Agentic loop</a></li>
              <li><a href="/geode/docs/harness/lifecycle">하네스 라이프사이클</a></li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE does not expose one giant event list as an extension API.
              It separates a stable external contract, <code>HookName</code>,
              trusted execution wrapping through <code>MiddlewareRegistry</code>,
              and operational telemetry through <code>RuntimeEvent</code>.
            </p>

            <h2>Three surfaces</h2>
            <table>
              <thead><tr><th>Surface</th><th>Purpose</th><th>Authority</th></tr></thead>
              <tbody>
                <tr><td>Public hooks</td><td>Input, tools, compaction, sessions, sub-agents, verification</td><td>Only hook-specific typed decisions</td></tr>
                <tr><td>Trusted middleware</td><td>Tool and LLM request transforms and execution wrapping</td><td>Transform at request time; wrap or short-circuit at execution time</td></tr>
                <tr><td>Runtime events</td><td>Metrics, audit, persistence, diagnostics</td><td>Internal observation, not an execution-control API</td></tr>
              </tbody>
            </table>

            <h2>Thirteen public hooks</h2>
            <p>
              The public allowlist is intentionally small and versioned. There
              are no wildcard subscriptions. Inputs are bounded, JSON-safe, and
              secret-redacted.
            </p>
            <table>
              <thead><tr><th>Hook</th><th>Required payload</th><th>Allowed actions</th></tr></thead>
              <tbody>
                {hookContracts.map((hook) => (
                  <tr key={hook.name}>
                    <td><code>{hook.name}</code></td>
                    <td><code>{hook.payload}</code></td>
                    <td>{hook.actions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p>
              Fields and actions outside this allowlist are rejected. An external
              hook also cannot turn a failed built-in verification into a pass.
              <code>rewrite</code> requires non-empty <code>updates</code>, while
              <code>PostVerify.revise</code> and <code>Stop.continue</code> require a
              non-empty <code>instruction</code>.
            </p>

            <h2>Common envelope and bounds</h2>
            <table>
              <thead><tr><th>Item</th><th>Contract</th></tr></thead>
              <tbody>
                <tr><td>Version</td><td><code>geode.public-hook.v1</code></td></tr>
                <tr><td>Correlation</td><td><code>session_id</code>, <code>turn_id</code>, <code>run_id</code>, session generation, verify attempt, and tool/LLM call IDs</td></tr>
                <tr><td>Payload bounds</td><td>4,096 characters per string, 32 KiB JSON, 64 collection items, depth 8</td></tr>
                <tr><td>Decision bounds</td><td>1,024-character reason, 4,096-character instruction, 32 evidence references</td></tr>
                <tr><td>Default timeout</td><td>10 seconds per handler; synchronous handlers run off the event loop</td></tr>
                <tr><td>Errors</td><td>Record the current handler error and continue with later handlers</td></tr>
              </tbody>
            </table>
            <p>
              Query each hook&apos;s Draft 2020-12 JSON Schema at runtime. If this
              table and the serialization contract ever differ, the runtime schema
              is authoritative.
            </p>
            <pre>{schemaExample}</pre>

            <h2>PostVerify for external loops</h2>
            <p>
              <code>PostVerify</code> lets an evaluator, CI policy, or outer
              orchestrator judge a completed candidate without replaying prior
              side effects. A revision requires a concrete follow-up instruction
              and is bounded to two continuation attempts. Before final evidence
              and checkpoint persistence, rounds, tool calls, and usage from all
              attempts are aggregated. Escalation is a delivery gate, not
              telemetry: it pauses the session, exposes the withheld candidate
              only to the owning loop as pending_text, and does not create a
              terminal <code>session.ended</code> record.
            </p>

            <h2>Four trusted middleware join points</h2>
            <table>
              <thead><tr><th>Join point</th><th>Contract</th></tr></thead>
              <tbody>
                <tr><td><code>tool_request</code></td><td>Sequentially transform tool name and arguments before approval, then revalidate</td></tr>
                <tr><td><code>tool_execution</code></td><td>Wrap the real executor as an async onion without changing the approved request</td></tr>
                <tr><td><code>llm_request</code></td><td>Sequentially transform the assembled adapter request; cache-prefix changes require capability and reason</td></tr>
                <tr><td><code>llm_execution</code></td><td>Wrap or short-circuit provider execution without changing the request</td></tr>
              </tbody>
            </table>
            <p>
              Execution middleware may call <code>next_call</code> once. Any
              transform belongs at the corresponding request join point.
            </p>

            <h2>Internal events and persistence</h2>
            <p>
              <code>RuntimeEvent</code> currently contains{" "}
              {architectureBaseline.hook_events.count} internal observability
              events. <code>HookEvent</code>/<code>HookSystem</code> remain
              compatibility type aliases; new code uses{" "}
              <code>RuntimeEvent</code>/<code>RuntimeEventBus</code>.
            </p>
            <table>
              <thead><tr><th>Store</th><th>Behavior</th></tr></thead>
              <tbody>
                <tr><td>SQLite activity store</td><td>Canonical operational record, including <code>extension.invoked</code> rows</td></tr>
                <tr><td>RunTimeline <code>events.jsonl</code></td><td>Mirrors the same typed row only while a run projection is active</td></tr>
              </tbody>
            </table>
            <p>
              Extension rows keep surface, name, extension, status, duration,
              and correlation IDs. Raw prompts, full requests or responses,
              personal data, and secrets are not persisted.
            </p>

            <h2>Tool boundary order</h2>
            <pre>{`tool_request → schema validation → PreToolUse → revalidation
→ hard deny / policy → PermissionRequest
→ tool_execution → TOOL_EXEC_STARTED → executor exactly once
→ TOOL_EXEC_ENDED or TOOL_EXEC_FAILED → PostToolUse`}</pre>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/guides/register-hook">Register public hooks and middleware</a></li>
              <li><a href="/geode/docs/architecture/agentic-loop">Agentic loop</a></li>
              <li><a href="/geode/docs/harness/lifecycle">Harness lifecycle</a></li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
