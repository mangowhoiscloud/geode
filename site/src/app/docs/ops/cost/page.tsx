import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Cost monitoring — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/cost"
      title="Cost monitoring"
      titleKo="비용 모니터링"
      summary="Session and monthly budgets. The usage ledger, geode history, and /cost."
      summaryKo="세션과 월간 예산입니다. 사용량 ledger, geode history, /cost를 다룹니다."
    >
      <Bi
        ko={
          <>
            <p>
              월간 사용량은 append-only ledger{" "}
              <code>~/.geode/usage/YYYY-MM.jsonl</code>
              (<code>core/llm/usage_store.py</code>)에 기록됩니다. 이는 모든
              호출을 빠짐없이 담은 청구서가 아닙니다. <code>/cost</code>는
              세션 tracker와 월간 기록을, <code>geode history</code>는 월간
              기록을 보여줍니다. 호출별 누락 여부는 durable 호출 이벤트와
              별도로 확인해야 합니다.
            </p>

            <h2>ledger 스키마</h2>
            <p>
              한 줄은 <code>UsageRecord</code>입니다. 모델, 입출력 토큰, 비용에
              더해 캐시와 thinking 분해가 들어갑니다.
            </p>
            <pre>{`# ~/.geode/usage/2026-06.jsonl 한 줄 (falsy 필드는 생략됨)
{"ts": 1780000000.0, "model": "claude-opus-4-8",
 "in": 1284, "out": 482, "cost": 0.0127,
 "session": "s-...", "cache_w": 0, "cache_r": 28104, "think": 1872}`}</pre>
            <p>
              일반 실행에서 사용량이 있는 응답은 AgenticLoop 경계의
              TokenTracker가 기록합니다. 실패한 시도와 보조 호출까지 모두
              포함한다는 뜻은 아닙니다. Petri 감사는 inspect_ai가
              프로바이더를 직접 호출해 GEODE의 tracker를 우회하므로, 감사 종료 후{" "}
              <code>core/audit/eval_to_jsonl.py</code>가 (model, role) 단위로{" "}
              <code>source: &quot;petri_eval&quot;</code> 행을 보태 judge와
              auditor 비용까지 ledger에 합류시킵니다. 단가는{" "}
              <code>core/llm/model_pricing.toml</code>이 SoT입니다.
            </p>

            <h2>짧은 대화도 같은 기록 경로</h2>
            <p>
              IPC fast-chat 우회 경로는 제거됐습니다. 기존{" "}
              <code>GEODE_FAST_CHAT</code> 설정은 더 이상 읽지 않으며, 짧은
              질문도 일반 AgenticLoop의 대화 이력·호출 관측·사용량 기록을
              거칩니다. 일반 컨텍스트·도구·검증을 사용하므로 이전의 축약
              경로보다 시간과 토큰이 늘 수 있습니다. 과거 누락 기록은
              소급 복구되지 않습니다.
            </p>
            <p>
              캐시 미수신과 명시적 0은 다릅니다. Durable 호출 이벤트는 이
              차이를 보존하지만 기존 JSONL과 월간·일별·history 집계는
              캐시 누락과 총계를 완전히 표현하지 못합니다. 제공자 보고 비용과
              모델 단가 추정, 구독 청구액도 서로 구분해야 합니다.
            </p>

            <h2>/cost: 세션 대시보드</h2>
            <pre>{`> /cost              # 세션 + 월간 요약
> /cost daily        # 오늘 분해
> /cost recent       # 최근 LLM 호출 10건
> /cost budget 30    # 월 예산 상한 (USD)`}</pre>
            <p>
              <code>/cost budget</code>은 프로젝트의{" "}
              <code>.geode/config.toml</code>에 저장되고, 이후 대시보드에 예산
              대비 사용률 바가 함께 표시됩니다
              (<code>core/cli/commands/cost.py</code>).
            </p>

            <h2>geode history: 월간 회계</h2>
            <pre>{`geode history                # 이번 달, 최근 10건
geode history -n 30          # 최근 30건
geode history -m 2026-05     # 지난달 집계`}</pre>
            <p>
              모델별 토큰과 비용 테이블, 최근 호출 목록을 출력합니다
              (<code>core/cli/typer_commands.py</code>).
            </p>

            <h2>예산이 실행을 멈추는 지점</h2>
            <p>
              <code>cost_limit_usd</code> 설정(기본 0 = 무제한)이 세션 비용
              가드를 켭니다. 세션 누적 비용이 80%에 닿으면 한 번 경고하고,
              예산에 도달하면 실행이 <code>cost_budget_exceeded</code>로
              끝납니다. 동작 방식은{" "}
              <a href="/geode/docs/ops/long-running">장기 실행 안전</a>의 가드
              표에 있습니다. 비용을 줄이는 가장 빠른 손잡이는 모델입니다.{" "}
              <code>/model</code>로 더 싼 모델로 전환하면 새 세션부터
              적용됩니다.
            </p>

            <h2>ledger 직접 집계</h2>
            <pre>{`# 이번 달 총비용
jq -s '[.[].cost] | add' ~/.geode/usage/$(date +%Y-%m).jsonl

# 모델별 비용
jq -s 'group_by(.model) | map({m: .[0].model, c: (map(.cost) | add)})' \\
  ~/.geode/usage/$(date +%Y-%m).jsonl

# Petri 감사 비용만
jq -c 'select(.source == "petri_eval")' ~/.geode/usage/$(date +%Y-%m).jsonl`}</pre>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>비용이 0으로만 보임</td>
                  <td>제공자 보고값, 단가 추정 또는 누락된 기록을 확인해야 함</td>
                  <td>0만으로 무료 실행이나 구독 청구액을 판단하지 않습니다. 모델 단가와 호출별 usage 존재 여부를 확인합니다.</td>
                </tr>
                <tr>
                  <td>감사 비용이 history에 안 보임</td>
                  <td>petri_eval 추출 전이거나 다른 달 파일</td>
                  <td><code>geode history -m</code>으로 해당 월을 보고, <code>source</code> 필드로 필터합니다.</td>
                </tr>
                <tr>
                  <td>예산 경고가 안 뜸</td>
                  <td><code>cost_limit_usd</code>가 0</td>
                  <td>0은 무제한입니다. 양수로 설정해야 80% 경고와 종료 가드가 켜집니다.</td>
                </tr>
              </tbody>
            </table>

            <h2>다음</h2>
            <ul>
              <li><a href="/geode/docs/ops/long-running">장기 실행 안전</a>. 비용 가드가 실행을 끊는 방식.</li>
              <li><a href="/geode/docs/runtime/llm/providers">LLM 라우팅</a>. 모델과 프로바이더 선택.</li>
              <li><a href="/geode/docs/verification/observability">관측성</a>. ledger 외의 렌즈들.</li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              Monthly usage is stored in the append-only ledger at{" "}
              <code>~/.geode/usage/YYYY-MM.jsonl</code>
              (<code>core/llm/usage_store.py</code>). It is not a complete invoice
              of every call. <code>/cost</code> combines the session tracker and
              monthly records; <code>geode history</code> reads monthly records.
              Check durable call events separately for observation gaps.
            </p>

            <h2>Ledger schema</h2>
            <p>
              A line is a <code>UsageRecord</code>: model, input and output
              tokens, cost, plus cache and thinking breakdowns.
            </p>
            <pre>{`# one line of ~/.geode/usage/2026-06.jsonl (falsy fields omitted)
{"ts": 1780000000.0, "model": "claude-opus-4-8",
 "in": 1284, "out": 482, "cost": 0.0127,
 "session": "s-...", "cache_w": 0, "cache_r": 28104, "think": 1872}`}</pre>
            <p>
              Normal responses with usage are recorded by TokenTracker at the
              AgenticLoop seam; this does not include every failed attempt or
              auxiliary call. Petri audits bypass
              GEODE&apos;s tracker (inspect_ai calls providers natively), so{" "}
              <code>core/audit/eval_to_jsonl.py</code> appends{" "}
              <code>source: &quot;petri_eval&quot;</code> rows per (model, role)
              after an audit, bringing judge and auditor cost into the same
              ledger. Prices come from <code>core/llm/model_pricing.toml</code>.
            </p>

            <h2>One recording path for short conversations</h2>
            <p>
              The IPC fast-chat bypass has been removed. The old{" "}
              <code>GEODE_FAST_CHAT</code> setting is no longer read. Short
              prompts use the normal AgenticLoop conversation, call observation
              and usage path. Normal context, tools and verification can consume
              more time and tokens than the removed compact route. Earlier
              missing records are not retroactively recovered.
            </p>
            <p>
              Missing cache usage is not explicit zero. Durable call events
              preserve that distinction; legacy JSONL and monthly/daily/history
              views do not fully represent cache absence and totals. Provider
              reported cost, model-price estimates and subscription invoices
              are different authorities.
            </p>

            <h2>/cost: the session dashboard</h2>
            <pre>{`> /cost              # session + monthly summary
> /cost daily        # today's breakdown
> /cost recent       # last 10 LLM calls
> /cost budget 30    # monthly ceiling (USD)`}</pre>
            <p>
              <code>/cost budget</code> persists to the project&apos;s{" "}
              <code>.geode/config.toml</code>, and the dashboard then renders a
              budget utilization bar (<code>core/cli/commands/cost.py</code>).
            </p>

            <h2>geode history: monthly accounting</h2>
            <pre>{`geode history                # this month, last 10 calls
geode history -n 30          # last 30 calls
geode history -m 2026-05     # last month's rollup`}</pre>
            <p>
              Prints a per-model token and cost table plus recent calls
              (<code>core/cli/typer_commands.py</code>).
            </p>

            <h2>Where a budget stops a run</h2>
            <p>
              The <code>cost_limit_usd</code> setting (default 0, meaning no
              limit) arms the session cost guard: one warning at 80% of budget,
              then termination with <code>cost_budget_exceeded</code> at the
              budget. The guard table lives in{" "}
              <a href="/geode/docs/ops/long-running">Long-running safety</a>.
              The fastest cost lever is the model itself; switch with{" "}
              <code>/model</code> and new sessions pick it up.
            </p>

            <h2>Querying the ledger directly</h2>
            <pre>{`# total this month
jq -s '[.[].cost] | add' ~/.geode/usage/$(date +%Y-%m).jsonl

# cost by model
jq -s 'group_by(.model) | map({m: .[0].model, c: (map(.cost) | add)})' \\
  ~/.geode/usage/$(date +%Y-%m).jsonl

# Petri audit cost only
jq -c 'select(.source == "petri_eval")' ~/.geode/usage/$(date +%Y-%m).jsonl`}</pre>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>Costs show as zero</td>
                  <td>Check provider reports, model-price estimates and missing records</td>
                  <td>Zero alone proves neither free execution nor a subscription invoice. Check model prices and the presence of per-call usage.</td>
                </tr>
                <tr>
                  <td>Audit cost missing from history</td>
                  <td>petri_eval rows not extracted yet, or a different month</td>
                  <td>Use <code>geode history -m</code> for the right month and filter by the <code>source</code> field.</td>
                </tr>
                <tr>
                  <td>No budget warning ever fires</td>
                  <td><code>cost_limit_usd</code> is 0</td>
                  <td>Zero means unlimited. Set a positive value to arm the 80% warning and the termination guard.</td>
                </tr>
              </tbody>
            </table>

            <h2>Next</h2>
            <ul>
              <li><a href="/geode/docs/ops/long-running">Long-running safety</a>. How the cost guard ends a run.</li>
              <li><a href="/geode/docs/runtime/llm/providers">LLM routing</a>. Model and provider selection.</li>
              <li><a href="/geode/docs/verification/observability">Observability</a>. The lenses beyond the ledger.</li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
