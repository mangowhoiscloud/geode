# Backlog Disposition — 2026-05-18

세 backlog 항목 (#51, #53, #55) 의 검토 결과 + 재검토 trigger 명시. 모두 현 시점 추가 작업 보류로 결론.

## #55 — site/ components game_ip 잔존 정리

### Finding

```bash
grep -rln "game_ip\|game-ip\|GameIP" site/src/ | grep -v "data/geode/changelog.ts"
# → site/src/app/portfolio/versions/v{1..5}/components-snapshot/sections/*.tsx
# → site/src/app/portfolio/versions/v{1,4,5}/CHANGELOG.md
```

### 분석

- 모든 hit 가 `site/src/app/portfolio/versions/v{1..5}/components-snapshot/` 폴더 (의도적 historical snapshot).
- `grep -rln "components-snapshot" site/src/` → 0건. 어떤 page 도 이 폴더를 import 하지 않음.
- 각 version 의 `CHANGELOG.md` 헤더가 "Portfolio v1 — Snapshot 2026-03-28" 처럼 dated snapshot 임을 명시.
- 실제 라이브 page 는 `versions/vN/page.tsx` 에서 `@/components/geode/sections/*` (현재 컴포넌트) 를 import — snapshot 폴더와 완전 분리.

### Disposition

**No action**. 의도된 archival material. live render 에 영향 없음. `site/src/data/geode/changelog.ts` 의 historical CHANGELOG bodies 보존 결정 (v0.99.13 audit) 과 같은 원칙.

### 재검토 trigger

- 사용자가 portfolio versions 전체를 purge 결정 (예: legal/IP 리스크 발견).
- snapshot 폴더가 어떤 page 에서 import 되기 시작 (즉시 live render 영향).

---

## #51 — credential_source DI 리팩토 (P1-D follow-up)

### Finding

- `plugins/petri_audit/credential_source.py` (216 lines, P1-D 신설).
- API: `list_credential_sources`, `resolve_credential_source`, `suppress_credential_source`, `is_suppressed`, `clear_suppressions`.
- Module-level state: `_suppressed: set[tuple[str,str]]` + `_lock: threading.Lock` + `_LEGACY_OAUTH_ALIAS: dict`.
- Direct deps: `plugins.petri_audit.adapters` (`is_adapter_available`, `get_adapter_metadata`), `plugins.petri_audit.manifest` (`load_manifest`, `AUTO_SOURCE`), `core.config.settings` (lazy import).
- Consumers: `models.py:170`, `registry.py:28+140`, `cli.py:27+309+394`, `tests/plugins/petri_audit/test_credential_source.py`.

### 분석

P1-D follow-up 의도는 module-level state + 직접 import 를 클래스화 (`CredentialSource(adapters, manifest, settings)`) 해 mock 주입 가능하게 만드는 것. 하지만:

| 측면 | 현재 상태 | DI 도입 효과 | 비용 |
|------|----------|-------------|------|
| 테스트 | `clear_suppressions()` 픽스처 + `core.config.settings` monkeypatch 로 이미 충분 | mock 주입 더 깔끔 | 기존 5개 consumer 의 호출 사이트 모두 갱신 |
| Thread safety | 모듈 단일 `_lock` + idempotent `add` | 인스턴스마다 별도 lock (오히려 분산) | 신규 lock 관리 비용 |
| 다중 인스턴스 필요성 | 없음 (Petri 가 단일 프로세스, 단일 manifest) | 가능해짐 (테스트 외 사용처 없음) | 추상화 부담 |
| Hermes parity | `agent/credential_sources.py` 도 module-level state | parity 깨짐 | reference frontier 와 발산 |

### Disposition

**Deferred**. 현 모듈은 단순 함수형 API + thread-safe 글로벌 상태로 5개 consumer 만족. 클래스화는 호출 사이트 갱신 비용 vs 테스트성 향상 트레이드오프에서 후자가 작음. tests 는 이미 `clear_suppressions()` + settings monkeypatch 로 충분.

### 재검토 trigger

- 다중 Petri 인스턴스 (예: 동일 프로세스 안에서 여러 audit run 병렬 + 서로 다른 manifest) 요구사항 발생.
- `core.config.settings` 가 mock 하기 어려운 형태로 변경 (예: lazy class proxy).
- Hermes `credential_sources.py` 가 클래스 기반으로 리팩토링 → frontier parity 유지 필요.

---

## #53 — Coverage ratchet 75% 복원

### Finding

`pyproject.toml [tool.coverage.run].omit` 의 현재 entries:

```toml
omit = [
    "core/ui/*",                          # CLI smoke-tested
    "core/cli/__init__.py",
    "core/cli/welcome.py",
    "core/cli/search_render.py",
    "core/cli/dispatcher.py",
    "core/cli/prompt_session.py",
    "core/cli/interactive_loop.py",
    "core/cli/typer_commands.py",
    "core/cli/typer_init.py",
    "core/cli/typer_serve.py",
    "core/cli/commands.py",
    "core/mcp_server.py",
    "core/tools/web_tools.py",
    "core/tools/document_tools.py",
    "core/tools/web_search.py",           # External-API + GUI tools, live-tested
    "core/tools/computer_use.py",
    "core/audit/dim_extractor.py",        # Inspect/Petri edge importers
    "core/audit/eval_to_jsonl.py",
    "core/audit/manifest.py",
]
fail_under = 75
```

### 분석

각 omit entry 는 명시적 카테고리:

1. **CLI/REPL smoke-tested** (`core/ui/*`, `core/cli/*`) — Typer 명령 + 인터랙티브 prompt_toolkit code. unit test 가 아니라 `geode version` smoke + integration test 에서 exercise. 정당.
2. **External-API + GUI** (`core/tools/web_search.py`, `core/tools/computer_use.py`, `core/tools/web_tools.py`, `core/tools/document_tools.py`) — Playwright / search API / GUI control. `-m live` test 에서 exercise. unit cover 부적합 (mock 비용 > 가치).
3. **Inspect/Petri 가져오기** (`core/audit/{dim_extractor,eval_to_jsonl,manifest}.py`) — Petri eval log → unified format 변환기. fixture 가 없으면 의미 있는 unit test 불가. integration test (`tests/integration/`) 에서 cover.

"복원" 의 의미를 두 가지로 해석 가능:

A. **omit 제거 + unit test 작성** — 위 3 카테고리 모두 mock-heavy 비실용적. 외부 의존성 (Anthropic API, Playwright, Petri eval format) mock 비용이 test 가치보다 큼.
B. **fail_under 를 실제 coverage 로 맞춤** — 현재 75% 가 omit 적용 후 측정값. omit 제거하면 73-74% 로 떨어짐. fail_under 만 낮추는 것은 ratchet 약화 (사용자 76a13ad6 에서 명시적으로 reject).

### Disposition

**Deferred**. 현재 75% 가 omit 적용 후 정직한 측정값 + 각 omit 의 카테고리별 정당화 명시. 진정한 "복원" 은 (a) integration/live test 가 unit test 와 동등하게 카운트되는 coverage 도구 도입, 또는 (b) omit 된 모듈 각각에 mock-heavy unit test 신규 작성 (PR 단위 5-10건 분량). 둘 다 별도 sprint 분량 작업.

### 재검토 trigger

- Coverage 도구 변경 (e.g. `coverage.py` → branch+integration 통합 카운팅).
- omit 된 모듈에 새 기능 추가되어 unit test 부담 정당화됨.
- 사용자가 명시적으로 "single-PR coverage sprint" 지시.

---

## Summary

| Task | Disposition | Trigger Count |
|------|-------------|---------------|
| #55 site/ game_ip | No action (intentional archive) | 2 |
| #51 credential_source DI | Deferred (5-consumer cost > test benefit) | 3 |
| #53 Coverage 75% 복원 | Deferred (real "restore" = multi-PR sprint) | 3 |

세 항목 모두 명시적 trigger 가 발생할 때까지 재오픈 보류.
