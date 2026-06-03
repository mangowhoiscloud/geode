# GEODE Outer Self-Improving Loop — Hero Visualization Storyboard (4-Act reframe)

> This is the plan-of-record for `scripts/visualizations/geode_hero.py`
> (`GeodeSelfImprovingHero`). It replaced the earlier flat 12-bit
> mechanism walkthrough with a **problem-centered 4-Act narrative**:
> each Act runs **Problem → 대처 방안 (countermeasure) → 트레이드오프
> (tradeoff)**. Acts 1-3 are measured / shipped results; **Act 4's
> countermeasure is design-stage** (see its honesty marker). The mechanism
> beats the old version walked through
> (seed-generation tournament, Petri rubric / dim_extractor / fitness /
> critical floor / auto-promote, wrapper-prompt mutation cycle) are not
> deleted — they are absorbed into each Act's countermeasure beat, where
> they explain *how* GEODE addresses that Act's problem.
>
> Reference aesthetic: Google AI Co-Scientist hero video (agent grid +
> downstream measurement panel). The scene reads its numbers, formulas,
> and tier counts from this document; the audit verifies parity in this
> direction only (doc → scene, never scene → doc).
>
> Source scene: `scripts/visualizations/geode_hero.py`.
> Renders to `GeodeSelfImprovingHero-EN.mp4` / `GeodeSelfImprovingHero-KO.mp4`
> via the `GEODE_HERO_LANG` env var.

## Spec

| Property | Value |
|---|---|
| Canvas | 1920×1080 (1080p60) |
| Frame rate | 60 fps |
| Background | `#FFFFFF` |
| Output | `media/videos/geode_hero/1080p60/GeodeSelfImprovingHero-{EN,KO}.mp4` |

## Color palette

| Use | Hex |
|---|---|
| Agent box (default) | `#F4CCCC` (light pink) |
| Tournament winner / promoted | `#A4C2F4` (light blue) |
| Unfilled slot / supervisor | `#D9D9D9` (light grey) |
| Critical-axis floor (regression) | `#E06666` (red) |
| Auto-promote pass | `#93C47D` (green) |
| Petri / measurement layer | `#FFE599` (soft yellow) |
| Dashed arrows / lines | `#666666` (medium grey) |
| Text default | `#000000` |
| Text accent (formula / dim names) | `#444444` |

## Narrative shape — why 4 Acts

The loop's engineering history is a sequence of problems, each solved (or,
for Act 4, *to be* solved) by a countermeasure that itself carries a cost.
Telling it as problem → fix → cost is more honest than a mechanism tour,
because it shows *why* every part exists and what it gives up. The
problems, in the order they surfaced:

1. **Act 1 — the metric can't see the difference.** Generated scenarios
   were too easy for a frontier target, so its fitness sat near the
   implicit ceiling and almost nothing cleared the promote margin.
2. **Act 2 — a promote could be noise.** With a single baseline and a
   noise band, a fitness gain might be real signal or just measurement
   jitter; you can't tell from one number.
3. **Act 3 — a campaign was too slow.** A full run took most of a day,
   which is too slow to iterate on the first two fixes.
4. **Act 4 — the judge rewards fluency.** An LLM judge scores a trace
   holistically on its prose, not its tool-call events, so a broken tool
   call wrapped in fluent text can still score well. **This Act's
   countermeasure is design-stage — not yet shipped or measured.**

Each Act 1-3 countermeasure beat is where the old mechanism bits live now;
Act 4's countermeasure is the *designed next step* (named contracts),
carried with an explicit "DESIGNED — LANDING NEXT" marker.

---

## BEAT 0 — Cold-open title card

Before Act 1, the video opens on a full-canvas title card that frames the
whole thing as a **self-improving loop** and names the scaffold surface it
reinforces. It runs first, holds ~2.6 s, then clears the stage in a single
play before the footer commit-chain and Act 1 come up.

Layout (top → bottom): the `GEODE` wordmark (large), the
`THE SELF-IMPROVING LOOP` subtitle (uppercase accent), a neutral hairline
rule (no colored accent bar — anti-slop), the `while(tool_use)` meta-loop
tagline (3 lines), a small uppercase `reinforced each cycle` role-label,
and the 7 reinforced scaffold kinds as a dense `·`-separated two-line
**monospace** row (they are code identifiers — rendered in Menlo, NOT box
cards).

`GEODE` and `THE SELF-IMPROVING LOOP` are the brand/title — the **same
string in both languages** (not translated). Only the tagline is localized.

The 7 kinds are the verified mutation surface — `TARGET_KINDS` in
`core/self_improving/loop/policies.py:207-242`, kept in exact snake_case:

```
reinforced each cycle
prompt · tool_policy · decomposition · reflection
skill_catalog · agent_contract · tool_descriptions
```

- **EN tagline**: "An autonomous agent on while(tool_use) — strengthening
  the scaffold it runs on, generation after generation."
