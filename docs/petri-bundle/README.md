# Petri × GEODE Alignment Audit — Benchmark Bundle

본 directory 의 `inspect_ai` 의 native log viewer 의 static bundle. 본 GEODE
의 Petri × alignment audit 의 archive 의 web-viewable form.

## 본 publish URL

GitHub Pages 의 source: `main` branch / `/docs`. 본 viewer 의 URL:
- https://mangowhoiscloud.github.io/geode/petri-bundle/

## 본 bundle 의 contents

7 archive 의 native viewer 의 expose:

| Archive | Target | Wrap | seed | 비고 |
|---|---|---|---|---|
| `geode-13-v3.eval` | claude-opus-4-7 | GEODE | (v3) | first valid run after G-A1+G-A2 |
| `vanilla-13-v3.eval` | anthropic/claude-opus-4-7 | vanilla | (v3) | v3 baseline |
| `n5-opus-geode-seed1.eval` | claude-opus-4-7 | GEODE | n5 seed 1 | N=5 plan 의 첫 sample |
| `n5-opus-vanilla-seed1.eval` | anthropic/claude-opus-4-7 | vanilla | n5 seed 1 | |
| `n5-sonnet-geode-seed1.eval` | claude-sonnet-4-6 | GEODE | n5 seed 1 | |
| `n5-sonnet-vanilla-seed1.eval` | anthropic/claude-sonnet-4-6 | vanilla | n5 seed 1 | |
| `n5-gpt55-vanilla-seed1.eval` | openai/gpt-5.5 | vanilla | n5 seed 1 | GEODE wrap 의 credit exhaust 의 fail |

## 본 viewer 의 활용

- 3-perspective view (auditor / target / judge)
- 17 dim score 의 inline chart
- branch navigation (auditor 의 rollback)
- citation highlight (judge 의 transcript reference)

## 본 audit 의 보고서

- `../audits/2026-05-12-petri-geode-audit-v3.md` — v3 valid 보고서
- `../audits/2026-05-12-petri-multi-model-partial.md` — multi-model partial + credit exhaust 의 정직 한 명시
- `../audits/2026-05-12-petri-geode-audit.md` — v1 retraction 의 origin

## 본 bundle 의 reproduce

```bash
cd <worktree>
uv sync --extra audit
inspect view bundle --log-dir logs/ --output-dir docs/petri-bundle --overwrite
```

본 bundle 의 update 시 의 `index.html` 의 `abs_log_dir` 의 `"logs"` 의 redaction 의 portability.
