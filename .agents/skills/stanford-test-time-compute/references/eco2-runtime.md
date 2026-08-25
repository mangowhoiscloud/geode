# Eco² — LG AI 1차 면접 PT 사실 카드 (검증 완료)

> 수집일: 2026-07-28. 검증 등급: `[실측]` 파일/커밋에서 직접 확인, `[문서주장]` 레포 문서상 주장(코드 미확인), `[미검증]` 근거 없음.
> 로컬 SoT: `${HOME}/workspace/SeSACTHON/backend` (main, HEAD
> 4c3eebb3). [Eco² 포트폴리오](https://mangowhoiscloud.github.io/portfolio/eco2/)

검증 표기: `[직접근거]`는 코드·Git·artifact 실측, `[외부연구]`는 공식
외부 문서, `[해석]`은 두 근거를 발표 직무 맥락에 정렬한 판단이다.

---

## ① 한 줄 개요

폐기물 분리배출 도우미 **production-level AI Agent 서비스** — LangGraph Multi-Agent 챗봇(10 intent) + Vision LLM 폐기물 분류 파이프라인을 Self-managed Kubernetes(Istio/ArgoCD/KEDA) 위에서 운영. **2025 서울시 새싹(SeSAC) 해커톤 우수상** `[실측: frontend/README.md:17-19 "2025 새싹 해커톤 … 🏆 우수상 수상 🏆" + 수상 사진]`. 수상 배경 "본선 32팀 중 Top 4, 총 181팀 지원" `[문서주장: 포트폴리오 페이지]`.

---

## ② 문제 → 접근 → 아키텍처 (에이전트 워크플로우 중심)

### 이력서 주장 1 — Intent 분류 + Send API 병렬 fan-out: **전부 [실측]**

- **10개 intent enum**: `WASTE, CHARACTER, LOCATION, BULK_WASTE, RECYCLABLE_PRICE, COLLECTION_POINT, WEATHER, IMAGE_GENERATION, WEB_SEARCH, GENERAL` `[실측: backend/apps/chat_worker/domain/enums/intent.py + routing/dynamic_router.py:162-173 INTENT_TO_NODE 정확히 10개]`
- **Intent 분류 앞단**: LLM Structured Output(`generate_structured`) 기반 분류 + Chain-of-Intent(`previous_intents`) + multi-intent 감지/분해 `[실측: application/commands/classify_intent_command.py:49,225,307,330]`
- **LangGraph Send API fan-out**: `dynamic_router`가 `list[Send]` 반환 — ① 주 intent 노드 ② `additional_intents` 병렬 Send(multi-intent fanout) ③ 규칙 기반 enrichment ④ 조건부 enrichment `[실측: routing/dynamic_router.py:203-317, from langgraph.types import Send :31]`
- **general fallback**: `INTENT_TO_NODE.get(primary_intent, "general")` — 미매핑 intent는 general로 폴백 `[실측: dynamic_router.py:226]`. 추가로 general+확신도<0.75면 web_search 자동 보강 `[실측: dynamic_router.py:141-158]`
- **weather enrichment 자동 합류**: `waste`/`bulk_waste` intent → `weather` 노드 자동 추가 `[실측: dynamic_router.py:78-90 ENRICHMENT_RULES]`, `user_location` 존재 시 조건부 weather 추가 `[실측: :131-140]`. 병렬 결과는 `aggregator` 노드에서 합류 `[실측: nodes/aggregator_node.py 존재; README.md:225-238 그래프 edge]`. Fail-Open 정책(보조 컨텍스트 누락 시 진행)은 `[문서주장: README.md:336]`
- **후단**: aggregator → 토큰 임계값(4K) 초과 시 summarize(OpenCode 스타일 압축) → answer(토큰 스트리밍) `[실측: 그래프 구조 README.md:189-242 (draw_mermaid 산출) + summarization.py 존재; 4K 수치는 문서주장 README.md:337]`
- **주의**: "질문이 10개 intent로 갈라진다는 **관찰**"(데이터 분석으로 10개를 도출했다는 서사)의 근거 데이터/문서는 레포에서 발견 못함 → 관찰 과정 자체는 `[미검증]`. 10개 분류 체계의 존재는 [실측].

### Tool Calling / 서브에이전트 구성

- Tool Calling 자산 6종: weather(기상청), bulk_waste(자치구), recyclable_price(시세), location·collection_point(Kakao Local), web_search(OpenAI web_search / Gemini Google Search native). 단, 현재 factory는 `*_agent_node.py`의 반복형 multi-tool loop가 아니라 대부분 `generate_function_call()` 1회로 인자를 추출한 뒤 application command를 실행하는 node를 연결한다. 따라서 현재 runtime을 "6개 ReAct subagent"라고 부르면 과장이다. `[실측: factory.py imports/wiring + nodes/*_node.py와 *_agent_node.py 대조]`
- OpenAI adapter의 Structured Output·web search 경로는 Agents SDK(primary) + Responses API(fallback)를 실제 사용한다. 일반 answer/stream 경로는 Chat Completions다. SDK 사용 범위와 전체 graph의 agent 성격을 구분해야 한다. `[실측: infrastructure/llm/clients/openai_client.py]`
- 이미지 생성: `dynamic_router`의 동급 branch로
  `image_generation_node → GenerateImageCommand →
  GeminiNativeImageGenerator → ImageStoragePort(gRPC) → Images API →
  CDN URL → aggregator`가 배선된다. 현재 generator는
  `gemini-3-pro-image-preview`로 고정되고, node policy는 timeout 30초,
  retry 1회, `FAIL_OPEN`이다. `[직접근거:
  factory.py:474-521,600-650; image_generation_node.py;
  generate_image_command.py; setup/dependencies.py:442-518;
  policies/node_policy.py:146-152]`
- Tool calling·Agents SDK 계보: `ecd59c7d`의 반복형 function-calling
  agent 자산 뒤 `174959d9`가 production API node를 one-shot argument
  extraction + deterministic command로 제한했다. `64a4e65b`·`b7316337`은
  Agents SDK primary를 추가했지만, 현재 factory는 반복형
  `*_agent_node.py`가 아니라 `*_node.py`를 연결한다. Agents SDK는
  structured output과 native web search에서 실제 사용된다.
  `[직접근거: Git + factory.py imports + openai_client.py]`
- LangGraph 노드 총 23개 = main 17 + eval subgraph 6 `[문서주장: backend/portfolio/eco2/architecture-facts.md:13,28-31 — "코드에서 직접 추출" 명시된 자체 실측 문서]`

### 시스템 아키텍처 (5-Layer)

- Edge(ALB+Istio Ingress) / Service(8 도메인 API) / Integration(Event Bus + Worker) / Persistence(PostgreSQL, Redis 용도별 분리) / Platform(ArgoCD, KEDA, Prometheus/Grafana, Jaeger, LangSmith, EFK) `[문서주장: README.md:26-49; apps/ 디렉토리 18개 서비스·워커는 실측]`
- Scan 파이프라인: Celery Chain 4단계 Vision(GPT Vision)→Rule(Lite RAG)→Answer→Reward, RabbitMQ + KEDA 오토스케일링 `[실측: apps/scan_worker 존재 + README.md:133-140]`
- Checkpoint: Redis Primary(~1ms) + PostgreSQL Async Sync(5s batch) — Worker PG 연결 192→8 (96% 감소) `[문서주장: README.md:353-399; checkpointer.py, sync/ 디렉토리는 실측]`

---

## ③ 내 역할 / 참여도 / 타임라인 (이력서 주장 4)

### git 실측 수치

- **Backend(인프라 포함 모노레포)**: 발표 검증 핀 `4c3eebb3afc3`의 HEAD는 2,277커밋. 본인 동일 이메일의 두 저자명(mangowhoiscloud 1,526 + mango 654 = **2,180**) / 다른 팀원 9 / 자동화 계정 88이다. `[실측: git rev-list --count HEAD; git shortlog -sne HEAD]` 모든 ref 기준 2,429와 섞지 않는다. 커밋 수는 활동 범위의 보조 증거이며 코드 품질·성과의 대리 지표가 아니다. terraform/, ansible/, clusters/, workloads/(K8s manifests) 모두 이 레포에 포함 → 인프라 전담 근거.
- **Backend 월별(본인)**: 2025-10: 64 / 11: 904 / 12: 721 / 2026-01: 477 / 02: 11 / 03: 3 `[실측: git log --author]`
- **Frontend**: 팀 공동 — 본인 208(133+75), suji8073 99, ChaeHyun-Kim 계열 119+, Suji Chae 33 `[실측: git shortlog @ frontend]`
- **Frontend 월별(본인)**: 2025-12: 7 → **2026-01: 157** — 타 FE 팀원 커밋은 2025-12에서 종료, **1월부터 FE 단독 인수** `[실측: git log 월별 분포; frontend 마지막 커밋 2026-01-25]`

### 타임라인

- 레포 시작: frontend 2025-10-27, backend 첫 본인 커밋 2025-10-30 `[실측: git log --reverse]`
- 포트폴리오 주장 기간: 2025-10-31 ~ 2026-01-28 (91일) `[문서주장: 포트폴리오 페이지]` — git 실측으론 backend 활동이 2026-03-08까지 이어짐(eval 파이프라인 등 후속 작업 2월).
- **정직한 서사**: ① 해커톤 기간(10월 말~11월, MVP): 5인 팀(BE/Infra 1 = 본인, AI 1, FE 2, 디자인 1 `[문서주장: 포트폴리오 페이지]`)에서 백엔드·인프라 전담 ② 수상 후(12월~3월): BE·Infra 계속 전담 + 12월 FE 참여 시작, **1월부터 FE·BE·Infra·Agent(LLM) 단독** 확장. → 이력서의 "1개월 MVP + 3개월 단독 확장"은 git 분포와 **대체로 정합**. 단 "단독 확장" 중 12월은 FE 팀원 잔여 커밋(suji 32, chaehyun 26)이 있으므로 "12월부터 완전 단독"이라고 말하면 과장됨.

### 팀 구성

- 5인: Backend/Infra 1(본인), AI Researcher 1, Frontend 2, UI/UX 1 `[문서주장: 포트폴리오 페이지]`. AI Researcher(taemin-steve 추정) backend 기여 8커밋(2025-11) `[실측]`.

---

## ④ 핵심 수치 (근거 병기)

### 이력서 주장 3 — SSE 재설계 + k6: **핵심 수치 [실측], 전사(前史) [문서주장]**

| 항목 | 값 | 근거 |
|---|---|---|
| 구조 개편 전 병목 | **50 VU**에서 SSE 성능 붕괴: SSE 1개당 RabbitMQ 연결 21개(Celery Events blocking 수신), RabbitMQ 연결 341개, scan-api 메모리 676Mi > 512Mi limit → readiness 실패 → 503 | `[문서주장: docs/blogs/redis-streams-sse/00-architecture-migration.md (2025-12-26)]` |
| 재설계 | Redis Streams(내구) + Pub/Sub(실시간) + State KV(복구) 3-tier Event Bus, Event Router(XREADGROUP/XCLAIM) + SSE Gateway 분리, 연결 곱폭발 O(client×conn) → 상수화 | `[실측: apps/event_router/, apps/sse_gateway/ 존재]` + `[문서주장: 위 블로그 + README.md:141-149]` |
| k6 스윕 | VU 500/600/700/800/900/1000 단계별 JSON 결과 파일 12개가 레포 루트에 실존 (2026-01-27) | `[실측: backend/k6-scan-polling-vu{500..1000}-*.json]` |
| **VU 1000 최종** | submitted 1,518 / completed 1,469 / failed 33 → **success_rate "97.8%"**, throughput 373.4 req/m, **e2e_p95 173.3s**, e2e_avg 121.3s | `[실측: k6-scan-polling-vu1000-2026-01-27T20-06-38-794Z.json]` |
| VU 900 (권장 한계) | 1,540 submitted, **99.7%**, 405.5 req/m, e2e_p95 149.6s | `[실측: k6-scan-polling-vu900-…json]` |
| 300s 타임아웃 | `POLL_TIMEOUT = 300000` (5분) 내 완료를 성공으로 판정 | `[실측: e2e-tests/performance/k6-scan-polling-test.js:51]` |
| 스윕의 실체 | 같은 날 보존된 VU1000 6회는 파일 timestamp 순 **92.5% → 96.6% → 0.0% → 0.0% → 0.0% → 97.8%**다. 선형 개선이 아니라 중간 회귀 뒤 복구한 기록이다. | `[실측: vu1000 JSON 6개 비교]` |
| 튜닝 내용 | Pub/Sub 채널 job_id 해시 4-shard 샤딩(Hot Key 분산), KEDA minReplicas 1→2/max 3→5(Cold Start), 병목=Celery Probe I/O-bound, OpenAI Tier 4 TPM 61% | `[문서주장: README.md:738-742,796-799]` |

**측정 방법론 주의(면접 대비)**: VU1000 "완료율 97.8%"는 **k6 폴링 방식**(평균 46.4 polls/task, 총 70,432 poll 요청 `[실측: 동일 JSON polling 섹션]`)으로 E2E 완료를 측정한 것. SSE 스트리밍 자체의 부하 스크립트는 별도 존재(`e2e-tests/performance/k6-sse-e2e.js, k6-sse-test.js, locustfile_sse.py` `[실측]`). "동기 SSE 포화 → 이벤트 기반 재설계"는 아키텍처 사실이고, 97.8%는 그 파이프라인의 E2E 처리 완료율.

### 이벤트 버스 발전 계보 — 블로그·포트폴리오·Git 대조

기준 revision은 Eco² backend `4c3eebb3afc3`이다. 블로그는 당시의 문제
인식과 선택 근거, 포트폴리오는 특정 시점의 요약, Git과 현재 코드는
실제 착지 상태로 구분해 읽는다.

| 시점 | 관찰한 압력 | 구조 변화 | 증거와 해석 |
|---|---|---|---|
| 2025-12-26 | 50 VU에서 활성 SSE 16개가 RabbitMQ 연결 341개를 만들고 scan-api 메모리가 676Mi로 512Mi limit을 초과 | SSE마다 Celery Events receiver를 여는 구조의 연결 증폭을 병목으로 판정 | `docs/blogs/async/23-*`, `redis-streams-sse/00-*`; 1:21은 당시 관측치 |
| 2025-12-26 | 작업 실행과 진행 이벤트가 같은 RabbitMQ 연결 수명에 결합 | RabbitMQ는 Celery task queue로 남기고, worker 진행 이벤트를 Redis Streams로 이동 | “RabbitMQ 제거”가 아니라 task plane과 event plane 분리 |
| 2025-12-27~28 | API가 client connection과 event consumption을 함께 소유하면 수평 확장·복구가 어려움 | SSE Gateway 분리, Event Router의 `XREADGROUP → State KV → Pub/Sub → XACK`, Streams catch-up, KEDA·metrics 추가 | `eb407926`, `1fd68f34`, `087f25c4`; Event Bus v1.0.7 |
| 2026-01-20 | 포트폴리오가 Event Relay 3-tier와 VU 50→300, 포화점 VU 80→500을 기록 | Redis Streams + Pub/Sub + State KV 구조가 중간 성과로 정리됨 | `${HOME}/Downloads/portfolio_류지환.pdf`; 최종 shard·VU1000 이전 snapshot |
| 2026-01-21~25 | duplicate, publish 실패 뒤 ACK, reconnect gap, stale Pub/Sub, replica 간 Pub/Sub 비복제, hot channel이 드러남 | `stream_id` dedupe, 실패 시 ACK 보류와 `XAUTOCLAIM`, `Last-Event-ID`, master-only Pub/Sub service, job hash 4-shard 도입 | `35268e39`, `a2ef9ae3`, `90604d39`, `97c0a00f`, `9c3297ec` |
| 2026-01-27~28 | 연결 병목을 제거한 뒤 worker·queue·외부 API가 새 처리 한계가 됨 | queue·pending·connection 신호별 KEDA 조정과 단계별 k6 sweep | VU1000 최종 97.8%는 300초 polling E2E completion이며 SSE throughput이 아님 |

이 계보의 핵심은 브로커 교체가 아니다. **작업 실행, 재생 가능한 이벤트,
실시간 전달, 복구 상태, client connection의 수명과 확장 신호를
분리한 것**이다.

### 현재 클러스터의 이벤트 버스 구조

| 평면 | 실제 흐름 | 상태·복구 계약 | 확장 신호 |
|---|---|---|---|
| Task | API → RabbitMQ queue → scan/chat worker | RabbitMQ는 작업 오케스트레이션만 소유 | scan worker는 `scan.vision/answer/rule` queue length, 현재 manifest 2–4 pods |
| Event log | Worker → `scan:events:{0..3}` / `chat:events:{0..3}` | Redis Streams consumer group과 event sequence | Streams Redis exporter |
| Distribution | Event Router `XREADGROUP` → non-token은 Lua state/idempotency, token은 publish-only → `sse:events:{0..3}` → 성공 시 `XACK` | publish 실패 시 ACK하지 않고 5분 idle 뒤 `XAUTOCLAIM`; state TTL 1h, marker TTL 2h | pending ≥100, Event Router 1–2 pods |
| Realtime | master-only Redis Pub/Sub → SSE Gateway process-local subscriber queue → client | 초기·재접속 시 State KV와 Streams catch-up, `Last-Event-ID` dedupe | active SSE 100/pod, Gateway 1–3 pods |
| Control | ArgoCD sync wave 27 Redis Operator → 28 Redis CR → 29–32 RabbitMQ → 35 KEDA → 42 Gateway → 43 Router | `prune/selfHeal`; KEDA가 소유하는 `/spec/replicas`는 ArgoCD diff에서 제외 | desired state와 autoscaling authority 분리 |
| Observe | Prometheus ServiceMonitor → Grafana Event Bus dashboard, OTEL → Jaeger | connection, lag, batch, publish error, reclaim, queue drop, TTFB 관측 | 관측만 수행하며 실행 권한 없음 |

발표 정확성 경계:

- “3-tier Event Bus”는 **논리적 역할 분리**다. State KV는 별도 세 번째
  Redis가 아니라 Streams Redis에 함께 있다.
- Streams Redis는 Pub/Sub보다 재생·consumer recovery가 가능하지만
  현재 manifest가 `emptyDir`, AOF/RDB off이므로 장기 durable storage로
  부르지 않는다.
- README의 scan-worker 2–5 pods보다 현재 ScaledObject의 2–4 pods를
  우선한다.
- 일부 config docstring은 `sse:events:{job_id}`로 남았지만 실제
  `EventProcessor`와 Gateway는 MD5 job hash 기반 4개 shard channel을
  사용한다.

### Observability를 에이전트의 feedback surface로 만든 외부 루프

2026-01-20 포트폴리오는 GitOps와 동기화된 코드베이스를 사람과
에이전트가 공유하는 SoT로 두고, 터미널·CLI·Observability로 실제
클러스터 상태를 읽으며 Foundations·Plans·Reports를 프로젝트 기억으로
사용했다고 기록한다. 이는 당시 작업 방식의 snapshot이다.

현재 revision의 매니페스트와 애플리케이션 코드는 이 서술이 기대는
관측면을 다음처럼 구체화한다.

| 관측면 | 현재 코드에 배선된 구성 | 외부 루프에 제공한 신호 | 정확성 경계 |
|---|---|---|---|
| Metrics | `kube-prometheus-stack` Prometheus 15일 보존, Grafana, API·RabbitMQ·Redis·Event Router·SSE Gateway exporter와 ServiceMonitor | request/error/latency, RabbitMQ connection·queue, Streams pending·lag, Router process/publish/reclaim, SSE CCU·TTFB·write·queue drop, pod/node resource | Router·Gateway ServiceMonitor scrape 주기는 15초다. dashboard query와 exporter 이름을 맞춘 수정 이력이 있다. |
| Logs | Fluent Bit DaemonSet → Elasticsearch 8.11 → Kibana | pod·namespace·container가 붙은 구조화 로그, 재시작 전 로그와 event sequence 대조 | 현재 Elasticsearch CR은 **1 node**, 50Gi PVC다. 기존 “3-node EFK” 표현은 사용하지 않는다. |
| Traces | 애플리케이션 OTEL + Istio → Jaeger, Kiali에서 service graph와 Prometheus·Grafana·trace 연결 | API→MQ→Worker→Event Router→Gateway 구간과 외부 호출의 시간 분해 | 현재 Jaeger는 all-in-one, memory storage, 최대 15,000 traces다. 장기 trace archive로 부르지 않는다. Router·Gateway 기본 sampling은 0.1이다. |
| Agent trace | chat-worker의 LangSmith tracing과 node·token·cost metadata, optional OTEL export | intent·node·LLM 호출 단위 실행 분석 | Chat Agent에 한정된 application trace다. 클러스터 전체의 운영 메트릭을 대체하지 않는다. |
| Alert | Pod·node·resource·Redis·ArgoCD·API latency/error PrometheusRule, Slack용 AlertmanagerConfig와 ExternalSecret | 사람이 루프를 시작해야 하는 threshold signal | 코드에는 `configExistingSecret: alertmanager-config`와 `AlertmanagerConfig/slack-alerts`가 함께 있으나 해당 Secret은 저장소에서 확인되지 않는다. Slack 전달이 실제 운영됐다고 단정하지 않는다. |

포트폴리오의 스택 나열보다 발표에서 중요한 것은 **신호가 변경으로
이어진 절차**다.

```text
k6 workload / alert
        ↓
metric + log + trace + cluster event
        ↓
coding agent가 code·manifest·project skill·의사결정 문서를 함께 대조
        ↓
병목 가설과 가장 작은 source / manifest diff
        ↓
lint·test·CI → Git desired state → ArgoCD reconcile
        ↓
같은 workload와 같은 signal family로 재측정
        ↓
사람이 keep / revise / revert
```

에이전트가 읽을 수 있었던 인터페이스도 코드베이스에 남아 있다.
`.claude/skills/k8s-debugging/SKILL.md`는 원격 클러스터의 node·pod·container
state, current/previous logs, Kubernetes events, CI job, ArgoCD refresh,
rollout, image digest를 확인하는 절차를 `Claude Code용`으로 명시한다.
`docs/blogs/tooling/01-cursor-to-claude-code-migration.md`는 51개 이상의
로컬 문서와 83개 이상의 블로그를 trigger 기반 skill과 `CLAUDE.md`로
재구성해 새 세션에도 architecture history를 공급한 과정을 기록한다.

#### 외부 루프가 병목을 이동시킨 두 사례

| 압력과 관측 | 가설 | 변경 | 재측정에서 알게 된 것 |
|---|---|---|---|
| 50 VU에서 SSE 16, RabbitMQ connection 341, scan-api 676Mi > 512Mi, readiness 503 | client connection마다 Celery Events receiver를 열어 task transport와 progress delivery 수명이 결합됨 | RabbitMQ는 task queue로 유지하고 progress는 Streams→Router→Pub/Sub→Gateway로 분리 | 연결 곱폭발을 제거한 뒤 queue·worker·외부 API가 다음 병목 후보로 이동 |
| 단계별 VU sweep에서 queue wait·worker state·probe restart와 OpenAI usage를 함께 대조 | CPU·memory나 OpenAI rate limit보다 I/O-bound Celery worker의 inspect-based probe가 in-flight task를 잃게 함 | KEDA min replica 조정과 probe 병목 진단, Pub/Sub 4-shard 등 부하 표면별 수정 | VU1000 polling E2E completion 97.8%; 100%가 아닌 이유를 33개 probe-timeout failure로 분리 |

첫 사례의 수치는 당시 Prometheus 분석 문서
`docs/blogs/async/23-sse-bottleneck-analysis-50vu.md`에 남아 있다. 둘째
사례의 최종 수치는 k6 JSON에서 직접 확인되지만, probe 원인과 OpenAI
TPM 61% 해석은 `docs/blogs/tests/2026-01-27-scan-load-test-vu1000-final.md`
및 README의 문서 주장이다.

Git 계보도 이 루프의 순서를 뒷받침한다.

- 2025-12-24~25: RabbitMQ·SSE metric을 세분화하고 병목 분석용 dashboard와
  HPA를 먼저 추가했다.
- 2025-12-26~27: Redis Streams, SSE Gateway, Event Router를 도입했다.
- 2025-12-27~28: Router/Gateway 자체 metric과 ServiceMonitor를 추가하고,
  dashboard query와 KEDA trigger를 **실제 exporter 이름에 맞게**
  수정했다.
- 2026-01-21~25: 중복·ACK·reconnect·Pub/Sub master·channel hot spot을
  관측한 뒤 recovery와 4-shard 구조를 보강했다.
- 2026-01-27: VU500–1000 sweep으로 새 포화 지점을 다시 찾았다.

따라서 정확한 발표 문장은 다음과 같다.

> 모니터링을 대시보드 설치로 끝내지 않았습니다. metric·log·trace와
> 클러스터 event를 코딩 에이전트가 읽을 수 있는 feedback surface로,
> Git desired state를 검증 가능한 action surface로 만들었습니다.
> 부하를 재현하고 가장 작은 변경을 반영한 뒤 같은 신호로 다시
> 측정했으며, 최종 채택 권한은 사람에게 남겼습니다.

이것은 production runtime이 스스로 source를 고치는 자율 self-improvement가
아니다. **사람과 coding agent가 함께 수행한 외부 engineering loop**다.
Eco²에서 관측값과 변경 이력은 문서·commit·k6 result로 흩어져 있었고,
GEODE에서는 이 한계를 trajectory, revision-bound eval artifact,
keep/revert gate로 구조화한다.

### 시스템의 발전을 제한하고 보호한 guardrail

Eco²의 guardrail은 하나의 승인 버튼이 아니다. 변경, 배포, 실행,
메시지 정합성, 부하, 관측의 각 층에서 **누가 무엇을 소유하는지**를
나눈 계약이다.

| 층 | 막으려 한 실패 | 실제 guardrail | 발전 과정과 한계 |
|---|---|---|---|
| Change boundary | 에이전트나 운영자가 live cluster만 고쳐 Git과 실제 상태가 갈라짐 | Git branch를 desired state로 두고 ArgoCD `prune/selfHeal`로 reconcile | drift는 복구하지만 manifest 자체의 오류까지 올바르게 만들지는 않는다. dev/prod가 immutable SHA가 아니라 branch를 추적한다는 한계가 있다. |
| Build boundary | 생성 코드의 문법·형식·단위 회귀, 잘못 렌더링된 manifest | 경로별 CI에서 Black·Ruff·Pytest, infra CI에서 Helm render·chart test·Kustomize build·Kubeconform·render parity | Radon은 설정과 수동 분석 자산이지 현재 blocking CI gate로 확인되지는 않는다. 테스트 통과를 production correctness와 동일시하지 않는다. |
| Rollout boundary | 검증되지 않은 revision이 stable traffic 전체에 즉시 노출 | stable/canary deployment와 `X-Canary: true` header routing, 별도 canary image tag | 여러 API·worker에 배선됐지만 label·tag 표기가 완전히 균일하지 않다. “전 서비스 자동 promotion”으로 과장하지 않는다. |
| Runtime boundary | runaway resource, 비정상 process가 계속 traffic을 받음, 불필요한 권한 | request/limit, readiness/liveness, non-root·read-only filesystem, NetworkPolicy | probe는 보호 장치지만 I/O-bound Celery worker에서는 오탐 재시작과 in-flight loss를 만들었다. guardrail 자체도 관측·수정 대상이 됐다. |
| Scaling boundary | CPU만 보고 늦게 확장하거나 metric 장애 때 0으로 수렴, scale flap | queue/pending/connection 기반 KEDA, min/max replica, metric failure 3회 뒤 fallback 2 replicas, 300초 scale-down stabilization | replica 필드는 KEDA가 소유하고 ArgoCD가 무시한다. desired-state controller와 autoscaler의 권한 충돌을 계약으로 제거했다. |
| Message integrity | 중복, out-of-order, publish 실패 뒤 ACK로 영구 유실, 재연결 gap | Lua state+published marker, publish 성공 시에만 `XACK`, 5분 idle `XAUTOCLAIM`, `stream_id` dedupe, Last-Event-ID catch-up | at-least-once delivery의 중복을 idempotency로 흡수한다. Streams 저장소가 `emptyDir`라 장기 durability를 보장하지는 않는다. |
| Detection boundary | 장애가 사용자 503으로 드러날 때까지 원인을 모름 | exporter·ServiceMonitor·Grafana, PrometheusRule, logs, traces, cluster events | threshold와 dashboard는 진단을 시작하게 할 뿐 변경을 승인하지 않는다. Slack alert delivery는 현재 코드만으로 검증되지 않는다. |
| Release boundary | coding agent가 자신이 만든 가설과 변경을 스스로 승인 | scoped diff → lint/test/CI → Git/ArgoCD → 동일 workload 재측정 → human keep/revise/revert | Eco²에는 GEODE Crucible 같은 formal promotion verdict가 없다. 최종 판정은 사람과 Git history에 남았다. |

가드레일은 장애를 겪으며 다음 순서로 두꺼워졌다.

```text
desired state / reconcile
    → runtime health와 resource boundary
    → task plane과 event plane 분리
    → idempotency·ACK·reclaim·replay
    → workload-specific scaling threshold와 fallback
    → observability를 읽는 agent-assisted outer loop
```

이 발전사의 핵심은 “안전 장치를 많이 붙였다”가 아니다.

1. **권한 충돌을 줄였다.** Git/ArgoCD는 선언 상태, KEDA는 replica,
   Event Router는 ACK, 사람은 release를 소유한다.
2. **실패를 국소화했다.** task 실행, event delivery, recovery,
   client connection을 분리해 한 영역의 포화가 전체 수명으로
   증폭되지 않게 했다.
3. **guardrail의 실패도 관측했다.** VU1000에서 CPU·memory보다 probe
   오탐이 실패를 만든 사실은 보호 장치도 workload에 맞춰 검증해야
   한다는 근거가 됐다.
4. **결정론으로 막을 수 있는 것은 모델에게 맡기지 않았다.** format,
   unit test, manifest schema, resource ceiling, idempotency, ACK 조건은
   코드와 controller가 판정했다.

발표에서는 다음 한 문장으로 압축한다.

> 시스템은 에이전트가 자유롭게 고쳐서 발전한 것이 아닙니다. Git,
> CI, controller, runtime invariant, message contract가 변경 범위를
> 제한했고, Observability가 그 가드레일의 부작용까지 다시 드러냈습니다.
> 에이전트는 그 경계 안에서 가설과 작은 변경을 만들고, 사람은 같은
> workload의 재측정 결과로 채택을 결정했습니다.

### 기타 규모 수치

- 마이크로서비스 19(9 API + 9 Worker + ext-authz), EC2 20노드(vCPU 28/RAM 90GB), RabbitMQ 큐 12/익스체인지 7, NetworkPolicy 21, KEDA ScaledObject 4, ArgoCD sync-wave 16단계(00~63), CI/CD 워크플로 9 `[문서주장: portfolio/eco2/architecture-facts.md — "codebase verified" 자체 명시, apps/ 18개 디렉토리는 실측]`
- Chat Worker 43,832+ LOC `[문서주장: architecture-facts.md:12]`
- ext-authz 성능: VU 2500, RPS 1200, p99 200-300ms (Grafana snapshot 링크) `[문서주장: README.md:876]`; RPS 42→1,200 (28×), 캐시 히트 >99% `[문서주장: 포트폴리오 페이지]`
- README 표기 "24-Nodes"와 architecture-facts "20 EC2" 불일치 존재 — 발표 시 하나로 통일 필요(EC2 20대가 실측 문서 쪽) `[실측: 두 문서 대조]`

---

## ⑤ Agent Workflow 운영 증거 + Data Governance 관점

### 이력서 주장 2 — 평가 파이프라인(Swiss Cheese 3-Tier): **구현 [실측], 운영 상태에 중요한 단서 있음**

- **L1 Code Grader (결정론, 무비용)**: 6개 직교 슬라이스 — format_compliance / length_check / language_consistency(한국어 비율≥0.80) / hallucination_keywords / citation_presence / intent_answer_alignment, 가중치 합 1.0, 목표 지연 <50ms, 외부 의존성 없음 `[실측: apps/chat_worker/application/services/eval/code_grader.py:1-49]`
  - hallucination blocklist 12항목("100% 안전", "제 생각에는" 등), citation 패턴(환경부/출처:/※ 등) `[실측: code_grader.py:52-90]`
- **L2 LLM Judge (BARS 루브릭)**: 5축 BARS — faithfulness 0.30 / relevance 0.25 / completeness 0.20 / safety 0.15 / communication 0.10 `[실측: domain/services/eval_scoring.py:27-34]`
  - **위험물 intent 시 safety 0.15→0.25 동적 부스트** `[실측: eval_scoring.py:36-42 HAZARDOUS_WEIGHTS]`
  - positional bias 완화를 위한 축 순서 셔플, Structured Output retry-with-repair 최대 2회 `[실측: infrastructure/llm/evaluators/bars_evaluator.py:100-102, :37]`
  - BARS 2·4의 경계 축은 3회 추가 평가 뒤 중앙값 채택 `[실측: application/services/eval/llm_grader.py:28-29, 144-188]`
  - 평가 모델 기본값 `gpt-4o-mini`, LLM 점수 부재 시 code-only degraded mode `[실측: application/dto/eval_config.py:43, score_aggregator.py:_aggregate_code_only]`
  - 등급: S[90,100] / A[75,90) / B[55,75) / C[0,55) `[실측: domain/enums/eval_grade.py:15-31]`; C등급 재생성은 `eval_regeneration_enabled` 플래그(기본 False) `[실측: eval_config.py:42]`
- **L3 Calibration Monitor (judge 자체 점검)**: CUSUM 양방향 누적합, slack k=0.5, CRITICAL h=4.0(~3σ), WARNING 2.4(~2σ), 기대평균 3.0, 최근 N=50 표본, 축별 독립 감시 `[실측: application/services/eval/calibration_monitor.py:34-74]`
  - **Calibration set**: JSON 수동 큐레이션(`calibration_set.json` v1.0-2026-02-10) — 샘플 **8개**, 필드 query/intent/context/reference_answer/**human_scores**/**annotator_agreement**, `min_kappa` 포함, 포함 기준 Cohen's kappa ≥ 0.6 `[실측: git show d344a9ea:…/calibration_set.json + docs/plans/chat-eval-pipeline-plan.md:453]`
- **eval subgraph**: eval_entry → Send API 병렬(code_grader ∥ llm_grader ∥ calibration_check) → eval_aggregator → eval_decision `[실측: infrastructure/orchestration/langgraph/eval_graph_factory.py:8-21 + factory.py:109-111 main graph 배선]`
- **점수의 정확한 의미**: full mode의 0–100은 L2 BARS 가중합이다. L1은 독립 진단과 개선 hint로 보존되고 L2 점수가 없을 때만 code-only 점수로 대체된다. L3는 각 답변의 세 번째 점수가 아니라 judge drift 신호다. 따라서 세 layer를 단일 점수의 직렬 합산으로 설명하지 않는다. `[실측: score_aggregator.py:80-136, eval_graph_factory.py:420-462]`
- **품질 게이트 프로세스**: 설계 리뷰 5라운드 69.4 → 89.2 → 95.4 → 98.8 → **99.8/100** (2026-02-09), 구현 리뷰 97.1, 테스트 165개(단위 148+통합 17) 전수 통과, PR #545/#546 merge `[문서주장: docs/plans/chat-eval-pipeline-review.md:9-15, docs/reports/chat-eval-pipeline-implementation-report.md; PR #546 merge 커밋 1a5463a7은 실측]`

### ⚠ 정직성 단서 (발표에서 과장 금지)

1. eval 기본값이 서로 충돌한다. DTO의 `enable_eval_pipeline`은 `False`지만 runtime `Settings`는 `True`이고, dependency 조립부는 후자를 DTO에 전달한다. 배포 manifest에서 명시적 override는 발견되지 않았다. 따라서 "기본 비활성(opt-in)"으로 단정할 수 없으며, "현재 main의 활성 경로는 아래 조립 불일치 때문에 운영 가능 상태가 아니다"가 정확하다. `[실측: application/dto/eval_config.py:38, setup/config.py:125, setup/dependencies.py:912-955]`
2. `recalibrate()`는 **stub** — HITL 재교정 인프라 미구축(경고 로그만) `[실측+문서주장: impl report "recalibrate() stub — HITL 인프라 미구축", calibration_monitor.py 주석 "재교정 시 사용 (현재 미구현)"]`
3. persistence adapter 5종 + calibration_set.json을 추가한 커밋 **922a9e74, d344a9ea는 feat/chat-eval-pipeline 브랜치에만 있고 main 미머지**다. 더구나 `get_chat_graph()`는 현재 `create_chat_graph()` 시그니처에 없는 `eval_counter`를 넘기며, 내부 subgraph 호출에도 counter를 전달하지 않는다. runtime 기본값이 True인 상태에서 ModuleNotFoundError 또는 TypeError가 날 수 있으므로 eval은 "응답 평가 계약 구현·부분 통합"으로만 소개한다. `[실측: git branch --contains + git ls-tree main + setup/dependencies.py:1222 + factory.py:196-238, 659-666]`
4. calibration 8샘플은 CUSUM N=50 요구 대비 통계적으로 얇음 — "초기 시드셋" 프레임이 정직.
5. eval 파이프라인은 **2026-02 작업**(수상 이후 확장기 산출물). 해커톤 수상 기능으로 소개하면 안 됨.
6. Krippendorff α≥0.75, Expert Review "99.8/100" 등 포트폴리오 페이지 수치 일부는 로컬 근거 문서와 지표 이름이 다름(plan은 Cohen's kappa ≥0.6) — 발표에는 레포 실측치만 사용 권장.

### 데이터 자산·로그 (Data Engineer 직무 연결 소재)

- **도메인 데이터 taxonomy**: `item_class_list.yaml` **86개 품목**(재활용/종이/종이팩… 계층형) `[실측: apps/chat_worker/infrastructure/assets/data/item_class_list.yaml, grep 카운트 86]`, `situation_tags.yaml`(80개 상황 `[문서주장: README.md:138]`), 분리배출 규정 JSON **18종**(대형폐기물/음식물/재활용_플라스틱류 등) `[실측: apps/scan_worker/infrastructure/assets/data/source/ 18파일]` — scan_worker/chat/chat_worker 3곳에 동일 자산 복제 배포 `[실측: find 결과]`
- **평가 이력 영속화**: V005 migration으로 eval schema DDL, EvalResult에 model_version / prompt_version(**루브릭 git SHA**) / eval_duration_ms / eval_cost_usd / calibration_status 기록 `[실측: d344a9ea --stat + score_aggregator.py aggregate() 시그니처]`
- **로그 파이프라인**: Fluent Bit(DaemonSet) → Elasticsearch(현재 CR 1-node, 50Gi PVC) → Kibana, JSON 구조화 로그와 K8s 메타데이터 `[실측: workloads/logging/base/{fluent-bit,elasticsearch,kibana}.yaml]`
- **트레이싱**: LangSmith(LangGraph 트레이스) + OpenTelemetry E2E + Jaeger, aio-pika/OpenAI/Gemini instrumentation `[문서주장: README.md:343,446-451]`
- **멱등성/유실 방지**: Event Router Lua script 멱등 마킹(TTL 7200s), ACK 정책 수정(실패 시 XACK 스킵→Reclaimer 재처리), P0 데이터 유실 버그 자체 발견·수정 리포트 `[문서주장: docs/reports/event-router-improvement-report.md — P0: consumer.py:216-223 process_event 실패에도 ACK→영구 유실]`

---

## ⑥ 시각 자산 후보

| 자산 | 위치 | 용도 |
|---|---|---|
| LangGraph StateGraph mermaid (draw_mermaid 산출, intent→router→10노드→aggregator→answer) | backend/README.md:189-242 | **주장 1의 핵심 다이어그램** — 그대로 재작도 |
| Eval subgraph 구조 (Send API 병렬 3-grader) | eval_graph_factory.py:8-21 docstring | 주장 2 다이어그램 |
| SSE 포화→재설계 before/after (연결 곱폭발 1:21 → Event Bus) | docs/blogs/redis-streams-sse/00-architecture-migration.md | 주장 3 문제-해결 서사 |
| Token Streaming Event Bus mermaid (XADD→XREADGROUP→PUBLISH→SSE) | README.md:248-304 | 주장 3 아키텍처 |
| Scan E2E flow mermaid (Celery Chain 4단계) | README.md:61-131 | 파이프라인 소개 |
| Checkpoint 아키텍처 mermaid (Redis Primary + PG Sync, 192→8 conn) | README.md:357-391 | 심화 질문 대비 |
| k6 스윕 결과 표 + 원본 JSON 12개 | README.md:155-162 + backend 루트 k6-*.json | 수치 신뢰성 증빙(원자료 보유 어필) |
| 서비스 아키텍처 전경 이미지 / GitOps 이미지 | README.md:23, :720 (github user-attachments) | 오프닝 슬라이드 |
| 수상 사진 | frontend/README.md:21 | 도입부 |
| 데모 영상 | [Eco² 서비스 시연](https://youtu.be/aFtb-oPv2Bo) | 서비스 시연 |
| 기존 발표덱 PPTX | backend/portfolio/eco2/eco2-portfolio-html.pptx (+build_pptx.py) | 재활용 소스 |
| 실측 팩트 시트 | backend/portfolio/eco2/architecture-facts.md | 수치 SoT |
| Grafana ext-authz snapshot | README.md:876 링크 | 성능 스크린샷 |

---

## ⑦ 예상 질문 소재 (약점 포함)

1. **"팀 프로젝트인데 단독 확장이 무슨 뜻?"** → git으로 답: backend HEAD 2,277개 중 후보자 별칭 2,180개, 다른 팀원 9개, 자동화 88개. FE는 1월부터 인수(본인 12월 7→1월 157커밋, 타 FE 팀원 12월 종료). "12월까지는 FE 팀원 활동이 있었고, 1월부터 4개 영역 단독"이 정확한 표현. `[실측]`
2. **"평가 파이프라인 실제로 돌고 있나?"** → 정직 답변 필수: PR #546으로 grader·subgraph·DI 중심부는 main에 병합됐지만 runtime 설정 기본값과 DTO가 충돌하고, persistence adapter·calibration asset은 branch에만 있으며 `eval_counter` 인자가 graph factory 경계에서 끊긴다. async fire-and-forget도 feature branch에만 있고 recalibrate는 HITL 미구축 stub이다. "운영 상시 활성"이나 "main에서 즉시 실행 가능"이라고 답하면 코드로 반박당함.
3. **"97.8%는 뭘 어떻게 잰 수치인가?"** → k6 폴링 기반 E2E 완료율(300s 타임아웃, VU1000, 1,469/1,518), SSE 스트리밍 별도 스크립트 존재. 같은 날의 시간순 보존본은 92.5%→96.6%→0%×3→97.8%이며, 선형 튜닝 성공이 아니라 회귀 탐지와 복구 증거로만 사용한다.
4. **"LLM judge를 어떻게 믿나?"** → L1 결정론 게이트 + BARS 루브릭 + 축 셔플(편향 완화) + CUSUM 드리프트 감시 + human_scores 기반 calibration set. 약점: 샘플 8개, kappa 실측 기록 없음 → "시드셋 단계, 확장 설계 완료"로 방어.
5. **"intent 10개는 어떻게 정했나?"** → 도출 과정의 데이터 근거는 레포에 없음[미검증]. 서비스 도메인 분석 + 외부 API 단위로 설계했다는 서사로 답하고, "관찰"을 정량 주장으로 만들지 말 것.
6. **"위험물 안전은?"** → HAZARDOUS_WEIGHTS(safety 0.25 부스트) + hallucination blocklist가 준비된 답변. `[실측]`
7. **"데이터 품질 관리(직무 연결)"** → 86품목 taxonomy + 18종 규정 JSON의 버전/출처 관리, 3개 앱에 자산 복제 배포(동기화 리스크) — 스스로 한계 언급하면 governance 감수성 어필.
8. **"격리 실행 환경 경험은?"(직무 요구)** → Eco²에 코드 샌드박스는 없음. K8s taint 기반 노드 격리(worker-ai/worker-storage NoSchedule `[문서주장: README.md:707-709]`) + NetworkPolicy 21종으로 실행 격리 개념 연결 가능.
9. **수치 불일치 리스크**: README "24-Nodes" vs architecture-facts "20 EC2"; 포트폴리오 페이지 "9 intent/11 subagent" vs 코드 10 intent — 발표 자료는 **코드 실측치(10 intent, EC2 20)**로 통일할 것.
10. **비용/생산성 수치**(Cursor 76일, 10.66B tokens, $7,473; 커밋 10.2K 등)는 포트폴리오 페이지 주장으로 로컬 근거 미확인 `[미검증]` — PT에서 쓰려면 원자료 확보 후 사용.
