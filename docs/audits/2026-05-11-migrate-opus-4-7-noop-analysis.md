# GEODE → Claude Opus 4.7 마이그레이션 — noop 결론 SOT

> **요청**: `/claude-api migrate` (Opus 4.7, scope = GEODE 전체)
> **결과**: ★ **본 GEODE 코드 베이스는 Opus 4.7 마이그레이션 완료 상태**. 변경 surface 0 lines of code.
> **Branch**: `feature/migrate-opus-4-7`

## TL;DR

`/claude-api migrate` 의 Step 1 (파일 분류) + breaking-change scan 결과, **GEODE 의 anthropic API caller path 가 이미 모든 Opus 4.7 breaking change 를 처리하고 있음** — sampling params 자동 제거, `budget_tokens` legacy 분기는 4.7 진입 X, `display: "summarized"` 명시 적용, `xhigh` effort 의 4.7-only gating 까지 완비.

본 PR 은 **코드 변경 0** + 본 분석 보고서 + CHANGELOG entry.

## Step 1 — 파일 분류 결과

### `claude-*` 참조 분포 (총 ~87개 파일, audits/venv 제외)

| 디렉토리 | 파일 수 | 분류 |
|----------|--------|------|
| `tests/` | 57 | Mock-based fixtures — API caller 아님 |
| `core/` | 23 | router/providers/adapter — adaptive path 통과 |
| `plugins/` | 5 | game_ip + petri_audit — router 통과 |
| `experimental/` | 2 | `claude-haiku-4-5-20251001` — Opus 4.7 영향 X |

### Bucket 분류

| Bucket | 정의 | 처리 |
|--------|------|------|
| **1 (API caller)** | `client.messages.create(model=…)` 직접 호출 | `core/llm/providers/anthropic.py` 만 해당. 이미 완벽 처리 (아래 §검증). |
| **2 (definer/registry)** | `MODEL_PRICING`, `ANTHROPIC_PRIMARY`, 카탈로그 | 모두 갱신됨. `claude-opus-4-7` 항목 존재. |
| **3 (opaque string)** | UI label, test fixture, doc | mock-based tests + README/CLAUDE.md 의 `claude-opus-4-7` 라벨 일관. |
| **4 (suffixed variant)** | `claude-haiku-4-5-20251001` 같은 dated id | experimental/ 2 파일. 영향 없음. |

## 검증 — Opus 4.7 breaking change 체크리스트

| 항목 | GEODE 상태 | 위치 |
|------|-----------|------|
| **`thinking: budget_tokens`** legacy 분기에서 4.7 진입 X | ✅ `_ADAPTIVE_MODELS` 에 4.7 포함 → adaptive path 우선 | `core/llm/providers/anthropic.py:367` (`_ADAPTIVE_MODELS = frozenset({"claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6"})`) |
| **`temperature` 자동 제거** | ✅ adaptive path 에서 `call_temperature = None` | `anthropic.py:541` |
| **`top_p` / `top_k` 미사용** | ✅ caller 가 전달해도 adapter 가 ignore | router → adapter contract |
| **`thinking.display: "summarized"`** 명시 | ✅ default `"omitted"` 회피, UX 일관 | `anthropic.py:530` (v0.56.0 R4-mini) |
| **`effort: "xhigh"`** Opus 4.7 only gate | ✅ `_XHIGH_EFFORT_MODELS = {"claude-opus-4-7"}` | `anthropic.py:380` |
| **MODEL_PRICING entry** | ✅ in=$5/Mtok, out=$25/Mtok, cache_read=in×0.1 | `core/llm/token_tracker.py` |
| **ANTHROPIC_PRIMARY default** | ✅ `"claude-opus-4-7"` | `core/config/__init__.py:214` |
| **Retired models** (claude-2.x, 3.5-sonnet-20240620 등) | ✅ 코드 베이스에 0개 잔존 | rg grep |
| **README / CLAUDE.md 라벨** | ✅ `claude-opus-4-7` 표기 일관 | `README.md:40,159,272` |
| **dry-run 검증** | ✅ `geode audit --target claude-opus-4-7` 정상 동작 | $0.53 / 737 KRW estimate |

## 본 PR scope

**코드 변경**: 0 lines.
**문서 변경**: 본 분석 보고서 1 file + CHANGELOG entry.

본 PR 의 가치는 **"GEODE 의 anthropic adapter 가 Opus 4.7 호환 완비됐다는 사실의 SOT"** — 향후 점검 시 회귀 가드.

## 향후 점검 (별도 PR)

직전 점검 (#1020 후속) 의 누락 항목들과 본 분석으로 발견된 cosmetic 부분:

| # | 항목 | 우선 |
|---|------|------|
| 1 | **`[Unreleased]` release cut → v0.90.0** — 본 세션 누적 20+ entries | 상 |
| 2 | F-A1 ~ F-A4 fix (결함 A 의 H6/H7 fix) | 상 (라이브 1 sample ~$0.30) |
| 3 | `docs/audits/eval-logs/README.md` 매핑 표 갱신 (본 세션 신규 4 archive) | 중 |
| 4 | `--no-auto-archive` 옵션 CLI 노출 | 중 |
| 5 | flaky `test_retry_on_rate_limit` root cause 추적 | 중 |
| 6 | worktree cleanup (본 세션 12+ feature branches) | 하 |
| 7 | 결함 R 의 inspect_ai -T comma-split 추적 | 하 |

## 참조

- `core/llm/providers/anthropic.py:365-385` — `_ADAPTIVE_MODELS`, `_XHIGH_EFFORT_MODELS`, `_supports_xhigh_effort`
- `core/llm/providers/anthropic.py:518-545` — adaptive thinking path (temperature/output_config 처리)
- `shared/model-migration.md` (`/claude-api migrate` skill) — Step 0 (scope), Step 1 (분류), Opus 4.7 breaking changes
- 본 세션 라이브 검증 (#1020): anthropic stack 1 sample 정상 success, target=claude-opus-4-7 호출 검증
