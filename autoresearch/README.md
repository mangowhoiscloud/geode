# autoresearch — Petri-signal fork (GEODE)

Karpathy [autoresearch](https://github.com/karpathy/autoresearch) (MIT, 2026-03,
26K+ stars, single-file ML training loop) 의 GEODE Petri-domain fork.
원본의 3-file 패턴 (prepare / train / program.md) + fixed-budget loop +
git-as-optimizer 정신을 그대로 보존하되, ML 도메인 (GPT pre-train + val_bpb)
을 alignment audit 도메인 (Petri seed pool + AlphaEval fitness) 으로 교체.

## Why fork instead of port

Karpathy 가 의도적으로 작게 유지한 3-file constraint 자체가 design — outer
loop agent (Claude Code / Codex) 가 단일 파일 mutation + grep metric 만으로
연구를 진행하도록. GEODE 의 outer-loop 도 같은 constraint 가 통과하면 self-
improving 의 cost frontier 가 단순해진다. 이 fork 는 GEODE 안에 같은 형식
의 단일 mutation file (`train.py`) + read-only harness (`prepare.py`) 를
배치해 동일한 loop pattern 을 재사용한다.

## How it works

원본과 동일한 3-file 구조:

- **`prepare.py`** — Petri seed pool + AlphaEval 19-dim rubric 의 존재/형식
  sanity check + audit harness self-test. Agent **수정 X**.
- **`train.py`** — GEODE wrapper system prompt sections (mutation target) +
  `geode audit` subprocess invocation + AlphaEval fitness extraction. **Agent
  가 수정하는 단일 file** — system prompt section 의 wording / 추가 / 삭제 /
  순서 변경 모두 fair game.
- **`program.md`** — agent 의 instruction. Human 이 수정.

원본의 fixed 5-min wall-clock budget → audit budget (default ~5 min, ChatGPT
Plus quota / Anthropic API 비용 cap 으로 제어). Metric `val_bpb` → AlphaEval
fitness (5-axis aggregate, **higher = better**). `results.tsv` 도 column 만
교체 (commit / fitness / hallucination_mean / status / description).

`WRAPPER_PROMPT_SECTIONS` 의 mutation 은 audit invoke 시
`GEODE_WRAPPER_OVERRIDE` env var (`autoresearch/state/wrapper-override.json`)
로 GEODE runtime 의 `PromptAssembler` Phase 0 에 전달되어 system prompt 의
base 를 대체. `--dry-run` 은 cost 없는 plumbing 검증 mode.

## Quick start

요구사항: `uv`, GEODE repo 의 `[audit]` extra (`inspect_ai`, `inspect_petri`),
`~/.codex/auth.json` (ChatGPT Plus OAuth) 또는 `ANTHROPIC_API_KEY`.

```bash
# 1. GEODE repo 의 dependencies + audit extras
uv sync --extra audit

# 2. Seed pool + rubric sanity check (one-time)
uv run python autoresearch/prepare.py

# 3. Real audit experiment (~5 min, uses LLM quota / API budget)
uv run python autoresearch/train.py

# 3-alt. Plumbing-only smoke (no quota)
uv run python autoresearch/train.py --dry-run
```

stdout 의 마지막 `---` block 에 grep-friendly metric.

## Running the agent

`program.md` 를 컨텍스트로 둔 채 outer-loop agent 를 띄움. 원본의 prompt 를
Petri 용으로 교체:

```
program.md 를 읽고 새 experiment 시작. 본 PR 의 baseline 부터 잡아.
```

`program.md` 가 lightweight skill — agent 가 mutation 후보 / fitness 해석 /
loop 종료 조건 을 모두 거기서 읽음.

## Project structure

```
autoresearch/
├── prepare.py     — seed pool + rubric sanity check (do not modify)
├── train.py       — wrapper prompt sections + audit invoke (agent modifies)
├── program.md     — agent instructions (human modifies)
├── README.md      — this file
└── state/         — runtime artifact (gitignored: results.tsv + audit_logs/)
```

## Design choices (원본과 동일)

- **Single file to modify.** Agent 는 `train.py` 만 수정. mutation 의 scope
  upper-bound 가 명확해 diff 가 의미를 가짐.
- **Fixed budget.** 1 audit 의 wall-clock ≈ 5 min. 모든 hypothesis 가 같은
  budget — 비교 공정. 시간당 ~12 experiment, 하룻밤 ~100.
- **Self-contained.** 외부 dependency 추가 X. GEODE pyproject 의 `[audit]`
  extra 만으로 충분.
- **Git as optimizer.** branch tip = best wrapper, commit = experiment,
  reset = discarded hypothesis.

## Source

- Karpathy autoresearch: https://github.com/karpathy/autoresearch (228791f)
- Local reference clone: `~/workspace/autoresearch`
- GEODE outer-loop spec (older 6-module stub, replaced by this fork):
  `docs/architecture/autoresearch.md`
- Petri evidence (gen 0 fitness signal):
  `docs/audits/2026-05-15-petri-insights.md` +
  `docs/audits/2026-05-15-autoresearch-gen0-plan.md`

## License

원본 MIT. 본 fork 는 GEODE repo 의 license 를 따름.
