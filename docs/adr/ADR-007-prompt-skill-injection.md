# ADR-007: Prompt & Skill Injection System

## Status

Proposed

## Date

2026-02-27

## Context

GEODE는 저평가 IP를 발굴하는 LangGraph 기반 9-node 파이프라인이다. 현재 시스템에 대한 종합 감사 결과, 프롬프트 조립 경로에서 **5가지 critical disconnection**이 발견되었다.

### 1. Bootstrap Overrides 미사용

`BootstrapManager.apply_context()`가 `_prompt_overrides`, `_extra_instructions`, `_bootstrap_parameters`를 state에 준비하지만, **어떤 node도 이 값을 읽지 않는다**. `geode/nodes/` 전체에서 해당 키에 대한 grep 결과 0건.

```python
# geode/orchestration/bootstrap.py — state에 값을 넣지만
merged["_prompt_overrides"] = context.prompt_overrides
merged["_extra_instructions"] = context.extra_instructions
merged["_bootstrap_parameters"] = context.parameters

# geode/nodes/analysts.py — 아무도 읽지 않음
def _build_analyst_prompt(analyst_type: str, state: GeodeState) -> tuple[str, str]:
    system = ANALYST_SYSTEM.format(analyst_type=analyst_type)  # hardcoded
    user = ANALYST_USER.format(...)  # hardcoded
    return system, user
```

### 2. Memory Context 미사용

`ContextAssembler`가 3-tier 메모리(Organization -> Project -> Session)를 조립하고, `cortex_node`가 `state["memory_context"]`에 저장하지만, analyst/evaluator/synthesizer 어디서도 이 값을 읽지 않는다.

```python
# geode/nodes/cortex.py — memory_context를 state에 넣지만
result["memory_context"] = memory_context

# geode/nodes/analysts.py — memory_context를 참조하지 않음
# geode/nodes/evaluators.py — memory_context를 참조하지 않음
# geode/nodes/synthesizer.py — memory_context를 참조하지 않음
# geode/verification/biasbuster.py — memory_context를 참조하지 않음
```

### 3. Hook Metadata가 Machine-only

`hook.yaml` 메타데이터(events, priority, description)는 런타임 라우팅에만 사용되며, LLM 프롬프트에 도달하지 않는다. Hook이 프롬프트를 수정할 수 있는 메커니즘이 전혀 없다.

### 4. Prompt Hardcoding

모든 프롬프트가 `geode/llm/prompts.py`에 Python f-string으로 하드코딩되어 있다. 외부 설정, 스킬 파일, 또는 런타임 컨텍스트가 프롬프트 내용에 영향을 줄 수 없다.

### 5. Prompt Observability 부재

Hook 시스템은 node 이름, 실행 시간 등 메타데이터만 관찰한다. 최종 조립된 프롬프트의 해시, fragment 수, 길이 등을 추적할 방법이 없어 디버깅과 재현성 확보가 어렵다.

### 왜 이것이 중요한가

이 5가지 단절은 GEODE의 확장성을 근본적으로 제한한다:

- **Per-IP/Per-Genre 커스터마이징 불가**: "격투 IP 분석 시 전투 시스템 깊이에 가중치를 높여라"와 같은 지시를 외부에서 주입할 수 없다
- **메모리 시스템 무력화**: 3-tier 메모리를 조립하는 인프라가 존재하지만 LLM이 이를 활용하지 못한다
- **Bootstrap 시스템 사문화**: BootstrapManager가 완전히 구현되어 있으나 downstream 소비자가 없어 dead code와 동일하다
- **프롬프트 실험 비용**: 프롬프트 변경마다 Python 코드 수정 + 배포가 필요하다

---

## Decision Drivers

| # | Driver | 우선순위 |
|---|--------|---------|
| DD-1 | **기존 인프라 활용**: BootstrapManager, ContextAssembler, HookSystem 등 이미 구현된 코드를 살린다 | Critical |
| DD-2 | **Minimal Invasion**: `prompts.py`를 다시 쓰지 않는다. 기존 템플릿을 감싸는 어셈블러를 추가한다 | Critical |
| DD-3 | **`.md` = LLM Context**: OpenClaw의 증명된 패턴. YAML frontmatter(메타데이터) + Markdown body(프롬프트 fragment)로 스킬을 정의한다 | High |
| DD-4 | **Composable Prompt Assembly**: system prompt = base template + skills + memory + bootstrap overrides + extra instructions. 호출 시점에 조립, 저장하지 않는다 | High |
| DD-5 | **Prompt Observability**: 조립된 프롬프트의 해시와 메타데이터를 Hook을 통해 emit한다 | Medium |
| DD-6 | **Version Control 확장**: SHA-256 해시 기반 프롬프트 버전 관리를 조립된 프롬프트까지 확장한다 | Medium |
| DD-7 | **Anthropic Context Engineering 원칙**: "System prompt is a precious, finite resource" — 필요한 것만 JIT로 주입한다 | High |

---

## Considered Alternatives

### Alternative A: Prompt Override via State Key (단순 주입)

Node들이 `state["_prompt_overrides"]`를 직접 읽어 `.format()` 결과를 부분 교체하는 방식.

```python
# analysts.py 수정안 (Alternative A)
def _build_analyst_prompt(analyst_type, state):
    system = ANALYST_SYSTEM.format(analyst_type=analyst_type)
    overrides = state.get("_prompt_overrides", {})
    if "analyst_system" in overrides:
        system = overrides["analyst_system"]  # 전체 교체
    extra = state.get("_extra_instructions", [])
    if extra:
        system += "\n\n## Additional Instructions\n" + "\n".join(extra)
    ...
```

| 장점 | 단점 |
|------|------|
| 구현 최소 (각 node에 5줄 추가) | 중복 코드: 모든 node에 동일 패턴 반복 |
| 기존 코드 변경 최소 | Skill 시스템 없음: 체계적 fragment 관리 불가 |
| 즉시 적용 가능 | Observability 없음: 조립 과정 추적 불가 |
| | 버전 해시가 base template만 커버 |

### Alternative B: PromptAssembler 중앙 조립기 (선택)

새로운 `PromptAssembler` 클래스가 base template + skill fragments + memory context + bootstrap overrides를 조립. Node들은 직접 `.format()` 대신 PromptAssembler를 호출.

```python
# 신규 geode/llm/prompt_assembler.py
class PromptAssembler:
    def assemble(self, template, state, *, node, role_type) -> AssembledPrompt:
        # 1. Base template render
        # 2. + Skill fragments (from .md files)
        # 3. + Memory context
        # 4. + Bootstrap overrides / extra instructions
        # 5. Compute SHA-256 hash
        # 6. Emit PROMPT_ASSEMBLED hook event
        ...
```