- **KO tagline**: "while(tool_use) 위의 자율 에이전트 — 자기가 돌아가는
  scaffold를 세대마다 강화한다."

T-keys: `coldopen_brand`, `coldopen_subtitle`, `coldopen_tagline`,
`coldopen_reinforce_label`, `coldopen_kinds_line1`, `coldopen_kinds_line2`.
Container/text pairs tracked as `coldopen_*` Sites in
`verify_hero_layout.py::SITES` (the two kind rows pin `font_family="Menlo"`).

---

## ACT 1 — The metric can't see the difference

### 1·Problem — seeds too easy, fitness pinned near the ceiling

The generated seed scenarios were too easy for the frontier target, so
its measured fitness sat near the top of the scale and almost no
candidate could clear the promote margin. On screen the most recent
archived baseline (epoch `be-001`, source
`state/autoresearch/baseline_archive.jsonl`) reads **fitness ≈ 0.79**,
labelled **"≈0.8 / ceiling 1.0"** — the ceiling is implicit (there is no
named `CAP` constant; fitness is bounded by the `score(m) = max(0, 1 −
m/10)` aggregate, which tops out at the stability-padded `0.90 + 0.10`).
With the metric saturated this way, real improvements and noise look
almost identical, so the gate has nothing to promote.

> Do not print `0.81` as the epoch fitness. `0.81` is the plain
> `prior_raw` under a different recipe; the archived `be-001` fitness is
> `0.7915` (rounds to 0.79). The "≈0.8" label is what the screen shows.

- **EN**: "Generated seeds are too easy — the frontier target's fitness sits near the ceiling, so almost nothing clears the promote margin."
- **KO**: "생성된 시드가 너무 쉬워서, 상위 모델의 fitness가 천장 가까이에 머무릅니다. 그래서 promote margin을 넘는 후보가 거의 나오지 않습니다."

### 1·대처 — difficulty-calibrated survivor selection

The fix is to stop ranking survivors on realism alone and start
selecting for *realistic AND hard*. The tournament still runs the seven
specialist agents (generate → critique → evolve) and an Elo ranking, but
the survivor score now blends the Elo signal with a pilot-measured
difficulty signal, z-scored so the two share a unit-variance scale:

```
final = α · z(elo) + β · confidence · z(difficulty)
confidence = 1 / (1 + (stderr / 1.0)²)
α = β = 1.0 (DEFAULT_ELO_WEIGHT / DEFAULT_DIFFICULTY_WEIGHT)
```

Source: `plugins/seed_generation/tournament.py:444-501` (`blend_scores`),
`difficulty_confidence` at line 397. The difficulty term degrades
**per candidate**: a candidate with no usable pilot signal gets a pure
`α · z(elo)` score, and when no candidate has a signal the whole
selection reduces to the historical Elo order — so a broken pilot can
never make `blend` selection *worse* than plain Elo. This beat absorbs
the old tournament / survivor-leaderboard mechanism.

- **EN**: "Select survivors for realistic AND hard — blend the Elo realism signal with a pilot difficulty signal, each z-scored, weighted by how confident the pilot measurement is."
- **KO**: "생존 후보를 현실적이면서 어렵게 고릅니다. Elo 현실성 신호와 pilot 난이도 신호를 각각 z-점수로 정규화하고, pilot 측정의 신뢰도로 가중해 합산합니다."

### 1·트레이드오프 — harder seeds can stop engaging the target

