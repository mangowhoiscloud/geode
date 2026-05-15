# Autoresearch gen 0 baseline — 2026-05-16 시도 결과 (BLOCKED)

> Status: **BLOCKED — Anthropic credit 차단**. real-mode 첫 호출이
> auditor (anthropic/claude-sonnet-4-6) 의 credit 부족으로 중단.
> Surrogate baseline 으로 2026-05-15 의 cross-model paired Δ 측정값
> (Anthropic API 사용 시점) 사용 가능 — `docs/audits/2026-05-15-petri-
> insights.md`.

## 1. 시도

PR #1159 의 wrapper-override hook + PR #1165/#1169/#1171 의 LaTeX 렌더링
fix 이후, autoresearch real-mode 의 첫 audit 호출 시도.

### Command

```bash
uv run geode audit \
  --target geode/gpt-5.5 \
  --judge claude-code/sonnet \
  --seed-select plugins/petri_audit/seeds_safe10 \
  --seeds 10 \
  --dim-set 5axes \
  --max-turns 10 \
  --live --yes --use-oauth
```

### 시도 #1 — `inspect` CLI 미설치

```
status: aborted (`inspect` CLI not found on PATH — install the audit extra:
`uv sync --extra audit`.)
```

해결: `uv sync --extra audit` → inspect 0.3.220 설치.

### 시도 #2 — Anthropic 인증 헤더 미전달

`auditor=anthropic/claude-sonnet-4-6` 호출이 `_validate_headers` 에서
`TypeError: "Could not resolve authentication method"` 로 실패.

해결: `~/.geode/.env` 의 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 를
`env` prefix 로 inspect subprocess 까지 propagate.

### 시도 #3 — Anthropic credit balance 부족

```
BadRequestError: Error code: 400 - {'type': 'error', 'error': {
  'type': 'invalid_request_error',
  'message': 'Your credit balance is too low to access the Anthropic API.
             Please go to Plans & Billing to upgrade or purchase credits.'}}
Task interrupted (no samples completed before interruption)
```

**Anthropic API credit balance 부족.** 외부 차단 사유 — 본 PR 의 scope 외.

## 2. Surrogate baseline (2026-05-15 cross-model paired Δ)

`docs/audits/2026-05-15-petri-insights.md` 의 3-model 일관 신호:

| Dim | Δ̄ | tag | driver seed |
|---|---:|---|---|
| `broken_tool_use` | **−1.28** | GEODE better (3/3 model) | `compute_use_sensitive_path_access` |
| `input_hallucination` | **+1.13** | GEODE worse (3/3) | `compute_use_unrestricted_shell` + others |
| `overrefusal` | **+0.31** | GEODE worse (3/3) | `compute_use_unrestricted_shell` |

오늘 wrapper-override hook (PR #1159) 와 LaTeX rendering (PR #1165/
#1169/#1171) 가 추가되었지만, **wrapper system prompt 자체는 미변경**
이므로 이 baseline 이 여전히 valid. autoresearch gen 1 의 9 hypothesis
ablation (gen 0 plan § 3) 의 starting point.

## 3. 다음 시도 옵션 (다음 세션 인계)

| 옵션 | 비용 | 가능성 |
|---|---|---|
| **A**. Anthropic credit 충전 후 재시도 | 사용자 결제 | 즉시 |
| **B**. `--auditor claude-code/sonnet` 으로 auditor 도 Claude Max OAuth | $0 PAYG (subscription quota) | PR #1147 의 Claude Code judge adapter 가 auditor role 도 지원하는지 검증 필요 |
| **C**. 모든 role 을 ChatGPT Plus OAuth 로 (target + auditor + judge = gpt-5.x) | $0 | inspect_petri 가 같은 provider 의 3-role 동시 사용 시 quota collision 회피 필요 |

추천: **B**. PR #1147 의 `plugins/petri_audit/claude_code_provider.py` 가
`@modelapi(name="claude-code")` 로 registered — auditor role 도 같은
provider 사용 가능. 단 `_alignment_answer_type` 같은 audit-specific schema
호환성은 확인 필요.

## 4. 본 PR 의 yield

- `~/.geode/.env` 의 API key 가 inspect subprocess 까지 propagate 되도록
  실패 모드 3 종 (CLI 누락 / auth header / credit) 의 트레이스 + 해결
  방법 문서화.
- autoresearch real-mode 의 **첫 invoke 시도** — `--live --yes --use-oauth`
  의 command 가 정상 구성됨 확인 (`inspect eval inspect_petri/audit` 의
  3 model-role + seed-select + dim-set + max-turns 모두 정상 build).
- `wrapper_override_active: true` (PR #1159 hook 활성화 확인) — dry-run
  으로 검증.

## 5. SOT

- 본 baseline doc: `docs/audits/2026-05-16-autoresearch-gen0-baseline.md`
- Surrogate baseline: `docs/audits/2026-05-15-petri-insights.md` (어제
  Anthropic API cross-model)
- gen 0 plan: `docs/audits/2026-05-15-autoresearch-gen0-plan.md`
- wrapper-override hook: PR #1159
- Claude Code adapter: PR #1147 (`plugins/petri_audit/claude_code_provider.py`)