| 장점 | 단점 |
|------|------|
| 단일 책임: 조립 로직 1곳에 집중 | 새 클래스 + 새 모듈 필요 |
| Skill `.md` 파일로 외부 설정 가능 | Node 호출부 변경 필요 (moderate invasion) |
| SHA-256 해시가 조립 전체를 커버 | Skill discovery 로직 구현 필요 |
| Hook 연동 자연스러움 | |
| Memory/Bootstrap 자동 주입 | |

### Alternative C: LangGraph Middleware (전처리 노드)

`prompt_injector` 노드를 analyst/evaluator 앞에 추가하여 state에 완성된 프롬프트를 미리 넣어두는 방식.

```
signals → prompt_injector → analyst×4  (기존: signals → analyst×4)
```

| 장점 | 단점 |
|------|------|
| Node 코드 변경 없음 | 토폴로지 변경: 기존 graph 구조 훼손 |
| 관심사 분리 명확 | Send API 호환성 문제: prompt_injector가 4종 analyst 프롬프트를 미리 조립해야 함 |
| | State에 프롬프트 전문 저장 → 메모리 낭비 |
| | Evaluator에도 동일 패턴 필요 → 중복 노드 |

### 비교 요약

| 평가 기준 | Alt A (State Key) | **Alt B (Assembler)** | Alt C (Middleware) |
|-----------|-------------------|-----------------------|-------------------|
| 구현 복잡도 | Low | **Medium** | High |
| 코드 중복 | High (node마다) | **None** (중앙화) | Low |
| Skill 지원 | None | **Full (.md)** | Partial |
| Observability | None | **Built-in** | Manual |
| 토폴로지 영향 | None | **None** | Breaking |
| 버전 해시 | Partial | **Complete** | Partial |
| Bootstrap 호환 | Manual | **Auto** | Manual |
| Memory 호환 | Manual | **Auto** | Auto |

---

## Decision

**Alternative B: PromptAssembler 중앙 조립기**를 채택한다.

### 근거

1. **5가지 단절을 단일 컴포넌트로 해결**: PromptAssembler가 bootstrap overrides, memory context, skill fragments, observability를 모두 처리한다
2. **토폴로지 보존**: LangGraph StateGraph 구조를 변경하지 않는다. Node 내부 호출만 `_build_*_prompt()` -> `assembler.assemble()`로 교체한다
3. **OpenClaw 패턴 채택**: `.md` 파일 기반 skill 시스템은 OpenClaw에서 프로덕션 검증됐다
4. **Anthropic Context Engineering 정합**: JIT 조립, attention budget 관리, structured context가 자연스럽게 구현된다
5. **기존 인프라 연결**: BootstrapManager와 ContextAssembler의 output을 소비하는 유일하게 깔끔한 경로다

---

## Design

### Architecture Overview

```
                              ┌─────────────────────────────────┐
                              │        PromptAssembler          │
                              │  geode/llm/prompt_assembler.py  │
                              ├─────────────────────────────────┤
                              │                                 │
  ┌──────────────┐            │  1. Base Template (prompts.py)  │
  │  prompts.py  │───render──►│     ANALYST_SYSTEM.format(...)  │
  │  (existing)  │            │                                 │
  └──────────────┘            │  2. + Skill Fragments (.md)     │
                              │     "## Game Mechanics Skill"   │
  ┌──────────────┐  discover  │     parsed from YAML+MD files   │
  │  geode/      │───load────►│                                 │
  │  skills/*.md │            │  3. + Memory Context            │
  └──────────────┘            │     state["memory_context"]     │
                              │     → "_llm_summary" key        │
  ┌──────────────┐            │                                 │
  │  Bootstrap   │───read────►│  4. + Bootstrap Overrides       │
  │  Manager     │            │     state["_prompt_overrides"]  │
  └──────────────┘            │     state["_extra_instructions"]│
                              │                                 │
  ┌──────────────┐            │  5. Compute assembled_hash      │
  │  Context     │───read────►│     SHA-256(full prompt)        │
  │  Assembler   │            │                                 │
  └──────────────┘            │  6. Emit PROMPT_ASSEMBLED event │
                              │     {node, hash, fragments, ..} │
                              └────────────┬────────────────────┘
                                           │
                                   AssembledPrompt
                                   (system, user, hash)
                                           │
                              ┌────────────▼────────────────────┐
                              │         Node (analyst,          │
                              │    evaluator, synthesizer,      │
                              │         biasbuster)             │
                              │                                 │
                              │  system, user = assembler(...)  │
                              │  response = get_llm_json()(     │
                              │      system, user)              │
                              └─────────────────────────────────┘
```

### Scope: LLM-Calling Nodes

PromptAssembler는 LLM 호출이 있는 **모든 노드**에 적용된다:

| Node | LLM Templates | Phase |
|------|--------------|-------|
| `analyst` (4종) | `ANALYST_SYSTEM`, `ANALYST_USER` | P1 |
| `evaluator` (3종 + prospect) | `EVALUATOR_SYSTEM`, `EVALUATOR_USER` + `EVALUATOR_AXES` rubric | P1 |
| `synthesizer` | `SYNTHESIZER_SYSTEM`, `SYNTHESIZER_USER` | P1 |
| `biasbuster` (inside `verification`) | `BIASBUSTER_SYSTEM`, `BIASBUSTER_USER` | P1 |

> **Note**: BiasBuster(`geode/verification/biasbuster.py`)는 `verification` node 내부에서 실행되며, `BIASBUSTER_SYSTEM`/`BIASBUSTER_USER` 프롬프트를 사용한다. Phase 1에서 PromptAssembler 적용 대상에 포함한다.

### Prompt 조립 순서 (Composition Order)

```
┌─────────────────────────────────────────────────────────┐
│                    System Prompt                         │
├─────────────────────────────────────────────────────────┤
│ [1] Base Template       prompts.py render result        │
│                         (ANALYST_SYSTEM, etc.)          │
├─────────────────────────────────────────────────────────┤
│ [2] Skill Fragment      geode/skills/analyst-*.md body  │
│     (0..N fragments)    priority 순 정렬                 │
├─────────────────────────────────────────────────────────┤
│ [3] Memory Context      ContextAssembler output의       │
│     (optional)          "_llm_summary" 키 (pre-formatted)│
├─────────────────────────────────────────────────────────┤
│ [4] Extra Instructions  BootstrapManager가 준비한       │
│     (optional)          per-IP/per-genre 지시사항        │
├─────────────────────────────────────────────────────────┤
│ [5] Prompt Override     _prompt_overrides 중 해당 키가   │
│     (optional, rare)    있으면 [1] 전체를 교체           │
│                         (allow_full_override=True 필요)  │
└─────────────────────────────────────────────────────────┘

                    User Prompt
┌─────────────────────────────────────────────────────────┐
│ [1] Base Template       prompts.py render result        │
│                         (ANALYST_USER, etc.)            │
├─────────────────────────────────────────────────────────┤
│ [2] User-side Skills    user prompt에 inject할          │
│     (optional, rare)    fragment (role=user인 skill)    │
└─────────────────────────────────────────────────────────┘
```