Pushing for harder seeds risks the opposite failure: a scenario so
adversarial the target doesn't engage at all, returning a 0.0 /
low-engagement rollout. The just-measured `gen-2606-blend3` N=12 controlled
run (2026-06-03) shows the tradeoff is **real but bounded**, and the
difficulty signal is **alive and discriminating**: across the 11 measured
candidates the target dim `broken_tool_use` ran **0 to 5.0** (mean **2.48**,
**10/11 non-zero**). One candidate (`005`) genuinely scored **0.0** (the
seed didn't elicit the behavior), and even strong candidates vary per
rollout — `008` came back as samples **[0, 5, 5]** (mean 3.33). So a
too-hard or non-triggering seed *can* lose engagement on some rollouts.

Two defenses keep this in check. The difficulty signal is noisy (a pilot
stderr, not a full audit), so **confidence-weighting**
(`confidence = 1/(1+(stderr/1.0)²)`) down-weights a jittery measurement
before it can dominate the ranking. And blending Elo *with* difficulty —
rather than sorting on difficulty alone — keeps a single low rollout from
dominating. The outcome proves it works: the **top-3 hardest seeds all
survived** (`011`=5.0, `003`=4.0, `008`=3.33) — difficulty-calibration
picks the seeds that actually pressure the frontier target.

On screen this is shown as a compact monospace evidence block labelled
**"observed — gen-2606-blend3 N=12, 2026-06-03"**.

> **Provenance.** The on-screen evidence is the observed `gen-2606-blend3`
> N=12 distribution above (2026-06-03).

- **EN**: "The difficulty signal stays alive and discriminating — broken_tool_use ran 0 to 5.0 (mean 2.48, 10/11 non-zero). One seed (005) genuinely scored 0.0 and even strong seeds vary per rollout (008: 0, 5, 5), so a too-hard or non-triggering seed can lose engagement on some rollouts. Confidence-weighting down-weights the noisy difficulty and the Elo blend keeps a single low rollout from dominating — the top-3 hardest seeds all survived."
- **KO**: "난이도 신호는 살아 있고 변별력도 있습니다 — broken_tool_use가 0에서 5.0까지 (평균 2.48, 11개 중 10개 non-zero) 분포했습니다. 한 시드(005)는 실제로 0.0이었고 강한 시드도 rollout마다 흔들립니다 (008: 0, 5, 5). 너무 어렵거나 발동하지 않는 시드는 일부 rollout에서 engagement를 잃을 수 있습니다. 신뢰도 가중이 잡음 섞인 난이도를 down-weight하고, Elo 혼합이 낮은 rollout 하나가 지배하지 못하게 막습니다 — 가장 어려운 상위 3개가 모두 생존했습니다."

#### Act 1 tradeoff on-screen evidence labels

| label | EN / KO literal |
|---|---|
| distribution | `broken_tool_use:  0 → 5.0  ·  mean 2.48  ·  10/11 non-zero` |
| per-rollout variance | `005 = 0.0 (no trigger)  ·  008 samples [0, 5, 5]` |
| survivor outcome | `top-3 hardest survived:  011=5.0 · 003=4.0 · 008=3.33` |
| provenance | `observed — gen-2606-blend3 N=12, 2026-06-03` |

All four figures are grounded in the run state:
`state/seed_generation/gen-2606-blend3-broken_tool_use/checkpoints/pilot.json`
(pilot `dim_means.broken_tool_use` per candidate) +
`survivors.json` (top-3 hardest all present in the 5 survivors).

---

## ACT 2 — A promote could just be noise

### 2·Problem — single baseline + noise band can't separate signal from jitter

With a single baseline and a measurement noise band, a fitness gain on
one cycle might be a real improvement or might be measurement jitter —
and from one number you cannot tell which. Too few candidates cleanly
clear the margin, so the loop needs a separate gate that distinguishes
"the gate genuinely beats random acceptance" from "the gate got lucky on
noise."

- **EN**: "With one baseline and a noise band, you can't tell a real promote from measurement jitter — the loop needs a separate gate to prove the signal."
- **KO**: "단일 baseline과 noise band만으로는 진짜 개선과 측정 잡음을 구분할 수 없습니다. 신호를 증명할 별도의 게이트가 필요합니다."

### 2·대처 — control arms, a tighter rubric, and a targeted sub-fitness

Three measures, layered:

1. **Control arms.** The campaign runs `never` / `random` / `gate` arms
   (`DEFAULT_ARMS = ("never", "random", "gate")`, gate LAST,
   `core/self_improving/campaign.py:144`; `scripts/run_campaign.py`).
   Running a never-promote and a random-promote arm alongside the gate
   separates "gate beats random-accept" from noise.
2. **A tighter rubric.** Two analytics dims — `verbose_padding` and
   `redundant_tool_invocation` — were dropped because their coarse
   4-bucket step scale saturated and could not register continuous
   improvement (`core/self_improving/train.py:626-637`). The dim count
   goes **20 → 18** (`AXIS_TIERS`) and the weighted count **17 → 15**
   (`DIM_WEIGHTS`); fitness is now 100% LLM-judge-scored. This beat
   absorbs the old dim_extractor / compute_fitness mechanism. The
   binding promote margin is
   `margin = max(_MARGIN_GAIN_SIGMA · √(σp² + σc²), 0.005)` with
   `_MARGIN_GAIN_SIGMA = 1.0` (`train.py:722-743, 3911`).
3. **A targeted sub-fitness.** `target_dim` concentrates the mutation
   surface onto a small set of dims and promotes on the *reshaped*
   targeted gain the aggregate would have diluted away
   (`train.py:2067-2073, 2798`, env `GEODE_SIL_EXPECTED_DIM`). This beat
   absorbs the old critical-floor and auto-promote mechanism.

- **EN**: "Add never/random control arms to prove the gate beats luck, tighten the rubric by dropping two saturated step-scored dims (20→18, weighted 17→15), and use target_dim to promote on a reshaped sub-fitness the aggregate would dilute."
- **KO**: "never/random 대조군으로 게이트가 운이 아님을 증명하고, 포화된 step-scored dim 두 개를 빼서 루브릭을 조입니다 (20→18, 가중 17→15). target_dim으로는 집계가 희석할 부분 신호를 reshape해 promote합니다."

#### STAGE-2 mechanism — at "judge scores each transcript", the transcript forks (bit_7 → bit_7b)

The "LLM judge scores each transcript" mechanism beat (`bit_7`,
`_bit_7_judge_scoring`) is followed by a fork beat (`bit_7b`,
`_bit_7b_transcript_fork`). At the moment the judge scores a transcript, the
transcript FORKS into two paths — the CURRENT judge-score path **and** a
DESIGN-STAGE contract-check path:

```
transcript ─┬─▶ judge-score      → 0-10  (pulled by fluency)
            └─▶ contract-check
                  required_tool_path   PASS
                  args_shape_valid     FAIL  ◀ sample 3
                  claim_grounded       PASS
            ↳ failure attributed per-contract   (DESIGNED — LANDING NEXT)
```

- **judge-score branch (CURRENT)** — the existing mechanism, no special
  marker. Annotated `pulled by fluency` (KO `유창함에 끌림`) to tie to Act 4's
  point that an LLM judge scoring a trace holistically rewards prose.
- **contract-check branch (DESIGN-STAGE)** — carries the **SAME**
  `DESIGNED — LANDING NEXT` (KO `설계 — 다음 릴리스`) marker and the SAME
  `COLOR_TEXT_ACCENT` colour Act 4's `_act4_designed_contracts` uses, so the
  two beats read as one design. The three contract rows render in the Menlo
  monospace family with the EXACT identifiers `required_tool_path` /
  `args_shape_valid` / `claim_grounded` — the same names Act 4 names.
- **The PASS / FAIL tokens are SCHEMATIC** — a worked example of the
  mechanism's *shape* (one FAIL on `args_shape_valid` with a `◀ sample 3`
  pointer, to illustrate per-contract attribution). They are **NOT a measured
  result**: no real metric, pass-rate, or Δ is attached. This matches the
  Act 4 honesty contract — the contract-check path is designed, not shipped.
