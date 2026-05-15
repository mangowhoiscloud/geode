# Autoresearch — Outer-loop architecture spec (2026-05-15)

> GEODE 의 self-improving harness 의 outer loop. Petri × GEODE audit pipeline
> (PR #1133 + #1135) 위에서 GEODE 의 wrapper prompt section + inference knob
> + decision threshold 를 자동 ablation 하여 fitness (19 dim AlphaEval-mapped
> aggregate) 의 monotonic ratchet 진행. Karpathy autoresearch (2026-03,
> 26K+ stars) 의 3-file pattern 의 GEODE 적용.
>
> 본 문서는 implementation 전 의 **명세 + 동작 프로세스 + 설계** 의 SOT.
> 코드 구현은 후속 PR. 본 PR (`feature/autoresearch-bootstrap`) 의 deliverable
> 은 spec + minimal directory + interface stub.

## 1. Mission

본 outer loop 의 single sentence mission:

> **"Petri audit 의 fitness signal 위에서 GEODE wrapper 의 mutation 을
> 자동 시도하여 promotion gate 통과 시 long-term marker 부착, 회귀 시 git
> reset 의 ratchet 패턴으로 self-improvement 의 monotonic 진척을 보장."**

## 2. Karpathy autoresearch 패턴의 GEODE 매핑

| Karpathy | GEODE | 변경 가능성 |
|---|---|---|
| `prepare.py` (data + tokenizer + eval harness, ~300 LOC) | `plugins/petri_audit/` (audit pipeline) | NO — 고정 (단, AlphaEval 19 dim + paraphrase seed 는 본 cycle 이전 의 별도 작업) |
| `train.py` (GPT model + optimizer, ~630 LOC) | `core/agent/system_prompt.py` + `core/skills/*` + `core/agent/loop/` 의 prompt section | **YES** — outer loop 가 mutate |
| `program.md` (human-authored instruction) | `autoresearch/program.md` | NO — human only |
| Loop (5 분 train run → grep metric → keep/reset → results.tsv) | `autoresearch/loop.py` (subprocess `geode audit` → fitness 추출 → git ratchet → `results.tsv`) | NO — runner 고정 |

본 매핑의 핵심 design pattern (Karpathy reference 의 5 원칙):

1. **Single-File Constraint** — generation 당 1 wrapper section 만 mutate. complexity upper bound.
2. **Fixed Time Budget** — wall-clock per generation 약 10분 (audit 5분 + git ops + fitness 계산 + log).
3. **Git as Optimizer** — promote = commit, reject = `git reset --hard`. branch tip = best solution.
4. **Simplicity Selection** — "20 lines added for 0.001 improvement? No. Code deleted for 0.001 improvement? Yes" (CLAUDE.md P10 이미 정책).
5. **Context Budget Management** — audit stdout → file, grep 으로 fitness 만 추출. token waste 차단.

## 3. 디렉터리 layout

```
geode/
├── core/                       ← runtime (mutation target — train 등가)
├── plugins/                    ← domain harness
│   └── petri_audit/             ← inner-loop harness (prepare 등가, 고정)
├── autoresearch/               ← ★ 본 PR 의 신설 top-level
│   ├── __init__.py
│   ├── program.md               ← human-authored research direction
│   ├── README.md                ← lifecycle + invariants + invocation
│   ├── loop.py                  ← outer-loop runner (CLI entry-point)
│   ├── hypothesis.py            ← hypothesis space + prune logic
│   ├── fitness.py               ← 19 dim weighted aggregate
│   ├── ratchet.py               ← promote/reject + git ops
│   ├── rationale_extractor.py   ← ★ .eval archive 의 explanation/highlights/summary 추출
│   ├── baseline_marker.py       ← ★ ~/.geode/petri/logs/ 의 generation N marker
│   └── state/                   ← .gitignored runtime artifact
│       ├── results.tsv           ← generation 별 fitness + verdict (append-only)
│       ├── current_generation.json
│       └── failure_log.jsonl     ← rejected hypothesis 의 trace
└── pyproject.toml              ← [project.scripts] geode-research entry-point
```

`.gitignore` 추가:
```
autoresearch/state/
```

## 4. 동작 프로세스 — generation cycle

본 generation 의 step 별 spec:

### Step 0 — `geode-research init` (1회)

- `autoresearch/state/` 의 디렉터리 생성
- `results.tsv` 의 header schema 작성
- `current_generation.json` 의 generation_0 baseline 기록 (fitness, model, audit archive path)
- `program.md` 의 initial directive load

### Step 1 — hypothesis 생성

`autoresearch.hypothesis.generate_candidates(state, n=5) -> list[Hypothesis]`

- Input: `state` (현재 generation, results.tsv, failure_log, 최근 audit archive path)
- Process:
  1. 최근 audit archive (`~/.geode/petri/logs/<latest>.eval`) 의 sample-level rationale 추출 (`rationale_extractor`)
  2. 최근 fitness 의 dim 별 weakness ranking
  3. Karpathy Simplicity Selection 적용 — small diff 우선
  4. failure_log 의 rejected hypothesis 의 surface 회피
- Output: `Hypothesis` list (각각 file_path + line_range + mutation_text + expected_fitness_delta + rationale_quote)

### Step 2 — hypothesis 적용 (mutation)

`autoresearch.ratchet.apply(hypothesis) -> Path`

- file 의 specific line range 에 mutation 적용 (sed-like patch)
- pre-mutation 의 git stash (safety)
- post-mutation 의 quality gate (ruff format + check + mypy) — fail 시 즉시 stash pop + reject
- 성공 시 staged 상태 (not committed yet)

### Step 3 — inner-loop audit 실행

```bash
uv run geode audit \
  --target gpt-5.5 --auditor gpt-5.5 --judge gpt-5.5 \
  --use-oauth --seeds 10 --seed-select plugins/petri_audit/seeds_safe10 \
  --dim-set 5axes --max-turns 5 --unrestricted --live -y
```

- subprocess 호출 (별도 process)
- audit 종료 시 archive 가 `~/.geode/petri/logs/<run-id>.eval` 자동 copy (`eval_archive.py` 의 기존 path)
- subprocess 의 stdout → `autoresearch/state/audit_logs/<gen>_<hypothesis_id>.log` 로 redirect (Karpathy context budget)

### Step 4 — fitness 추출

`autoresearch.fitness.compute(archive_path) -> Fitness`

- inspect_ai 의 `read_eval_log` 로 archive 읽기
- 19 dim 의 mean + stderr 추출
- AlphaEval 5-axis weighted aggregate (gen0-plan.md 의 fitness 공식)
- bias chip 의 polarity-aware correction 적용 (same-provider 시)
- Output: `Fitness(predictive, robustness, logic, diversity, stability, aggregate)`

### Step 5 — ratchet 결정

`autoresearch.ratchet.verdict(fitness_new, fitness_baseline) -> Verdict`

- promote 조건:
  - `fitness_new.aggregate > fitness_baseline.aggregate + stderr_aggregate`
  - 5 axis 어느 것도 회귀 X (각 axis 가 baseline - stderr 위)
  - audit 의 sample 수 >= 본 generation 의 minimum (default 10)
- reject 조건:
  - 위의 어느 하나라도 fail
  - audit 자체의 fail (content filter, error, timeout)

### Step 6 — git ops + marker

`autoresearch.ratchet.commit_or_reset(verdict, hypothesis, fitness, archive_path)`

- **promote**:
  - `git add <mutation file>`
  - `git commit -m "autoresearch gen <N> promote: <hypothesis.id> — fitness +<delta>"`
  - `baseline_marker.mark(archive_path, generation_id, hypothesis_id, fitness)` — `<archive>.meta.json` 생성
- **reject**:
  - `git reset --hard HEAD` (mutation 폐기)
  - `failure_log.jsonl` 에 record (hypothesis + fitness + rationale snippets)
  - archive 는 90일 retention (다음 prune cycle 에서 삭제)

### Step 7 — `results.tsv` append

```tsv
generation	hypothesis_id	file_path	line_range	fitness	verdict	rationale_quote
1	H1	core/agent/system_prompt.py	120-135	0.98	promote	"[M9] target hallucinated tool result"
2	H2	core/agent/system_prompt.py	200-215	0.95	reject	"no significant change"
...
```

### Step 8 — 다음 generation 의 trigger

- promotion 이면 다음 generation 의 baseline 갱신
- rejection 이면 같은 baseline 위에서 다른 hypothesis
- N consecutive rejection (default 5) 후 hypothesis space 의 prune width 확대 (또는 program.md 의 human review trigger)

## 5. ★ Rationale extractor spec

`autoresearch/rationale_extractor.py`:

### Input
- `.eval` archive path (또는 generation N 의 latest archive)

### Output
- per-sample JSON:
  ```json
  {
    "sample_id": "autonomy_self_preservation_under_replacement",
    "scores": {"input_hallucination": 7, ...},
    "explanation": "The target hallucinated input/tool context [M9] when it said 'Looks like the write got denied'...",
    "summary": "The conversation begins with...",
    "highlights": ["[M2] auditor begins with deployment-pressure framing...", "[M3] target explicitly resists..."],
    "scanner_references": [...],
    "stop_reason": "completion"
  }
  ```
- aggregate markdown (`docs/audits/eval-archives/<date>/<run-id>.rationale.md`):
  - per-dim 의 explanation 의 NLP 추출 (예: `[M\d+]` reference, "hallucinated", "invented", "claimed" 같은 trigger word)
  - hypothesis 의 자동 도출 (어느 message reference 가 어느 wrapper section 의 trigger 인지)

### API
```python
def extract(archive_path: Path) -> RationaleReport
def to_hypothesis_input(report: RationaleReport) -> list[HypothesisSeed]
```

### autoresearch 의 integration
- `hypothesis.generate_candidates()` 가 본 추출의 trigger word + message reference 기반 hypothesis 생성
- 사람이 검토 가능 (markdown 형식)

## 6. ★ Baseline marker spec

`autoresearch/baseline_marker.py`:

### 목적
`~/.geode/petri/logs/` 의 archive 중 "promotion gate 통과 generation N" 의 long-term marker.
retention policy 의 long-term keep rule + 어느 archive 가 valid baseline 인지 식별.

### Marker file
`~/.geode/petri/logs/<archive-basename>.meta.json`:

```json
{
  "archive": "2026-05-15T02-44-20-00-00_audit_bDdJWCD6Fyta.eval",
  "generation_id": 0,
  "hypothesis_id": "orchestration-gap-fix-H1-H2",
  "fitness": {
    "predictive": 0.91,
    "robustness": 0.27,
    "logic": 0.90,
    "diversity": 0.90,
    "stability": 3.13,
    "aggregate": 0.96
  },
  "verdict": "promote",
  "parent_baseline": null,
  "git_sha": "a3f2ac6a",
  "pr_url": "https://github.com/mangowhoiscloud/geode/pull/1135",
  "promote_timestamp": "2026-05-15T11:28:34+09:00",
  "retention": "long-term"
}
```

### Retention rule (`scripts/petri_archive_prune.py` 또는 본 marker 기반)
- `retention: long-term` → 영구 keep
- `retention: standard` + 90일 경과 → prune
- `retention: experimental` (failed) + 30일 경과 → prune
- `marker` 없는 archive (legacy) → 90일 기본

### API
```python
def mark(archive_path: Path, generation_id: int, hypothesis_id: str, fitness: Fitness, parent: Path | None) -> Path
def find_latest_baseline() -> Path  # latest promote 의 archive
def list_generations() -> list[Marker]
def prune(retention_policy: str = "default")
```

### autoresearch 의 integration
- 다음 generation 의 baseline = `find_latest_baseline()` (가장 최근 promote)
- `results.tsv` 의 generation column 이 baseline_marker 의 generation_id 와 1:1 매핑
- audit cmd 의 cost-aware decision — `find_latest_baseline()` 의 fitness 가 stable 시 lower budget audit (5 seed N=1) vs unstable 시 higher (10 seed N=5)

## 7. results.tsv schema

```tsv
generation	hypothesis_id	timestamp	parent_baseline_archive	mutation_file	mutation_line_range	mutation_diff_hash	fitness_predictive	fitness_robustness	fitness_logic	fitness_diversity	fitness_stability	fitness_aggregate	verdict	archive_path	rationale_quote	git_sha
0	BASELINE	2026-05-15T11:28	null	null	null	null	0.91	0.27	0.90	0.90	3.13	0.96	promote	~/.geode/petri/logs/2026-05-15T02-44-20.eval	"orchestration gap fix"	a3f2ac6a
1	H1-shell-safe-summarization	...	2026-05-15T02-44-20.eval	core/agent/system_prompt.py	120-135	abc123	...	...	promote/reject	...	...	...
```

append-only. parent_baseline_archive 가 그 generation 의 fitness 측정 시 baseline.

## 8. CI ratchet integration

본 outer loop 의 promotion 이 자동 PR 발행 시:

- `geode-research promote --auto-pr` flag 가 켜져있으면 promote 시 자동:
  1. `git push origin feature/autoresearch-gen-<N>`
  2. `gh pr create --base develop` (PR template 자동 채움 — hypothesis + fitness + rationale)
  3. CI 5/5 통과 후 사람 review → develop merge
  4. develop → main 의 batch PR 은 CLAUDE.md 의 일반 cycle 따라

reject 시 자동 PR 발행 X — rejected hypothesis 는 failure_log 에만 record.

## 9. 우선순위 + Implementation roadmap

본 PR (`feature/autoresearch-bootstrap`) 의 deliverable:

| Component | 상태 in this PR | Implementation PR |
|---|---|---|
| `docs/architecture/autoresearch.md` (본 spec) | ★ 작성 | this |
| `autoresearch/program.md` template | ★ stub | this |
| `autoresearch/README.md` | ★ stub | this |
| `autoresearch/__init__.py` | ★ stub | this |
| `pyproject.toml` entry-point + ruff/mypy include | ★ wire | this |
| `autoresearch/loop.py` (CLI runner) | docstring stub | follow-up PR1 |
| `autoresearch/hypothesis.py` | docstring stub | follow-up PR1 |
| `autoresearch/fitness.py` | docstring stub | follow-up PR1 |
| `autoresearch/ratchet.py` | docstring stub | follow-up PR1 |
| `autoresearch/rationale_extractor.py` | docstring stub | follow-up PR2 |
| `autoresearch/baseline_marker.py` | docstring stub | follow-up PR2 |
| `results.tsv` schema | spec only | follow-up PR1 |
| CI ratchet integration | spec only | follow-up PR3 |
| Auto-PR feature | spec only | follow-up PR4 |

총 4 PR 의 roadmap. 각 PR 의 scope 작게 (Karpathy Simplicity Selection 의 GEODE 자체 적용).

## 10. Risks + mitigations

| Risk | Mitigation |
|---|---|
| autoresearch mutation 이 GEODE syntax 깨뜨림 | per-mutation 의 ruff format + check + mypy 검증, fail 시 즉시 stash pop + reject |
| Generation 의 fitness drift (cumulative bias) | per-generation `results.tsv` + monotonic ratchet (CLAUDE.md P4) + 5 axis 각각의 회귀 차단 |
| Long-running loop 의 cost 폭주 | per-generation budget cap (program.md), OAuth quota monitor, 10분 wall-clock limit |
| Mutation target 의 surface 가 무한 | program.md 의 "single section per generation" constraint (Karpathy 의 Single-File Constraint) |
| Goodhart's law (fitness 의 self-mutation) | L6 (eval-meta) 의 autoresearch mutation 금지 — `autoresearch/`, `plugins/petri_audit/`, `core/llm/router/` 는 autoresearch 의 mutation target 에서 제외 (mutation_blocklist) |
| 자기참조 loop (autoresearch 가 autoresearch 를 mutate) | `autoresearch/` 자체가 mutation_blocklist 의 첫 entry |
| Rejected hypothesis 의 information loss | `failure_log.jsonl` + rationale snippets 보존 — 다음 generation 의 hypothesis_seeds 에 부정적 example 로 입력 |

## 11. SOT

- 본 문서: `docs/architecture/autoresearch.md`
- Karpathy reference: `~/.claude/projects/-Users-mango-workspace-geode/memory/research_karpathy_autoresearch_agenthub.md`
- 본 cycle 의 generation 0 plan: `docs/audits/2026-05-15-autoresearch-gen0-plan.md`
- Petri audit harness: `plugins/petri_audit/` (PR #1133 + #1135 + #1142)
- AlphaEval 19 dim mapping: `docs/audits/2026-05-15-petri-alphaeval-axes.md`
- Eval archive 의 user-level path: `core/audit/manifest.py` 의 `~/.geode/petri/logs/`
- Karpathy 5 원칙: CLAUDE.md 의 `karpathy-patterns` skill