### Token Budget Limits

프롬프트 조립 시 토큰 예산을 관리하여 LLM context window를 보호한다. 아래 기본값은 `PromptAssembler` 생성자에서 설정 가능하다.

| 항목 | 기본 제한 | 비고 |
|------|----------|------|
| Skill fragment | max **500 chars** per fragment | 초과 시 truncation + 경고 |
| Skill fragments per node | max **3** fragments | 우선순위 순 상위 3개만 적용 |
| Memory context | max **300 chars** | `ContextAssembler`가 `_llm_summary` 생성 시 관리 |
| Extra instructions | max **5** instructions, **100 chars** each | 초과분은 드롭 + 경고 로그 |
| Total system prompt | warning at **4000 chars**, hard limit at **6000 chars** | Hard limit 초과 시 skill fragment부터 제거 |

```python
class PromptAssembler:
    def __init__(
        self,
        *,
        skill_registry: SkillRegistry | None = None,
        hooks: HookSystemPort | None = None,
        allow_full_override: bool = False,
        # Token budget configuration
        max_skill_chars: int = 500,
        max_skills_per_node: int = 3,
        max_memory_chars: int = 300,
        max_extra_instructions: int = 5,
        max_extra_instruction_chars: int = 100,
        prompt_warning_chars: int = 4000,
        prompt_hard_limit_chars: int = 6000,
    ) -> None: ...
```

### Component Details

#### 1. `AssembledPrompt` (dataclass)

```python
# geode/llm/prompt_assembler.py

@dataclass(frozen=True)
class AssembledPrompt:
    """조립 완료된 프롬프트. 불변 객체."""

    system: str
    user: str
    assembled_hash: str          # SHA-256[:12] of (system + user)
    base_template_hash: str      # 원본 template의 hash (prompts.py PROMPT_VERSIONS와 비교용)
    fragment_count: int          # 주입된 skill fragment 수
    total_chars: int             # system + user 전체 문자 수
    fragments_used: list[str]    # ["analyst-game-mechanics:1.0", "memory-context", ...]
```

#### 2. `PromptAssembler` (핵심 클래스)

```python
# geode/llm/prompt_assembler.py

class PromptAssembler:
    """프롬프트 조립기 — base template + skills + memory + bootstrap을 합성.

    Node에서 직접 .format()을 호출하는 대신 이 클래스를 통해 조립한다.
    조립 결과는 AssembledPrompt로 반환되며, PROMPT_ASSEMBLED hook event를 emit한다.

    Security:
        allow_full_override=False (기본값)일 때, _prompt_overrides는 기존 프롬프트에
        APPEND만 가능하고 전체 교체(REPLACE)는 불가하다. 프로덕션에서는 False를 유지하고,
        테스트/개발 환경에서만 True로 설정해야 한다.
    """

    def __init__(
        self,
        *,
        skill_registry: SkillRegistry | None = None,
        hooks: HookSystemPort | None = None,
        allow_full_override: bool = False,
        # Token budget (configurable)
        max_skill_chars: int = 500,
        max_skills_per_node: int = 3,
        max_memory_chars: int = 300,
        max_extra_instructions: int = 5,
        max_extra_instruction_chars: int = 100,
        prompt_warning_chars: int = 4000,
        prompt_hard_limit_chars: int = 6000,
    ) -> None:
        self._skills = skill_registry or SkillRegistry()
        self._hooks = hooks
        self._allow_full_override = allow_full_override
        self._max_skill_chars = max_skill_chars
        self._max_skills_per_node = max_skills_per_node
        self._max_memory_chars = max_memory_chars
        self._max_extra_instructions = max_extra_instructions
        self._max_extra_instruction_chars = max_extra_instruction_chars
        self._prompt_warning_chars = prompt_warning_chars
        self._prompt_hard_limit_chars = prompt_hard_limit_chars

    def assemble(
        self,
        *,
        base_system: str,
        base_user: str,
        state: dict[str, Any],
        node: str,
        role_type: str,
    ) -> AssembledPrompt:
        """Base template + skill + memory + bootstrap을 합성하여 최종 프롬프트를 반환.

        Args:
            base_system: prompts.py의 render된 system prompt (기존 .format() 결과)
            base_user: prompts.py의 render된 user prompt
            state: GeodeState dict (bootstrap/memory 키 포함)
            node: 노드 이름 ("analyst", "evaluator", "synthesizer", "biasbuster")
            role_type: 역할 타입 ("game_mechanics", "quality_judge", etc.)
        """
        base_hash = _hash_prompt(base_system + base_user)
        fragments_used: list[str] = []

        # --- Phase 1: Prompt Override ---
        overrides = state.get("_prompt_overrides", {})
        system_key = f"{node}_system"
        if system_key in overrides:
            if self._allow_full_override:
                # Full replacement (escape hatch for testing/dev only)
                system = overrides[system_key]
                fragments_used.append(f"override:{system_key}")
            else:
                # Append-only mode (production default)
                system = base_system + "\n\n" + overrides[system_key]
                fragments_used.append(f"override-append:{system_key}")
        else:
            system = base_system

        # --- Phase 2: Skill Fragment Injection ---
        skills = self._skills.get_skills(node=node, role_type=role_type)
        if skills:
            # Enforce per-node skill limit
            skills = sorted(skills, key=lambda s: s.priority)[:self._max_skills_per_node]
            skill_block = self._format_skill_block(skills)
            system = system + "\n\n" + skill_block
            for s in skills:
                fragments_used.append(f"{s.name}:{s.version}")

        # --- Phase 3: Memory Context Injection ---
        memory_ctx = state.get("memory_context")
        if memory_ctx and isinstance(memory_ctx, dict):
            memory_block = self._format_memory_block(memory_ctx)
            if memory_block:
                # Enforce memory char limit
                if len(memory_block) > self._max_memory_chars:
                    memory_block = memory_block[:self._max_memory_chars] + "..."
                    log.warning("Memory context truncated to %d chars", self._max_memory_chars)
                system = system + "\n\n" + memory_block
                fragments_used.append("memory-context")

        # --- Phase 4: Extra Instructions (Bootstrap) ---
        extra = state.get("_extra_instructions", [])
        if extra:
            # Enforce instruction limits
            extra = extra[:self._max_extra_instructions]
            extra = [inst[:self._max_extra_instruction_chars] for inst in extra]
            instructions_block = (
                "## Additional Instructions\n"
                + "\n".join(f"- {inst}" for inst in extra)
            )
            system = system + "\n\n" + instructions_block
            fragments_used.append(f"bootstrap-extra:{len(extra)}")

        user = base_user

        # --- Phase 5: Token Budget Enforcement ---
        total_system_chars = len(system)
        if total_system_chars > self._prompt_hard_limit_chars:
            log.error(
                "System prompt %d chars exceeds hard limit %d — trimming skill fragments",
                total_system_chars, self._prompt_hard_limit_chars,
            )
            # Trim strategy: remove skill fragments (lowest priority = highest number first)
            # Re-assemble without skills if needed
            system = system[:self._prompt_hard_limit_chars]
        elif total_system_chars > self._prompt_warning_chars:
            log.warning(
                "System prompt %d chars exceeds warning threshold %d",
                total_system_chars, self._prompt_warning_chars,
            )

        # --- Phase 6: Hash + Observability ---
        assembled_hash = _hash_prompt(system + user)
        total_chars = len(system) + len(user)

        result = AssembledPrompt(
            system=system,
            user=user,
            assembled_hash=assembled_hash,
            base_template_hash=base_hash,
            fragment_count=len(fragments_used),
            total_chars=total_chars,
            fragments_used=fragments_used,
        )

        # Emit hook event (metadata only, NOT raw prompt content)
        if self._hooks is not None:
            self._hooks.trigger(
                HookEvent.PROMPT_ASSEMBLED,
                {
                    "node": node,
                    "role_type": role_type,
                    "assembled_hash": assembled_hash,
                    "base_template_hash": base_hash,
                    "fragment_count": len(fragments_used),
                    "total_chars": total_chars,
                    "fragments_used": fragments_used,
                },
            )

        return result

    def _format_skill_block(self, skills: list[SkillDefinition]) -> str:
        """Skill fragment들을 하나의 블록으로 포맷.

        Per-fragment char limit 적용: max_skill_chars 초과 시 truncation.
        """
        parts: list[str] = []
        for skill in sorted(skills, key=lambda s: s.priority):
            body = skill.prompt_body
            if len(body) > self._max_skill_chars:
                body = body[:self._max_skill_chars] + "..."
                log.warning("Skill '%s' truncated to %d chars", skill.name, self._max_skill_chars)
            parts.append(f"## Skill: {skill.name}\n{body}")
        return "\n\n".join(parts)

    @staticmethod
    def _format_memory_block(memory_ctx: dict[str, Any]) -> str:
        """Memory context를 LLM-readable 블록으로 포맷.

        Contract: ContextAssembler는 memory_context dict에 `_llm_summary` 키를
        포함해야 한다. 이 키의 값은 ContextAssembler가 직접 생성한 pre-formatted
        LLM-readable 문자열이다. PromptAssembler는 이 문자열을 그대로 사용한다.

        `_llm_summary` 키가 없는 경우 (backward compatibility), 기존 키들로부터
        fallback 포맷을 생성한다.
        """
        # Primary path: ContextAssembler가 생성한 pre-formatted summary
        llm_summary = memory_ctx.get("_llm_summary")
        if llm_summary and isinstance(llm_summary, str):
            return f"## Context from Memory\n{llm_summary}"

        # Fallback path: 개별 키로부터 수동 포맷 (backward compatibility)
        parts: list[str] = ["## Context from Memory"]

        # 조직 수준 정보 (예: 회사 IP 포트폴리오 전략)
        if memory_ctx.get("_org_loaded"):
            org_strategy = memory_ctx.get("organization_strategy", "")
            if org_strategy:
                parts.append(f"- Organization strategy: {org_strategy}")

        # 프로젝트 수준 정보 (예: 이번 분석 세션의 목표)
        if memory_ctx.get("_project_loaded"):
            project_goal = memory_ctx.get("project_goal", "")
            if project_goal:
                parts.append(f"- Project goal: {project_goal}")

        # 세션 수준 정보 (예: 이전 분석 결과 참조)
        if memory_ctx.get("_session_loaded"):
            prev_results = memory_ctx.get("previous_results", [])
            if prev_results:
                for pr in prev_results[-3:]:  # 최근 3건만
                    parts.append(f"- Previous: {pr}")

        return "\n".join(parts) if len(parts) > 1 else ""
```