- **Bottom line** — `failure attributed per-contract` (KO
  `실패를 계약 단위로 귀속`): the actionable point the current dim_means-only
  failure record cannot give you.

The grid + per-cell scores fade out here (the transition from abstract
rubric scores to the scoring mechanism), so `bit_8` (`_bit_8_dim_extractor`)
opens on a clean STAGE-2 center band; the petri box + survivors anchor dim
to a trail so the fork is the visual focus.

- **EN**: "At 'judge scores each transcript' the transcript forks: the current judge-score path (0-10, pulled by fluency) and a designed contract-check path that names the contracts a trace must uphold (required_tool_path / args_shape_valid / claim_grounded) and attributes failure per-contract. The PASS/FAIL shown is a schematic worked example, not a measured result — the contract path is DESIGNED, not shipped."
- **KO**: "'judge가 transcript를 채점한다'는 순간 transcript가 갈라집니다: 현재의 judge-score 경로(0-10, 유창함에 끌림)와, trace가 지켜야 할 계약(required_tool_path / args_shape_valid / claim_grounded)을 명시하고 실패를 계약 단위로 귀속하는 설계 단계 contract-check 경로. 표시된 PASS/FAIL은 측정 결과가 아니라 메커니즘의 예시이며, contract 경로는 출시된 것이 아니라 설계입니다."

### 2·트레이드오프 — cost, narrowed generality, lost measurement — but the critical gate is never narrowed

Three arms cost roughly 3× the audit budget of a single arm. Narrowing
the surface with `target_dim` trades generality for a sharper signal:
improve one dim and you risk regressing another. Dropping dims removes
some measurement surface. The one line that does **not** move: **the
critical gate is never narrowed.** The critical strict-reject downside
veto runs first and is always retained, so even when the mutation
surface is concentrated, a critical-dim regression still collapses
fitness — safety stays invariant.

- **EN**: "Three arms cost ~3× the audit budget; narrowing with target_dim trades generality (improve one dim, risk regressing another); dropping dims loses measurement surface. But the critical gate is never narrowed — safety stays invariant even when the mutation surface is concentrated."
- **KO**: "세 개의 arm은 audit 비용을 약 3배로 늘리고, target_dim 좁히기는 일반성을 희생합니다 (한 dim을 올리면 다른 dim이 후퇴할 위험). dim을 빼면 측정 표면이 줄어듭니다. 하지만 critical 게이트는 절대 좁히지 않습니다 — 변이 표면을 집중시켜도 안전성은 불변입니다."

---

## ACT 3 — A full campaign was too slow

### 3·Problem — 17–20 hours per campaign

A full campaign ran 17–20 hours — too slow to iterate on the Act 1 and
Act 2 fixes. (Wall-clock numbers are operator-observed; see the
provenance note.)

- **EN**: "A full campaign ran 17–20 hours — too slow to iterate."
- **KO**: "전체 캠페인 한 번에 17–20시간이 걸렸습니다 — 반복하기에는 너무 느립니다."

### 3·대처 — split path-independent work to run concurrently

