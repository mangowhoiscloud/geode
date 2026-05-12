import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "LangSmith — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/langsmith"
      title="LangSmith"
      titleKo="LangSmith"
      summary="Opt-in tracing for the five LLM call sites in core/llm/router.py. Zero runtime cost when disabled."
      summaryKo="core/llm/router.py의 다섯 개 LLM 호출 지점에 대한 opt-in 트레이싱. 비활성화 시 런타임 비용 0."
    >
      <Bi
        ko={
          <>
            <h2>활성화</h2>
            <pre>{`export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=ls_...      # 또는 LANGSMITH_API_KEY
export LANGCHAIN_PROJECT=geode       # 선택`}</pre>
            <p>
              <code>LANGCHAIN_TRACING_V2=true</code> 게이트와 API 키가 모두 필요합니다.
              한쪽만 있으면 트레이싱은 비활성화됩니다.
            </p>

            <h2>데코레이터</h2>
            <pre>{`# core/llm/router.py:151-181
def is_langsmith_enabled() -> bool:
    tracing = os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
    api_key = (
        os.environ.get("LANGCHAIN_API_KEY")
        or os.environ.get("LANGSMITH_API_KEY")
    )
    return tracing and api_key is not None

def maybe_traceable(*, run_type="llm", name=None):
    if is_langsmith_enabled():
        from langsmith import traceable
        return traceable(run_type=run_type, name=name)
    return lambda fn: fn`}</pre>
            <p>
              LangSmith가 비활성 상태일 때 데코레이터는 항등 함수로 축소됩니다.
              런타임 비용 0, import도 일어나지 않습니다.
            </p>

            <h2>래핑된 호출 지점</h2>
            <table>
              <thead><tr><th>함수</th><th>run_type</th></tr></thead>
              <tbody>
                <tr><td><code>call_llm</code></td><td>llm</td></tr>
                <tr><td><code>call_llm_parsed</code></td><td>llm</td></tr>
                <tr><td><code>call_llm_json</code></td><td>llm</td></tr>
                <tr><td><code>call_llm_with_tools</code></td><td>chain</td></tr>
                <tr><td><code>call_llm_streaming</code></td><td>llm</td></tr>
              </tbody>
            </table>

            <h2>트레이싱되는 것, 되지 않는 것</h2>
            <ul>
              <li><strong>트레이싱됨</strong>. 모델 입출력 메시지, 토큰 사용량, 지연, 오류.</li>
              <li><strong>트레이싱되지 않음</strong> (별도 채널). prompt 어셈블리 메타데이터. <code>PROMPT_ASSEMBLED</code> 훅 페이로드 (fragment 목록, skill 해시, 절단 이벤트)는 로컬에서 발생하지만 LangSmith run에 자동 첨부되지 않습니다. 브릿징은 로드맵에 있습니다 (<em>geode-prompt-evolution P2 #4</em>).</li>
            </ul>

            <h2>로그 노이즈 제어</h2>
            <pre>{`# core/llm/router.py:141-143
logging.getLogger("langsmith").setLevel(logging.ERROR)
logging.getLogger("langchain").setLevel(logging.ERROR)`}</pre>
            <p>
              LangSmith 내부의 429 재시도 로깅을{" "}
              <code>WARNING</code>에서 <code>ERROR</code>로 올려 GEODE stdout을
              깨끗하게 유지합니다.
            </p>
          </>
        }
        en={
          <>
            <h2>Activation</h2>
            <pre>{`export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=ls_...      # or LANGSMITH_API_KEY
export LANGCHAIN_PROJECT=geode       # optional`}</pre>
            <p>
              Both the <code>LANGCHAIN_TRACING_V2=true</code> gate and an API key
              are required. Either alone disables tracing.
            </p>

            <h2>The decorator</h2>
            <pre>{`# core/llm/router.py:151-181
def is_langsmith_enabled() -> bool:
    tracing = os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
    api_key = (
        os.environ.get("LANGCHAIN_API_KEY")
        or os.environ.get("LANGSMITH_API_KEY")
    )
    return tracing and api_key is not None

def maybe_traceable(*, run_type="llm", name=None):
    if is_langsmith_enabled():
        from langsmith import traceable
        return traceable(run_type=run_type, name=name)
    return lambda fn: fn`}</pre>
            <p>
              When LangSmith is inactive the decorator collapses to identity —
              zero runtime cost, no import.
            </p>

            <h2>Wrapped call sites</h2>
            <table>
              <thead><tr><th>Function</th><th>run_type</th></tr></thead>
              <tbody>
                <tr><td><code>call_llm</code></td><td>llm</td></tr>
                <tr><td><code>call_llm_parsed</code></td><td>llm</td></tr>
                <tr><td><code>call_llm_json</code></td><td>llm</td></tr>
                <tr><td><code>call_llm_with_tools</code></td><td>chain</td></tr>
                <tr><td><code>call_llm_streaming</code></td><td>llm</td></tr>
              </tbody>
            </table>

            <h2>What gets traced, what does not</h2>
            <ul>
              <li><strong>Traced</strong>: model input/output messages, token usage, latency, errors.</li>
              <li><strong>Not traced</strong> (separate channel): prompt assembly metadata. The <code>PROMPT_ASSEMBLED</code> hook payload (fragment list, skill hashes, truncation events) is fired locally but does not auto-attach to the LangSmith run. Bridging is on the roadmap (<em>geode-prompt-evolution P2 #4</em>).</li>
            </ul>

            <h2>Log noise control</h2>
            <pre>{`# core/llm/router.py:141-143
logging.getLogger("langsmith").setLevel(logging.ERROR)
logging.getLogger("langchain").setLevel(logging.ERROR)`}</pre>
            <p>
              LangSmith&apos;s internal 429 retry logging is escalated from{" "}
              <code>WARNING</code> to <code>ERROR</code> to keep the GEODE stdout
              clean.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