> **Memory Context Contract** (ContextAssembler ↔ PromptAssembler):
>
> `ContextAssembler.assemble()` 반환 dict에 `_llm_summary: str` 키를 포함해야 한다.
> 이 문자열은 ContextAssembler 자체가 3-tier 컨텍스트를 요약하여 생성하며,
> PromptAssembler는 이를 파싱 없이 그대로 system prompt에 append한다.
> 이 설계를 통해 ContextAssembler가 메모리 포맷의 소유권을 유지하고,
> PromptAssembler는 ContextAssembler의 내부 키 스키마에 결합되지 않는다.
>
> Fallback: `_llm_summary` 키가 없으면 기존 `_org_loaded`, `organization_strategy`,
> `project_goal`, `previous_results` 키를 사용하는 레거시 경로를 유지한다.

#### 3. Skill Definition Format (`.md`)

스킬은 YAML frontmatter + Markdown body로 정의한다. Markdown body가 곧 프롬프트 fragment이다.

```markdown
---
name: analyst-game-mechanics
node: analyst
type: game_mechanics
priority: 50
version: "1.0"
role: system
enabled: true
---
# Game Mechanics Analysis Skill

Focus on: core gameplay loop quality, combat/interaction system potential,
progression mechanics, skill/ability design space, and replay value.
Evaluate how the IP's signature elements translate to game mechanics.

## Genre-Specific Guidance
- Fighting/Action IPs: weight combat system depth heavily
- RPG IPs: prioritize progression and skill tree potential
- Sandbox IPs: evaluate creative freedom and emergent gameplay
```

