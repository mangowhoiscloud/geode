# Plan: .geode/ 시스템 구축

## 프론티어 리서치 요약

| 시스템 | 관련 패턴 | 채택 여부 | 근거 |
|--------|----------|----------|------|
| Claude Code | `.claude/` 3-tier hierarchy (global/project/user-project) | 변형 | `.geode/`를 에이전트 시스템으로, `.claude/`는 하네스 전용으로 분리 |
| Codex | 해당 없음 | 불채택 | Sandbox/TDD 중심, identity 패턴 없음 |
| OpenClaw | boot-md (agent:bootstrap), 4단계 스킬 우선순위 | 변형 | 스타트업 시 GEODE.md 자동 로딩 (boot-md 패턴) |
| autoresearch | P7 program.md (루트 정체성), P1 제약 기반 설계 | **채택** | GEODE.md = program.md 역할, CANNOT 섹션 포함 |

## 설계 판단

### D1. GEODE.md 위치 = 프로젝트 루트
- **근거**: Karpathy P7 — "program.md 품질 = 에이전트 품질". 가시성이 핵심.
- **대안 검토**: `docs/SOUL.md` → 가시성 부족. `.geode/SOUL.md` → 런타임 데이터와 혼재.
- **결정**: `./GEODE.md` (CLAUDE.md와 동급 위치)

### D2. .claude/ vs .geode/ 역할 분리
- **근거**: 관심사 분리. Claude Code 하네스 설정 ≠ GEODE 에이전트 메모리.
- `.claude/` = Claude Code 전용 (settings, hooks, skills, worktrees)
- `.geode/` = GEODE 에이전트 전용 (memory, rules, journal, vault, config)

### D3. ProjectMemory 경로 변경
- `.claude/MEMORY.md` → `.geode/memory/PROJECT.md` (GEODE 전용 프로젝트 메모리)
- `.claude/rules/*.md` → `.geode/rules/*.md` (도메인 규칙)
- `.claude/MEMORY.md`는 Claude Code 자체 메모리로 유지 (수정하지 않음)

### D4. User Profile 스타트업 활성화
- `startup.py`에서 `FileBasedUserProfile.ensure_structure()` 호출
- `~/.geode/user_profile/` 자동 생성 (profile.md, preferences.json, learned.md)

## 구현 Phase

### Phase 1: GEODE.md 생성 + SOUL 경로 변경
- `./GEODE.md` 작성 (범용 자율 에이전트 정체성)
- `core/memory/organization.py`: `DEFAULT_SOUL_PATH` → `./GEODE.md`
- `.claude/SOUL.md` 삭제

### Phase 2: Rules 이동
- `.claude/rules/*.md` → `.geode/rules/*.md` 물리적 이동
- `core/memory/project.py`: `_rules_dir` 경로 변경

### Phase 3: Memory 분리
- `.geode/memory/PROJECT.md` 생성 (GEODE 전용)
- `core/memory/project.py`: `_memory_file` 경로 변경
- `ensure_structure()` 업데이트

### Phase 4: User Profile 활성화
- `core/cli/startup.py`: `ensure_structure()` 호출 추가

### Phase 5: geode init 정비
- `.geode/memory/`, `.geode/rules/` 디렉토리 자동 생성

### Phase 6: 테스트 업데이트
- 경로 참조 변경된 테스트 파일 수정
