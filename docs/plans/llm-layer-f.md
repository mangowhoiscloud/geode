# llm-layer-f

## 문제
1. client.py 1182줄 God Object — 3 provider의 호출/retry/circuit breaker가 한 파일에
2. Adapter 6개 클래스 — 대부분 client.py에 위임만 하는 1줄 래퍼
3. Port Protocol 13개 — 구현체 1개뿐인 Protocol은 추상화가 아니라 간접 참조 (DomainPort 제외)
4. Proxy 30개 — 이전 마이그레이션 잔재
5. Agent SDK 도입 시 커스텀 Protocol과 충돌

## 근거
- 프론티어(Codex, OpenClaw) 어디에도 Port/Adapter 패턴 없음
- Codex: 생성자 주입 + 크레이트 경계 / OpenClaw: 파라미터 전달 + Provider Module
- Kent Beck: "구현체 1개인 인터페이스는 관료주의" (Fewest Elements)
- Agent SDK 호환: SDK 타입과 커스텀 Protocol 충돌 제거

## 소크라틱 게이트: 통과
- Q1: Port/Adapter 형태만 존재, 실질 작동 안 함 (Adapter가 client.py에 위임)
- Q2: 안 하면 깨지진 않지만 1,600줄 + 40파일 불필요 코드 유지
- Q3: 파일 수/줄 수 감소 + mypy 통과로 측정
- Q4: Provider Module 패턴 (OpenClaw과 동일)
- Q5: Codex + OpenClaw 모두 Port/Adapter 미사용

## 변경 범위

### 삭제 (40파일, ~2,700줄)
- infrastructure/ports/ 13파일 (DomainPort만 core/domains/port.py로 이동)
- infrastructure/adapters/llm/ 7파일
- infrastructure/adapters/mcp/ 14파일 (proxy)
- infrastructure/ 디렉토리 자체 (atomic_io, signal_adapter 이동)
- cli/ proxy 6파일
- extensibility/ proxy 전부
- auth/ proxy 전부

### 생성 (~1,100줄)
- core/llm/router.py — 디스패치 + ContextVar DI 유지
- core/llm/providers/anthropic.py
- core/llm/providers/openai.py
- core/llm/providers/glm.py
- core/llm/fallback.py
- core/domains/port.py — DomainPort만

### 이동
- infrastructure/atomic_io.py → core/utils/atomic_io.py
- infrastructure/signal_adapter.py → core/mcp/signal_adapter.py
- BillingError (agentic_llm_port.py) → core/llm/errors.py

### ContextVar DI
유지. 주입 대상이 Adapter → router 함수로 변경.