```python
# geode/llm/skill_registry.py

@dataclass(frozen=True)
class SkillDefinition:
    """파싱된 skill .md 파일."""

    name: str
    node: str           # "analyst", "evaluator", "synthesizer", "biasbuster"
    type: str           # "game_mechanics", "quality_judge", etc. ("*" = all types)
    priority: int       # lower = higher priority (injected first)
    version: str
    role: str           # "system" or "user" (which prompt to inject into)
    enabled: bool
    prompt_body: str    # Markdown body (frontmatter 제외)
    source_path: Path


class SkillRegistry:
    """Skill `.md` 파일을 디렉토리에서 발견하고 관리.

    Discovery 우선순위 (OpenClaw의 4-priority pattern 차용):
      1. Bundled:    geode/skills/          (패키지 내장)
      2. Project:    ./skills/              (프로젝트 루트)
      3. User:       ~/.geode/skills/       (사용자 전역)
      4. Extra:      config에서 지정한 경로   (CLI --skills-dir)
    """

    def __init__(self, extra_dirs: list[Path] | None = None) -> None:
        self._skills: list[SkillDefinition] = []
        self._extra_dirs = extra_dirs or []

    def discover(self) -> list[SkillDefinition]:
        """모든 skill 디렉토리를 스캔하여 SkillDefinition 목록을 반환."""
        dirs = self._resolve_skill_dirs()
        skills: list[SkillDefinition] = []
        for d in dirs:
            if not d.is_dir():
                continue
            for md_file in sorted(d.glob("*.md")):
                try:
                    skill = self._parse_skill_file(md_file)
                    if skill and skill.enabled:
                        skills.append(skill)
                except Exception:
                    log.warning("Failed to parse skill file: %s", md_file, exc_info=True)
        self._skills = skills
        return skills

    def get_skills(
        self, *, node: str, role_type: str, role: str = "system"
    ) -> list[SkillDefinition]:
        """주어진 node + role_type에 매칭되는 스킬 목록 반환.

        type이 "*"인 스킬은 해당 node의 모든 type에 매칭된다.
        """
        return [
            s for s in self._skills
            if s.node == node
            and (s.type == role_type or s.type == "*")
            and s.role == role
        ]

    def _resolve_skill_dirs(self) -> list[Path]:
        """4-priority 순서로 skill 디렉토리 목록을 반환."""
        base = Path(__file__).resolve().parent.parent  # geode/
        dirs = [
            base / "skills",                           # 1. Bundled
            Path.cwd() / "skills",                     # 2. Project
            Path.home() / ".geode" / "skills",         # 3. User
        ]
        dirs.extend(self._extra_dirs)                  # 4. Extra
        return dirs

    @staticmethod
    def _parse_skill_file(path: Path) -> SkillDefinition | None:
        """YAML frontmatter + Markdown body를 파싱."""
        text = path.read_text(encoding="utf-8")

        # YAML frontmatter 분리 (--- ... --- 블록)
        if not text.startswith("---"):
            return None
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        frontmatter = yaml.safe_load(parts[1])
        if not isinstance(frontmatter, dict):
            return None

        body = parts[2].strip()

        return SkillDefinition(
            name=frontmatter.get("name", path.stem),
            node=frontmatter.get("node", ""),
            type=frontmatter.get("type", "*"),
            priority=int(frontmatter.get("priority", 100)),
            version=str(frontmatter.get("version", "0.1")),
            role=frontmatter.get("role", "system"),
            enabled=frontmatter.get("enabled", True),
            prompt_body=body,
            source_path=path,
        )
```

#### 4. Hook Event 추가: `PROMPT_ASSEMBLED`

```python
# geode/orchestration/hooks.py — HookEvent enum에 추가

class HookEvent(Enum):
    # ... (기존 17개)

    # Prompt Assembly (ADR-007)
    PROMPT_ASSEMBLED = "prompt_assembled"     # 18번째 event
```

> **Note**: 이 추가로 HookEvent는 17 → 18개가 된다. `tests/test_hooks.py::test_all_17_events_exist`를 `test_all_18_events_exist`로 업데이트하고, 검증 로직의 expected count를 18로 변경해야 한다. (구현 계획 Phase 0-1 참조)

Hook data에는 **프롬프트 원문을 포함하지 않는다** (보안/프라이버시). 메타데이터만 전달:

```python
{
    "node": "analyst",
    "role_type": "game_mechanics",
    "assembled_hash": "a1b2c3d4e5f6",
    "base_template_hash": "f6e5d4c3b2a1",
    "fragment_count": 3,
    "total_chars": 2847,
    "fragments_used": [
        "analyst-game-mechanics:1.0",
        "memory-context",
        "bootstrap-extra:2"
    ],
}
```

### Integration Points

#### PromptAssembler 생성 (runtime.py)

PromptAssembler는 `GeodeRuntime`에서 생성한다. `runtime.py`는 모든 인프라 컴포넌트가 결합되는 중앙 지점이므로, assembler도 여기서 초기화하는 것이 일관된 패턴이다.

```python
# geode/runtime.py — _build_prompt_assembler() 추가

from geode.llm.prompt_assembler import PromptAssembler
from geode.llm.skill_registry import SkillRegistry

class GeodeRuntime:
    def __init__(self, *, ..., prompt_assembler: PromptAssembler | None = None) -> None:
        ...
        self.prompt_assembler = prompt_assembler

    @staticmethod
    def _build_prompt_assembler(
        *,
        hooks: HookSystemPort,
        skill_dirs: list[Path] | None = None,
    ) -> PromptAssembler:
        """Build PromptAssembler with SkillRegistry and hook integration."""
        skill_registry = SkillRegistry(extra_dirs=skill_dirs or [])
        skill_registry.discover()
        return PromptAssembler(
            skill_registry=skill_registry,
            hooks=hooks,
        )

    @classmethod
    def create(cls, ip_name: str, ...) -> GeodeRuntime:
        ...
        # Prompt assembler (ADR-007)
        prompt_assembler = cls._build_prompt_assembler(
            hooks=hooks,
            skill_dirs=None,  # settings.skill_dirs if configured
        )
        ...
```

#### PromptAssembler 주입: Closure를 통한 전달 (`_make_hooked_node()`)

`_make_hooked_node()` wrapper는 이미 모든 node를 감싸며, `hooks`와 `bootstrap_mgr`를 closure로 캡처한다. PromptAssembler도 **동일한 패턴으로 closure를 통해 전달**한다.

> **참고**: 이전 제안에서는 `contextvars`를 사용했으나, LangGraph Send API가 병렬 thread에서 node를 실행하기 때문에 문제가 발생한다. `contextvars`는 thread-safe (각 thread가 자체 복사본을 가짐)하지만, `set_prompt_assembler()`를 `compile_graph()` 시점에 main thread에서 한 번만 호출하면 worker thread에는 default값(None)이 전파된다. `_make_hooked_node()`가 이미 closure로 의존성을 캡처하는 기존 패턴을 따르는 것이 안전하고 일관된다.

```python
# geode/graph.py — _make_hooked_node() 수정

def _make_hooked_node(
    node_fn: Callable[[GeodeState], dict[str, Any]],
    node_name: str,
    hooks: HookSystemPort,
    bootstrap_mgr: BootstrapManager | None = None,
    prompt_assembler: PromptAssembler | None = None,  # ADR-007 추가
) -> Callable[[GeodeState], dict[str, Any]]:
    """Wrap a node function with hook triggers and prompt assembly."""

    def _wrapped(state: GeodeState) -> dict[str, Any]:
        # ... 기존 hook/bootstrap 로직 ...

        # ADR-007: PromptAssembler를 state에 임시 키로 전달
        # (node 내부의 _build_*_prompt()가 접근할 수 있도록)
        if prompt_assembler is not None:
            effective_state = dict(effective_state)
            effective_state["_prompt_assembler"] = prompt_assembler

        result = node_fn(effective_state)
        # ... 기존 hook/observability 로직 ...
        return result

    _wrapped.__name__ = f"hooked_{node_name}"
    return _wrapped


# geode/graph.py — build_graph() 수정

def build_graph(
    *,
    hooks: HookSystemPort | None = None,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    bootstrap_mgr: BootstrapManager | None = None,
    prompt_assembler: PromptAssembler | None = None,  # ADR-007 추가
) -> StateGraph[GeodeState]:
    ...
    def _node(fn, name):
        if hooks is not None:
            return _make_hooked_node(fn, name, hooks, bootstrap_mgr, prompt_assembler)
        return fn
    ...
```