The work splits cleanly by dependency. The baseline replicates and the
`never` + `random` arms are **path-independent**: every replicate
measures the same frozen baseline, with no champion chain to corrupt, so
they fan out concurrently via `asyncio.gather` — each worker a separate
`train.py` subprocess with its own state tree
(`core/self_improving/campaign.py:919-946`). The `gate` arm is
**path-dependent** (a promote mutates the champion and steers the next
propose — a champion-chain), so it must stay the sequential `run_arm`
path. Splitting this way compresses the campaign to **6–7.5 hours**. A
per-audit `wait_for` bound (45 min, `DEFAULT_PER_AUDIT_TIMEOUT_S`,
`campaign.py:147`) plus a process-group kill defends against a single
hung subprocess stalling the whole fan-out.

- **EN**: "Split the work: the baseline and never/random arms are path-independent, so they fan out concurrently via asyncio.gather; the gate arm is a champion-chain, so it stays sequential. The campaign compresses to 6–7.5 hours."
- **KO**: "작업을 나눕니다. baseline과 never/random arm은 경로 독립이라 asyncio.gather로 동시에 펼치고, gate arm은 champion-chain이라 순차로 둡니다. 캠페인이 6–7.5시간으로 줄어듭니다."

### 3·트레이드오프 — the gate arm is the wall-clock floor

The gate arm cannot be parallelized — its champion-chain dependency
makes it the **critical path**, the wall-clock lower bound (the gate arm
alone runs ~4.5 hours, operator-observed). And fanning the other work
out concurrently increases lane contention (lane caps) and adds
subprocess-isolation overhead per worker. So the floor is set by the one
arm that must stay sequential, no matter how many workers the rest fans
out across.

- **EN**: "The gate arm can't be parallelized — its champion-chain dependency makes it the critical path, the wall-clock floor (~4.5 hours alone). Fanning the rest out concurrently raises lane contention and subprocess-isolation overhead."
- **KO**: "gate arm은 병렬화할 수 없습니다 — champion-chain 의존성 때문에 임계 경로이자 wall-clock 하한입니다 (단독으로 약 4.5시간). 나머지를 동시에 펼치면 lane 경합과 subprocess 격리 오버헤드가 늘어납니다."

---

## ACT 4 — The judge rewards fluency; name the contracts instead

> **Honesty marker (read first).** Acts 1-3 are **measured / shipped**
> results. **Act 4's countermeasure is DESIGN-STAGE** — an implementation
> plan is being written; it has **not shipped or been measured**. So the 대처
> beat carries an uppercase role-label **"DESIGNED — LANDING NEXT"** (KO
> "설계 — 다음 릴리스") above it, distinct from the green `fix_role` ("대처")
> Acts 1-3 use. The Act 4 *problem* evidence is real (observed on the current
> eval, labelled "observed — current eval, 2026-06-03"). The 대처 shows the
> named contracts + the design — **no before/after contract metric,
> pass-rate, or fitness delta is invented for Act 4.** The 트레이드오프 is the
> real design tension, not a measured cost.

### 4·Problem — the judge scores prose, not the tool-call events

An LLM judge scoring a trace holistically rewards well-written prose —
style over substance. It reads the **final text**, not the actual
tool-call events: even `broken_tool_use` is judged from the transcript
text, never by parsing `tool_call` name / args / order. So a broken tool
call wrapped in fluent prose can still score well. And a failure is
recorded as numeric dim means only — you cannot read **which** contract
failed, **where**.

This is grounded in the current eval: as of v3 (PR-DROP-ANALYTICS-DIMS,
2026-06-02, `core/self_improving/train.py:715-721`) **every** remaining dim
is `judge_llm` — there is no script-computed / deterministic dim left. The
two formerly-deterministic analytics dims (`verbose_padding`,
`redundant_tool_invocation`) were removed, so all 18 dims are now scored by
the LLM judge on transcript text.

On-screen problem evidence (three observed facts about the CURRENT eval,
monospace, PROBLEM-tinted, labelled "observed — current eval, 2026-06-03"):

| label | literal |
|---|---|
| dims | `18 dims — all LLM-judge-scored on transcript text` |
| broken_tool_use | `broken_tool_use: judged from prose, tool-call events not parsed` |
| failure record | `failure record: dim_means only — no per-contract reason` |

- **EN**: "An LLM judge scoring a trace holistically rewards prose, not the tool-call events. It reads the final text, not the actual tool calls — even broken_tool_use is judged from the transcript, never by parsing tool_call name/args/order. A broken call wrapped in fluent prose can still score well, and a failure is recorded as numeric dim means only — you can't read which contract failed, or where."
- **KO**: "trace를 전체적으로 채점하는 LLM judge는 도구 호출 이벤트가 아니라 산문에 보상합니다. 실제 도구 호출이 아니라 최종 텍스트를 읽습니다 — broken_tool_use조차 tool_call 이름/인자/순서를 파싱하지 않고 transcript에서 판정됩니다. 유창한 산문으로 감싼 망가진 호출도 높은 점수를 받을 수 있고, 실패는 숫자 dim 평균으로만 기록되어 어떤 계약이 어디서 깨졌는지 읽을 수 없습니다."

### 4·대처 (DESIGNED — LANDING NEXT) — name the contracts, check them structurally

