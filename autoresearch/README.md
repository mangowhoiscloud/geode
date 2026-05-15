# autoresearch — GEODE self-improvement outer loop

GEODE 의 self-improving harness 의 outer loop. Petri × GEODE audit
pipeline 위에서 GEODE wrapper prompt 의 mutation 을 자동 시도하고,
fitness signal 의 monotonic ratchet 으로 self-improvement 의
진척을 보장.

## Quick start

```bash
# Initialize
uv run geode-research init

# Generation 1 — 1 hypothesis
uv run geode-research step --program autoresearch/program.md

# Continuous loop until termination
uv run geode-research loop --program autoresearch/program.md --max-gen 50
```

## Invariants

1. **Single-File Constraint** — generation 당 1 wrapper section 만 변경
2. **Git as Optimizer** — promote = commit, reject = git reset --hard
3. **Fixed Time Budget** — generation 당 wall-clock 10분
4. **mutation_blocklist** — autoresearch/, plugins/petri_audit/, core/llm/router/ 등의 eval-meta 는 변경 금지
5. **subprocess isolation** — outer loop 은 GEODE 를 subprocess 로만 호출 (in-process import 금지)

## Lifecycle

```
[Step 0] geode-research init
   ↓
[Step 1] hypothesis 생성 (latest archive + rationale 추출)
   ↓
[Step 2] mutation 적용 (file:line edit + quality gate)
   ↓
[Step 3] inner-loop audit (uv run geode audit ...)
   ↓
[Step 4] fitness 추출 (.eval archive 의 19 dim → AlphaEval 5 axis)
   ↓
[Step 5] ratchet verdict (promote/reject)
   ↓
[Step 6] git ops + baseline_marker (promote 시) OR git reset (reject 시)
   ↓
[Step 7] results.tsv append
   ↓
[Step 8] 다음 generation
```

## File 역할

| File | Role |
|---|---|
| `program.md` | human direction (mutation target / blocklist / budget) |
| `loop.py` | CLI runner (entry-point geode-research) |
| `hypothesis.py` | hypothesis 생성 + prune |
| `fitness.py` | 19 dim → 5 axis aggregate |
| `ratchet.py` | promote/reject + git ops |
| `rationale_extractor.py` | .eval archive 의 explanation/highlights/summary 추출 |
| `baseline_marker.py` | ~/.geode/petri/logs/ 의 generation N marker |
| `state/` | runtime artifact (gitignored) — results.tsv + failure_log + audit_logs |

## Spec

본 architecture 의 자세한 spec: `docs/architecture/autoresearch.md`.