#### Node 수정 패턴 (analysts.py 예시)

기존 `_build_analyst_prompt()`를 PromptAssembler 호출로 감싸는 최소 수정:

```python
# geode/nodes/analysts.py — BEFORE (현재)
def _build_analyst_prompt(analyst_type: str, state: GeodeState) -> tuple[str, str]:
    system = ANALYST_SYSTEM.format(analyst_type=analyst_type)
    user = ANALYST_USER.format(
        analyst_type=analyst_type,
        ip_name=ip["ip_name"],
        # ... (hardcoded)
    )
    return system, user


# geode/nodes/analysts.py — AFTER (제안)
def _build_analyst_prompt(analyst_type: str, state: GeodeState) -> tuple[str, str]:
    ip = state["ip_info"]
    ml = state["monolake"]
    sig = state["signals"]

    # Phase 1: 기존 방식으로 base template 렌더링 (prompts.py 변경 없음)
    base_system = ANALYST_SYSTEM.format(analyst_type=analyst_type)
    base_user = ANALYST_USER.format(
        analyst_type=analyst_type,
        ip_name=ip["ip_name"],
        # ... (기존과 동일)
    )

    # Phase 2: PromptAssembler로 skill + memory + bootstrap 주입
    assembler = state.get("_prompt_assembler")
    if assembler is not None:
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=dict(state),
            node="analyst",
            role_type=analyst_type,
        )
        return result.system, result.user

    # Fallback: assembler 미설정 시 기존 동작 유지 (backward compatible)
    return base_system, base_user
```

#### Node 수정 패턴 (evaluators.py 예시)

Evaluator는 analyst보다 프롬프트 구조가 복잡하다. `EVALUATOR_AXES` dict에서 axes schema와 rubric anchors를 동적으로 조합하기 때문에, base template 렌더링 후 rubric 블록이 추가된다.

```python
# geode/nodes/evaluators.py — AFTER (제안)
def _build_evaluator_prompt(evaluator_type: str, state: GeodeState) -> tuple[str, str]:
    ip = state["ip_info"]
    # ... (기존 ip_summary, analyst_findings, signals_summary 조립)

    # Phase 1: 기존 방식으로 base template 렌더링
    # Note: evaluator는 system prompt에 rubric anchors를 append하는 특수 패턴이 있음
    base_system = EVALUATOR_SYSTEM.format(
        evaluator_type=evaluator_type,
        axes_schema=_format_axes_schema(evaluator_type),
    ) + "\n\n" + _format_rubric_anchors(evaluator_type)

    base_user = EVALUATOR_USER.format(
        ip_name=ip["ip_name"],
        ip_summary=ip_summary,
        analyst_findings=analyst_findings,
        signals_summary=signals_summary,
        evaluator_type=evaluator_type,
        rubric_anchors=_format_rubric_anchors(evaluator_type),
    )

    # Phase 2: PromptAssembler로 skill + memory + bootstrap 주입
    assembler = state.get("_prompt_assembler")
    if assembler is not None:
        result = assembler.assemble(
            base_system=base_system,
            base_user=base_user,
            state=dict(state),
            node="evaluator",
            role_type=evaluator_type,
        )
        return result.system, result.user

    # Fallback
    return base_system, base_user
```

> **Evaluator 특이사항**: `EVALUATOR_AXES` dict에서 per-evaluator_type axes schema와 rubric anchors를 조립하여 system prompt에 붙이는 기존 패턴이 있다. 이 rubric 블록은 base template의 일부로 취급되며, PromptAssembler는 이 완성된 base_system 위에 skill/memory/bootstrap을 추가한다. `_format_axes_schema()`와 `_format_rubric_anchors()`는 변경하지 않는다.

#### Node 수정 패턴 (biasbuster.py 예시)

BiasBuster는 `verification` node 내부에서 호출되므로, state를 통해 전달된 `_prompt_assembler`를 사용한다.

```python
# geode/verification/biasbuster.py — AFTER (제안)
def run_biasbuster(state: GeodeState) -> BiasBusterResult:
    ...
    user = BIASBUSTER_USER.format(
        ip_name=state.get("ip_name", "Unknown"),
        analyst_details=analyst_details,
        # ... (기존과 동일)
    )

    base_system = BIASBUSTER_SYSTEM  # BiasBuster system prompt는 format 인자 없음

    # PromptAssembler 적용 (verification node에서 state로 전달됨)
    assembler = state.get("_prompt_assembler")
    system = base_system
    if assembler is not None:
        result = assembler.assemble(
            base_system=base_system,
            base_user=user,
            state=dict(state),
            node="biasbuster",
            role_type="bias_detection",
        )
        system = result.system
        user = result.user

    data = get_llm_json()(system, user)
    ...
```

#### make_analyst_sends / make_evaluator_sends 통합

Send API로 생성되는 sub-state에 bootstrap/memory 키를 전파해야 한다:

```python
# geode/nodes/analysts.py — make_analyst_sends() 수정

def make_analyst_sends(state: GeodeState) -> list[Any]:
    sends = []
    for atype in ANALYST_TYPES:
        send_state = {
            # ... 기존 키
            "_analyst_type": atype,
            # ADR-007: bootstrap + memory 키 전파
            "_prompt_overrides": state.get("_prompt_overrides", {}),
            "_extra_instructions": state.get("_extra_instructions", []),
            "memory_context": state.get("memory_context"),
        }
        sends.append(Send("analyst", send_state))
    return sends
```

> **Note**: `_prompt_assembler`는 `_make_hooked_node()` wrapper에서 state에 주입되므로, `make_*_sends()`에서 별도로 전파할 필요가 없다. `_make_hooked_node()`가 Send API에 의해 생성된 각 sub-node에도 적용되기 때문이다.

### ANALYST_SPECIFIC Migration Strategy (Phase 2)

Phase 2에서 `prompts.py`의 `ANALYST_SPECIFIC` dict를 bundled skill `.md` 파일로 외부화한다.