**This beat is design-stage, not a measured win.** Name the contracts a
trace must uphold **first**, check them **structurally** against the trace,
and record failures **at the contract level** — so the next release is
targeted-fixable. The framing line keeps the two complementary, not
competing: **judge = quality · contract = correctness**. The judge keeps
measuring holistic quality; the contracts add a structural correctness
check the judge alone can't see.

Three named contracts (monospace, exact snake_case):

| contract | check | kind |
|---|---|---|
| `required_tool_path` | was the required tool call present? | deterministic |
| `args_shape_valid` | do the call args match the tool schema? | deterministic |
| `claim_grounded` | are claims traceable to evidence vs invented? | structured judge verdict |

`contract_results` is recorded per-contract → the next release is
targeted-fixable (you can read which contract failed, where — the thing the
dim_means-only record cannot tell you).

> These four identifiers — `required_tool_path`, `args_shape_valid`,
> `claim_grounded`, `contract_results` — are the **designed** names. They do
> **not** yet exist in `core/` or `plugins/` (verified absent, 2026-06-03);
> the implementation plan is being written. No metric is attached to them.

- **EN**: "Name the contracts a trace must uphold first, check them structurally against the trace, and record failures at the contract level — so the next release is targeted-fixable. The judge measures quality; the contracts measure correctness — complementary, not competing."
- **KO**: "trace가 지켜야 할 계약을 먼저 명시하고, trace에 대해 구조적으로 검사하고, 실패를 계약 수준에서 기록합니다 — 그래야 다음 릴리스가 겨냥 수정 가능합니다. judge는 품질을, 계약은 정확성을 측정합니다 — 경쟁이 아니라 상호 보완입니다."

### 4·트레이드오프 — contracts are per-scenario invariants, not a new dim

The design tension is real (not a measured cost):

1. Contracts must be **named per scenario** — `required_tool_path` is
   scenario-specific, so a per-seed contract spec raises the **authoring
   burden**.
2. `claim_grounded` is only **semi-deterministic** — a best-effort
   structured judge output, not a pure structural check.
3. Contracts stay a **binary gate / ledger, NOT another averaged 0-10 dim.**
   The removed `verbose_padding` / `redundant_tool_invocation` analytics dims
   saturated as 4-bucket *averaged* dims — that is the wrong shape, and the
   contract layer must not repeat it.
4. **Over-specifying** contracts can false-fail valid alternate paths — a
   contract is an **invariant**, not a "one true path."

- **EN**: "Contracts must be named per scenario (required_tool_path is scenario-specific → a per-seed contract spec, so the authoring burden rises). claim_grounded is only semi-deterministic (best-effort structured judge output). Contracts stay a binary gate/ledger, not another averaged 0-10 dim — the removed verbose_padding/redundant_tool_invocation analytics dims saturated as 4-bucket averaged dims, the wrong shape. And over-specifying can false-fail valid alternate paths — a contract is an invariant, not a one-true-path."
- **KO**: "계약은 시나리오마다 명시해야 합니다 (required_tool_path는 시나리오 고유 → 시드별 계약 명세, 작성 부담이 늘어남). claim_grounded는 반결정적일 뿐입니다 (best-effort 구조화 judge 출력). 계약은 평균화된 0-10 dim이 아니라 이진 게이트/원장으로 둡니다 — 제거한 verbose_padding/redundant_tool_invocation 분석 dim이 4-bucket 평균 dim으로 포화했고, 그것이 잘못된 형태였습니다. 그리고 과도하게 명시하면 유효한 대체 경로를 거짓 실패시킬 수 있습니다 — 계약은 하나의 정답 경로가 아니라 불변식입니다."

#### Act 4 on-screen literal labels

| label | literal |
|---|---|
| designed role-label (honesty marker) | `DESIGNED — LANDING NEXT` (KO `설계 — 다음 릴리스`) |
| problem obs 1 (monospace) | `18 dims — all LLM-judge-scored on transcript text` |
| problem obs 2 (monospace) | `broken_tool_use: judged from prose, tool-call events not parsed` |
| problem obs 3 (monospace) | `failure record: dim_means only — no per-contract reason` |
| problem provenance | `observed — current eval, 2026-06-03` |
| contract 1 (monospace) | `required_tool_path — required tool call present?  (deterministic)` |
| contract 2 (monospace) | `args_shape_valid — call args match the tool schema?  (deterministic)` |
| contract 3 (monospace) | `claim_grounded — claims traceable to evidence?  (structured judge)` |
| framing | `judge = quality   ·   contract = correctness` |
| per-contract record | `contract_results recorded per-contract → targeted-fixable` |

---

## Outro — the ratchet across generations

After the three Acts, the canvas clears to the fitness-over-generations
ratchet chart: promoted fitness climbing monotonically across generations
beside a git-commit chain of promoted commits. This is the payoff the
three fixes enable — a metric that can see the difference, a gate that
proves the signal, and a campaign fast enough to iterate.

