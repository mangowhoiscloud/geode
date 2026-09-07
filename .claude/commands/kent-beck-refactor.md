# Kent Beck Refactoring

> "Make the change easy, then make the easy change."

대상: `$ARGUMENTS`의 파일·모듈. 생략하면 현재 diff의 범위를 먼저 확인합니다.

- **Quick** (기본): 지정 대상 또는 현재 변경만 검토합니다.
- **Deep** (`--deep`): 지정 모듈의 호출 경로와 책임까지 살핍니다.
- **Audit** (`--audit`): 저장소 전역에서 후보를 찾고 실제 영향으로 우선순위를 정합니다.

판단 기준은 [Kent Beck review](../../.agents/skills/kent-beck-review/SKILL.md),
전수 감사는 [codebase audit](../../.agents/skills/codebase-audit/SKILL.md)를 따릅니다.
이 명령에 별도 팩토리 추출·파일 분할·검증 절차를 두지 않습니다.

리뷰 요청이면 근거와 수정안을 보고합니다. 변경까지 요청받았다면
[워크플로우](../../docs/workflow.md)에 따라 가장 작은 근본 수정을 구현하고,
[검증 기준](../../.agents/skills/geode-workflow/references/verification-gates.md)에
맞춰 확인합니다. 파일 길이·반복 횟수·실패 횟수만으로 구조 문제를 단정하지 않습니다.
기존 회귀 검증이 부족하면 보강하고, 호출부별로 같은 전체 테스트를 반복하지 않습니다.

## 역사 사례: GEODE Gateway-REPL 통합 (#461)

아래는 당시 기록이며, 현재 경로·루프 제한·CI 개수의 기준이 아닙니다.

**Before**: `handlers → sub_mgr → executor → AgenticLoop` 43줄 x 3곳 반복.

**차이점 매트릭스**:

| 관점 | REPL | Gateway | Batch |
|------|------|---------|-------|
| hitl_level | 2 (default) | 0 (autonomous) | 2 |
| system_suffix | "" | _GATEWAY_SUFFIX | "" |
| quiet | False | True | False |
| max_rounds | 50 | config.toml | 50 |

**After**: `_build_agentic_stack()` 1개. 호출부에서 차이만 명시.
**결과**: -55줄, CI 5/5 통과, 동작 동일성 보장.