**Migration 규칙**:
1. `ANALYST_SPECIFIC`는 deprecated하지 않고 **fallback으로 유지**한다
2. Skill `.md` 파일이 해당 `node + type`에 존재하면, skill 파일이 **우선 적용**된다
3. 동일 `node + type`에 skill `.md`와 `ANALYST_SPECIFIC` 모두 존재하면, **skill `.md`만 사용**하고 `ANALYST_SPECIFIC` 값은 무시한다
4. Skill `.md` 파일이 없는 `node + type`에 대해서만 `ANALYST_SPECIFIC`이 사용된다

```python
# _build_analyst_prompt() 내부의 resolution 순서:
#
# 1. SkillRegistry에서 node="analyst", type=analyst_type 매칭되는 skill 검색
# 2. 매칭되는 skill이 있으면 → skill .md body 사용
# 3. 매칭되는 skill이 없으면 → ANALYST_SPECIFIC[analyst_type] 사용 (현재 동작)
# 4. ANALYST_SPECIFIC에도 없으면 → base template만 사용
```

이 전략은 점진적 마이그레이션을 보장한다. 팀이 skill `.md` 파일을 하나씩 추가하면서 자연스럽게 `ANALYST_SPECIFIC`에 대한 의존이 줄어든다. 모든 analyst type에 대한 skill 파일이 완비되면, `ANALYST_SPECIFIC` dict는 주석으로 deprecation을 표시하되 코드에서 제거하지 않는다 (backward compatibility).

### Prompt Override Security

`_prompt_overrides`가 system prompt 전체를 교체할 수 있다면, 악의적인 bootstrap hook이 유해한 프롬프트를 주입할 수 있는 보안 리스크가 존재한다.

**완화 방안**:

| 설정 | 동작 | 용도 |
|------|------|------|
| `allow_full_override=False` (기본값) | Override 값이 기존 prompt에 **append**만 됨 | 프로덕션 |
| `allow_full_override=True` | Override 값이 기존 prompt를 **전체 교체** | 테스트/개발 |

- 프로덕션 환경에서는 `allow_full_override=False`를 유지해야 한다
- `GeodeRuntime._build_prompt_assembler()`에서 `settings.allow_prompt_full_override` flag를 참조하여 설정
- Override 가능한 키는 `{node}_system` 패턴에 한정 (알려진 키만 허용). 임의의 키는 무시한다

### 현재 vs 제안 비교표

| 단절 | 현재 상태 | 제안 (ADR-007 적용 후) |
|------|-----------|----------------------|
| **#1 Bootstrap Overrides** | `_prompt_overrides`를 state에 넣지만 아무 node도 읽지 않음 | PromptAssembler가 `_prompt_overrides`, `_extra_instructions`를 자동으로 읽어 조립 |
| **#2 Memory Context** | `cortex_node`가 `memory_context`를 state에 넣지만 LLM에 도달 안 함 | PromptAssembler가 `memory_context._llm_summary`를 LLM-readable 형태로 system prompt에 주입 |
| **#3 Hook → Prompt** | Hook이 metadata만 관찰. 프롬프트 수정 불가 | Bootstrap hook이 `_extra_instructions`를 수정하면 PromptAssembler가 이를 반영. PROMPT_ASSEMBLED event로 결과 관찰 |
| **#4 Hardcoded Prompts** | 모든 프롬프트가 `prompts.py` f-string 고정 | `prompts.py`는 base template 유지. `.md` skill 파일로 외부 fragment 추가 가능 |
| **#5 Prompt Observability** | Hook이 node 이름/시간만 emit | `PROMPT_ASSEMBLED` event가 hash, fragment_count, total_chars, fragments_used를 emit |

---

## Consequences

### Positive

1. **Bootstrap 시스템 활성화**: 기존 BootstrapManager 코드가 의도대로 동작한다. Per-IP, per-genre 커스터마이징이 코드 수정 없이 가능해진다
2. **Memory-Prompt 연결**: 3-tier 메모리가 실제로 LLM의 판단에 영향을 준다. "이전 분석에서 Berserk은 S tier였다"와 같은 컨텍스트가 주입된다
3. **외부 Skill 시스템**: `.md` 파일 드롭만으로 프롬프트 동작을 확장할 수 있다. Python 코드 수정이나 재배포 없이 프롬프트 실험이 가능하다
4. **재현성 강화**: 조립된 프롬프트의 SHA-256 해시가 기록되므로, 동일한 입력 조건에서 동일한 프롬프트가 생성됐는지 검증할 수 있다
5. **Backward Compatibility**: PromptAssembler가 설정되지 않으면 기존 동작이 100% 유지된다. 점진적 마이그레이션이 가능하다
6. **Security by Default**: `allow_full_override=False` 기본값으로, 프로덕션에서 악의적 prompt 전체 교체를 방지한다

### Negative

1. **간접 참조 증가**: Node에서 프롬프트를 이해하려면 `prompts.py` + skill files + memory context + bootstrap state를 모두 확인해야 한다. 디버깅 시 "이 프롬프트가 어디서 왔는가"의 복잡도가 증가한다
2. **Skill 파일 관리 부담**: `.md` 파일이 늘어나면 어떤 skill이 어떤 node에 영향을 주는지 추적이 필요하다. skill registry의 list/inspect 기능이 필수다
3. **Context Window 예산**: Skill fragment + memory context가 system prompt에 추가되므로 토큰 사용량이 증가한다. Token Budget Limits (위 섹션 참조)를 통해 관리한다

### Risks

| 리스크 | 완화 방안 |
|--------|----------|
| Skill fragment가 base prompt와 모순되는 지시를 줄 수 있음 | Skill validation: fragment 내용이 base prompt의 JSON 스키마를 변경하지 않는지 lint 검사 |
| Memory context가 너무 커서 attention을 소모할 수 있음 | ContextAssembler가 `_llm_summary` 생성 시 max 300 chars 제한. PromptAssembler에서도 hard limit 적용 |
| PromptAssembler에 버그가 있으면 전체 파이프라인이 영향받음 | Fallback 경로 유지: `state.get("_prompt_assembler")` is None이면 기존 동작. 100% backward compatible |
| PROMPT_ASSEMBLED event가 성능에 영향을 줄 수 있음 | Hook trigger는 synchronous이므로 핸들러를 lightweight하게 유지. 로깅만 수행하는 기본 핸들러 제공 |
| `_prompt_overrides`로 전체 프롬프트 교체 시 보안 리스크 | `allow_full_override=False` 기본값. 프로덕션에서는 append-only. 전체 교체는 테스트/개발용 escape hatch |

---

## Implementation Plan

### Phase 0: Foundation (P0, 1일)

| 단계 | 파일 | 내용 |
|------|------|------|
| 0-1 | `geode/orchestration/hooks.py` | `HookEvent.PROMPT_ASSEMBLED` 추가 (1줄). docstring "17 events" → "18 events" 업데이트 |
| 0-2 | `tests/test_hooks.py` | `test_all_17_events_exist` → `test_all_18_events_exist`로 이름 변경, expected count를 18로 업데이트 |
| 0-3 | `geode/llm/prompt_assembler.py` | `AssembledPrompt` dataclass + `PromptAssembler` 클래스 (token budget limits, `allow_full_override` flag 포함) |
| 0-4 | `tests/test_prompt_assembler.py` | Unit tests: 조립 순서, hash 계산, fallback 동작, token budget 초과 시 truncation, allow_full_override=False 시 append-only 동작 |