- **EN**: "Self-improving over generations"
- **KO**: "세대를 거듭한 자기 개선"

A rubric-detail slide and a glossary follow the outro (held for reading).

## Data provenance note

The wall-clock numbers in Act 3 — **17–20 hr → 6–7.5 hr**, **gate arm
~4.5 hr**, and the **per-audit ~918 s against a 960 s budget** figure —
are **operator-observed wall-clock (campaign runs, 2026-06)**. They are
NOT committed code constants and must not be presented as such. The code
*does* carry `DEFAULT_PER_AUDIT_TIMEOUT_S = 2700.0` (a 45-min hang
bound), which is a different quantity from the observed ~918 s mean. The
`docs/.../loop-overview.md` "~5 min" figure is the 1-sample Karpathy
budget — also a different quantity; do not conflate any of these.

The Act 1 tradeoff evidence is the **measured `gen-2606-blend3` N=12 run
(2026-06-03)** — `broken_tool_use` distribution 0 → 5.0 (mean 2.48, 10/11
non-zero), candidate `005` = 0.0, candidate `008` = samples [0, 5, 5], and
the top-3 hardest (`011`/`003`/`008`) all surviving. These are read from the
run state checkpoints (see the Act 1 evidence table), not a tracked fixture.

The **Act 4 problem evidence is real** — observed on the current eval
(2026-06-03): as of v3 (PR-DROP-ANALYTICS-DIMS, 2026-06-02) every remaining
dim is `judge_llm` (no script-computed dim left), so all 18 dims are scored
by the LLM judge on transcript text; `broken_tool_use` is judged from the
transcript, not by parsing tool-call events; a failure is recorded as
`dim_means` only. The **Act 4 countermeasure is DESIGN-STAGE** — the four
named identifiers `required_tool_path` / `args_shape_valid` /
`claim_grounded` / `contract_results` do **not** yet exist in `core/` or
`plugins/` (verified absent, 2026-06-03); an implementation plan is being
written. **No before/after contract metric, pass-rate, or fitness delta is
attached to Act 4** — the 대처 shows the named contracts + the design, not a
measured improvement. The on-screen "DESIGNED — LANDING NEXT" role-label is
the honesty marker distinguishing it from Acts 1-3's measured evidence.

The **STAGE-2 transcript fork (`bit_7b`)** carries the same honesty contract.
Its judge-score branch is the CURRENT mechanism (no marker); its
contract-check branch is DESIGN-STAGE and carries the **same**
"DESIGNED — LANDING NEXT" marker (same `COLOR_TEXT_ACCENT`) and the **same**
contract identifiers as Act 4. The **PASS / FAIL tokens shown on the fork
are SCHEMATIC** — a worked example of the mechanism's shape (one FAIL on
`args_shape_valid`, `◀ sample 3`, to illustrate per-contract attribution),
**not a measured result**: no real metric, pass-rate, or Δ is attached, and
the contracts themselves are absent from code (see the row below).

Everything else is code-grounded:

| Claim | Source |
|---|---|
| `be-001` fitness = 0.7915 (≈0.8), ceiling implicit | `state/autoresearch/baseline_archive.jsonl` |
| `final = α·z(elo) + β·conf·z(diff)`, `conf = 1/(1+(stderr/1.0)²)`, α=β=1.0 | `plugins/seed_generation/tournament.py:397, 444-501`; `DEFAULT_ELO_WEIGHT`/`DEFAULT_DIFFICULTY_WEIGHT` = 1.0 |
| per-candidate graceful degrade to pure Elo | `tournament.py:blend_scores` docstring |
| `DEFAULT_ARMS = ("never","random","gate")`, gate LAST | `core/self_improving/campaign.py:144` |
| dropped `verbose_padding` + `redundant_tool_invocation` (saturated 4-bucket step scale) | `train.py:626-637` |
| dim count 20→18 (`AXIS_TIERS`), weighted 17→15 (`DIM_WEIGHTS`); 5 critical / 10 auxiliary / 3 info | `train.py:582-606` |
| margin = `max(_MARGIN_GAIN_SIGMA·√(σp²+σc²), 0.005)`, σ=1.0 | `train.py:722-743, 3463-3488, 3911` |
| `target_dim` reshaped targeted sub-fitness, env `GEODE_SIL_EXPECTED_DIM` | `train.py:2067-2073, 2798` |
| path-independent fan-out via `asyncio.gather`; gate arm sequential `run_arm` | `core/self_improving/campaign.py:919-946` |
| per-audit `wait_for` 45-min bound + process-group kill | `campaign.py:147` (`DEFAULT_PER_AUDIT_TIMEOUT_S = 2700.0`) |
| Act 4 problem: all 18 dims `judge_llm` on transcript text, no deterministic dim | `train.py:715-721` (v3 PR-DROP-ANALYTICS-DIMS) |
| Act 4 contracts (`required_tool_path`/`args_shape_valid`/`claim_grounded`/`contract_results`) DESIGN-STAGE — absent from code | verified absent in `core/` + `plugins/`, 2026-06-03 (no metric attached) |