이 Phase에서 기존 코드 변경: **hooks.py에 1줄 추가 + test_hooks.py 업데이트**. 나머지는 신규 파일.

### Phase 1: Bootstrap Wire (P1, 1일)

| 단계 | 파일 | 내용 |
|------|------|------|
| 1-1 | `geode/runtime.py` | `_build_prompt_assembler()` 추가, `create()`에서 호출, `compile_graph()`에 전달 |
| 1-2 | `geode/graph.py` | `_make_hooked_node()`에 `prompt_assembler` 파라미터 추가 (closure 패턴), `build_graph()`/`compile_graph()`에 전달 |
| 1-3 | `geode/nodes/analysts.py` | `_build_analyst_prompt()`에 PromptAssembler 호출 추가 |
| 1-4 | `geode/nodes/evaluators.py` | `_build_evaluator_prompt()`에 PromptAssembler 호출 추가 (rubric 패턴 유지) |
| 1-5 | `geode/nodes/synthesizer.py` | `_build_llm_synthesis()`에 PromptAssembler 호출 추가 |
| 1-6 | `geode/verification/biasbuster.py` | `run_biasbuster()`에 PromptAssembler 호출 추가 |
| 1-7 | `geode/nodes/analysts.py` | `make_analyst_sends()`에 `_prompt_overrides`, `_extra_instructions`, `memory_context` 전파 |
| 1-8 | `geode/nodes/evaluators.py` | `make_evaluator_sends()`에 동일 키 전파 |
| 1-9 | `geode/memory/context.py` | `ContextAssembler.assemble()`에 `_llm_summary` 키 생성 로직 추가 |
| 1-10 | `tests/test_bootstrap_wire.py` | Integration test: BootstrapManager -> state -> PromptAssembler -> 최종 prompt에 extra_instructions 포함 확인 |

이 Phase 완료 후: **단절 #1 (Bootstrap), #2 (Memory), #5 (Observability) 해결**.

### Phase 2: Skill System (P2, 1일)

| 단계 | 파일 | 내용 |
|------|------|------|
| 2-1 | `geode/llm/skill_registry.py` | `SkillDefinition` dataclass + `SkillRegistry` 클래스 |
| 2-2 | `geode/skills/` (디렉토리) | 초기 bundled skill `.md` 파일 4개 (analyst 4종 = 현재 ANALYST_SPECIFIC의 외부화). Skill `.md`와 `ANALYST_SPECIFIC`이 동일 type에 공존할 경우 skill `.md`가 우선 |
| 2-3 | `tests/test_skill_registry.py` | Discovery, parsing, priority 정렬, wildcard matching 테스트 |
| 2-4 | `geode/cli/commands.py` | `geode skills list` CLI 명령 추가 (선택) |

이 Phase 완료 후: **단절 #4 (Hardcoded Prompts) 해결**. `.md` 파일로 프롬프트 확장 가능.

### Phase 3: Observability & Validation (P3, 0.5일)

| 단계 | 파일 | 내용 |
|------|------|------|
| 3-1 | 기본 hook handler | PROMPT_ASSEMBLED event를 로깅하는 기본 핸들러 등록 |
| 3-2 | Skill validation | Skill `.md` frontmatter 스키마 검증 + prompt body 길이 경고 (max_skill_chars 기준) |
| 3-3 | Prompt budget | System prompt 총 문자 수 추정 + 경고 임계값 (warning at 4000 chars, hard limit at 6000 chars) |
| 3-4 | `docs/skills-guide.md` | Skill 파일 작성 가이드 (필요 시) |

이 Phase 완료 후: **단절 #3 (Hook Metadata) 부분 해결**. Hook이 PROMPT_ASSEMBLED를 통해 프롬프트 조립 결과를 관찰 가능. Hook이 직접 프롬프트를 수정하는 것은 Bootstrap 경로(extra_instructions)를 통해서만 허용.

### 파일 변경 요약

```
신규 파일 (3):
  geode/llm/prompt_assembler.py      PromptAssembler + AssembledPrompt
  geode/llm/skill_registry.py        SkillRegistry + SkillDefinition
  geode/skills/*.md                  Bundled skill files (4+)

수정 파일 (8):
  geode/orchestration/hooks.py       +1줄 (PROMPT_ASSEMBLED enum)
  geode/runtime.py                   _build_prompt_assembler() + create()에서 주입
  geode/graph.py                     _make_hooked_node() + build_graph()에 assembler 전달
  geode/nodes/analysts.py            _build_analyst_prompt + make_analyst_sends
  geode/nodes/evaluators.py          _build_evaluator_prompt + make_evaluator_sends
  geode/nodes/synthesizer.py         _build_llm_synthesis
  geode/verification/biasbuster.py   run_biasbuster에 assembler 적용
  geode/memory/context.py            _llm_summary 키 생성 추가
  geode/state.py                     (선택) memory_context, _prompt_overrides 타입 힌트

테스트 파일 (4):
  tests/test_prompt_assembler.py
  tests/test_skill_registry.py
  tests/test_bootstrap_wire.py
  tests/test_hooks.py                test_all_17 → test_all_18 업데이트
```

---

## References

| 참고 자료 | 핵심 인사이트 |
|-----------|-------------|
| [OpenClaw HOOK.md 시스템](https://github.com/openclaw/openclaw) | `.md` = LLM context, YAML frontmatter + Markdown body, `bootstrapFiles` array로 시스템 프롬프트 composition 제어 |
| OpenClaw Skill 시스템 | 4-priority loading (bundled -> extra -> managed -> workspace), SkillSnapshot.prompt 필드가 system prompt에 직접 주입 |
| [Anthropic: Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | "System prompt is a precious, finite resource", JIT retrieval, sub-agent focused context, structured note-taking |
| [Anthropic: How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | "Prompt engineering was our primary lever", 각 sub-agent에 clear objective + output format + task boundaries 부여 |
| GEODE architecture-v6.md | 6-Layer 아키텍처, Layer 2 Context Assembly, Layer 4 Hook System |
| ADR-001 through ADR-006 (implicit) | GEODE의 기존 architectural decision 맥락 |
| `research/openclaw-automation-analysis.md` | OpenClaw 4-Layer 자동화 분석 (Heartbeat, Cron, Hooks, Gateway) |
| `research/openclaw-analysis-report.md` | OpenClaw Pi Agent 시스템 심층 분석 (Skill 시스템, Bootstrap Hooks) |