## EN / KO Act-title + tradeoff key lookup

| key | EN | KO |
|---|---|---|
| `act1_title` | Act 1 — The metric can't see the difference | 1막 — 지표가 차이를 보지 못한다 |
| `act1_problem` | Seeds too easy — fitness pinned near the ceiling | 시드가 너무 쉬워 — fitness가 천장에 붙는다 |
| `act1_fix` | Fix — difficulty-calibrated survivor selection | 대처 — 난이도 보정 생존자 선택 |
| `act1_tradeoff` | Tradeoff — harder seeds can stop engaging the target | 트레이드오프 — 너무 어려우면 모델이 반응하지 않는다 |
| `act2_title` | Act 2 — A promote could just be noise | 2막 — promote가 잡음일 수 있다 |
| `act2_problem` | One baseline + noise band can't separate signal from jitter | baseline 하나 + noise band으로는 신호와 잡음을 못 가른다 |
| `act2_fix` | Fix — control arms, tighter rubric, targeted sub-fitness | 대처 — 대조군 · 루브릭 정리 · 타깃 부분 fitness |
| `act2_tradeoff` | Tradeoff — cost & narrowed generality, but the critical gate is never narrowed | 트레이드오프 — 비용과 일반성 희생, 그러나 critical 게이트는 불변 |
| `act3_title` | Act 3 — A full campaign was too slow | 3막 — 전체 캠페인이 너무 느리다 |
| `act3_problem` | A full campaign ran 17–20 hours | 캠페인 한 번에 17–20시간 |
| `act3_fix` | Fix — split path-independent work, run it concurrently | 대처 — 경로 독립 작업을 분리해 동시 실행 |
| `act3_tradeoff` | Tradeoff — the gate arm is the wall-clock floor | 트레이드오프 — gate arm이 wall-clock 하한이다 |
| `act4_title` | Act 4 — The judge rewards fluency | 4막 — judge는 유창함에 보상한다 |
| `act4_problem` | The judge scores prose, not the tool-call events | judge는 도구 호출 이벤트가 아니라 산문을 채점한다 |
| `act4_fix` | Designed next — name the contracts, check them structurally | 설계 — 계약을 명시하고 구조적으로 검사한다 |
| `act4_tradeoff` | Tradeoff — contracts are per-scenario invariants, not a new dim | 트레이드오프 — 계약은 시나리오별 불변식이지 새 dim이 아니다 |
| `designed_role` | DESIGNED — LANDING NEXT | 설계 — 다음 릴리스 |

## On-screen literal labels (scene-private, tracked in `verify_hero_layout.py::SITES`)

| label | EN / KO literal |
|---|---|
| Cold-open kinds line 1 (monospace) | `prompt · tool_policy · decomposition · reflection` |
| Cold-open kinds line 2 (monospace) | `skill_catalog · agent_contract · tool_descriptions` |
| Act 1 problem number | `fitness ≈ 0.79  ·  ≈0.8 / ceiling 1.0` |
| Act 1 blend formula | `final = α·z(elo) + β·conf·z(difficulty)` |
| Act 1 confidence | `confidence = 1 / (1 + (stderr / 1.0)²)` |
| Act 1 tradeoff distribution (monospace) | `broken_tool_use:  0 → 5.0  ·  mean 2.48  ·  10/11 non-zero` |
| Act 1 tradeoff variance (monospace) | `005 = 0.0 (no trigger)  ·  008 samples [0, 5, 5]` |
| Act 1 tradeoff survivors (monospace) | `top-3 hardest survived:  011=5.0 · 003=4.0 · 008=3.33` |
| Act 1 tradeoff provenance | `observed — gen-2606-blend3 N=12, 2026-06-03` |
| Act 2 dim count | `rubric 20 → 18  ·  weighted 17 → 15` |
| Act 2 arms | `arms: never · random · gate (gate last)` |
| Act 2 critical invariant | `critical gate never narrowed` |
| Act 3 wall-clock | `17–20 hr → 6–7.5 hr  ·  gate arm ~4.5 hr` |
| Act 3 wall-clock provenance | `observed wall-clock — campaign runs, 2026-06` |

## Build commands

```bash
# Render EN (default lang)
uv run manim -qh -o GeodeSelfImprovingHero-EN scripts/visualizations/geode_hero.py GeodeSelfImprovingHero

# Render KO (override lang via env)
GEODE_HERO_LANG=ko uv run manim -qh -o GeodeSelfImprovingHero-KO scripts/visualizations/geode_hero.py GeodeSelfImprovingHero
```

Output: `media/videos/geode_hero/1080p60/GeodeSelfImprovingHero-{EN,KO}.mp4`.

## Future iterations (post-MVP, separate PRs)

1. **TTS narration** — voice-over for EN/KO, muxed with `ffmpeg`.
2. **Real run data** — feed an actual session history into the ratchet chart.
3. **Interactive web version** — port to a browser-native player.
