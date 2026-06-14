# Self-improving campaign: quick start

The single front door for running GEODE's self-improving loop. If you have never
run a campaign, start here, then graduate to `campaign-procedure.md` for the full
procedure and `docs/architecture/autoresearch.md` for the design.

What the loop does, and what it does not: each cycle mutates one section of
GEODE's scaffold (the system-prompt sections + policy artifacts that wrap the
base model, never the model weights), audits the scaffolded GEODE with Petri,
folds the per-dim judge scores into a scalar fitness, and either commits the
mutation or reverts the source of truth on a statistically defensible gate. The
loop MEASURES and GATES. It does not promise improvement: a real run can produce
zero promotions (the `broken_tool_use` campaign's robust improvement was 0). The
held-out fitness curve is the evidence surface, and a flat curve is an honest,
expected outcome.

## 1. Prerequisites checklist

Verify every item below. Skipping the audit extra or the model accounts produces
a run that looks like it works but measures nothing.

| Requirement | How to satisfy | Why it matters |
|-------------|----------------|----------------|
| Python 3.12+ | `python --version` | Project floor (`pyproject.toml`, `requires-python >= 3.12`). |
| `uv` | `uv --version` | Package manager + runner for every command here. |
| Base sync | `uv sync` | Installs GEODE core. Not enough on its own for the loop. |
| Audit extra | `uv sync --extra audit` | Installs `inspect_ai` + Petri (puts the `inspect` CLI on PATH). WITHOUT it the audit aborts loudly: `plugins/petri_audit/runner.py` checks `shutil.which("inspect")` and returns an aborted report with `` `inspect` CLI not found on PATH — install the [audit] extra: `uv sync --extra audit`. `` (`core.self_improving.train` then returns failure for that cycle). Install it before your first run. |
| Auditor + judge model | Anthropic account (Claude). See model accounts below. | The Petri auditor drives each scenario, the judge scores each rollout on the rubric. No judge means no fitness. |
| Target model | `geode/gpt-5.5` via ChatGPT / Codex OAuth, or override `[self_improving_loop.autoresearch.target] model = ...` in config. | The audit target is GEODE-as-a-system running the mutated scaffold. No target means no audit. |

Without these model accounts the loop cannot run: the auditor, judge, and target
are three separate LLM roles, and an absent account aborts the audit (or, with
quota exhausted, degenerates to `fitness=None`, which the gate refuses to
promote).

### Model accounts and the three roles

The audit uses three distinct roles, each with its own model + credential
source. Manifest defaults come from `plugins/petri_audit/petri.plugin.toml`; you
override them per role under `[self_improving_loop.autoresearch.<role>]` in
`~/.geode/config.toml` (each table takes `model` + `source`):

| Role | Manifest default model | Default source | Provider account needed |
|------|------------------------|----------------|-------------------------|
| auditor | `claude-opus-4-7` | `claude-cli` | Anthropic (Claude Code OAuth or API key) |
| target | `claude-haiku-4-5` | `claude-cli` | Anthropic (or override to `geode/gpt-5.5` on ChatGPT / Codex OAuth) |
| judge | `claude-sonnet-4-6` | `claude-cli` | Anthropic (kept on a different provider than the target for the cross-provider guard) |

For a cross-provider audit, override the target to `geode/gpt-5.5`: it routes
through `GeodeModelAPI` to the `AgenticLoop`, so the mutated scaffold is in the
causal path of the audited behaviour. Set the override under
`[self_improving_loop.autoresearch.target]` (`model = "geode/gpt-5.5"`,
`source = "openai-codex"`). If you do not have ChatGPT / Codex access, set
`[self_improving_loop.autoresearch.target] model = ...` to a model your account
can reach instead.

### Config and keys

1. Copy the annotated template, then edit the values for your accounts:

   ```bash
   cp docs/examples/self_improving_loop.config.toml.example ~/.geode/config.toml
   ```

   The template documents every `[self_improving_loop.*]` key: `budget_minutes`,
   `use_oauth`, `seed_limit`, `seed_select`, `dim_set`, `max_turns`, plus the
   active per-role `[self_improving_loop.autoresearch.<role>]` (auditor / target /
   judge) `model` + `source` bindings. Absent sections fall back to documented
   defaults.

2. Set the API keys in `~/.geode/.env` (see `docs/setup.md` for the full key
   list). At minimum the auditor + judge need an Anthropic credential:

   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```

   The Claude Code / Codex OAuth path (`use_oauth = true`, the default) lets the
   audit subprocess reuse your subscription quota instead of PAYG. PAYG fallback
   stays off unless you flip `fallback_to_payg = true`. The OAuth audit path is
   roughly $0; the Anthropic PAYG path is roughly $5 to $10 per audit.

3. Optional outer-loop env hook: `GEODE_WRAPPER_OVERRIDE` points at the JSON file
   of system-prompt sections that the loop writes per cycle. The loop sets it for
   you; you do not normally set it by hand.

## 2. Your first campaign (5 steps)

### Step a: get an isolated worktree

Never run code work on `main` / `develop`. Allocate a worktree off `develop`:

```bash
git fetch origin
git worktree add .claude/worktrees/my-campaign -b feature/my-campaign develop
```

All subsequent commands run from inside that worktree checkout.

### Step b: set the loop config

Edit `~/.geode/config.toml` `[self_improving_loop.*]` per section 1. The values
that matter most for a first run: `seed_limit` (default 10), `budget_minutes`
(default 5, the per-audit wall-clock budget), and the three
`[self_improving_loop.autoresearch.<role>]` (auditor / target / judge) `model`
bindings. Leave the measurement parameters (`seed_limit`, `max_turns`,
`dim_set`) fixed once chosen: changing them changes how / what the audit
measures and confounds the mutated-vs-baseline comparison.

### Step c: gen-0 baseline + a single audit

`python -m core.self_improving.train` runs ONE audit per invocation, the
single-audit entry. Smoke the plumbing first with `--dry-run` (synthetic
baseline, no network, no quota): it emits the real output shape with
`fitness` near `0.89` against the dry-run dim mock.

```bash
# Plumbing smoke: synthetic audit, no budget spent, no PAYG/network.
uv run python -m core.self_improving.train --dry-run

# Real single audit (consumes budget). Redirect, never flood stdout.
uv run python -m core.self_improving.train > ~/.geode/self-improving/run.log 2>&1
```

Extract the metrics from the log:

```bash
grep "^fitness:\|^.*_score:\|^.*_mean:" ~/.geode/self-improving/run.log
```

An empty grep result means the audit crashed (check `tail -n 50` of the log) or
aborted before measuring: a missing `[audit]` extra aborts loudly with `inspect`
CLI not found on PATH. A fitness line with all-zero `dim_means` instead points at
a degenerate audit (the target could not reach a model, e.g. auth or quota), so
re-check section 1 before reading anything into the number. The first real run with no prior `baseline.json` establishes the
baseline; the cross-axis gate stays dormant until a baseline exists.

### Step d: a short 3-arm run

The campaign driver runs three arms (`never`, `random`, `gate`) from a matched
gen-0 reset so any observed gain is attributable to the gate, not to drift or
chance. Run a short version first (`--n 1` cycle per arm).

Recommended entry, the `geode campaign` command (a sibling change adds this CLI;
prefer it once available):

```bash
geode campaign --n 1 --k 5 --arms never,random,gate
```

Script form, which works today (equivalent driver, same flags):

```bash
uv run python core/self_improving/campaign.py --n 1 --k 5 --arms never,random,gate
```

Flags (from `core/self_improving/campaign.py::_build_arg_parser`):

| Flag | Default | Meaning |
|------|---------|---------|
| `--n` | 10 | cycles per arm |
| `--k` | 5 | gen-0 baseline repeats (the noise band) |
| `--arms` | `never,random,gate` | comma-separated arm order, gate LAST |
| `--mc` | 8 | max propose-guard re-proposal attempts |
| `--audit-max-samples` | 3 | `GEODE_AUDIT_MAX_SAMPLES` export |
| `--audit-max-connections` | 8 | `GEODE_AUDIT_MAX_CONNECTIONS` export |
| `--dry-run` | off | synthetic audits, no PAYG / network (plumbing only) |

Smoke the campaign wiring end to end with `--dry-run` before spending budget:

```bash
uv run python core/self_improving/campaign.py --n 1 --k 5 --arms never,random,gate --dry-run
```

A real 3-arm run is long: the gate arm runs last and sequentially, so budget per
arm at default `--n 10` adds up across many audits. Start with `--n 1` to confirm
the full loop completes before scaling up.

### Step e: where results land and how to read them

| Artifact | Path | What it holds |
|----------|------|---------------|
| Mutation ledger | `core/self_improving/state/mutations.jsonl` | One row per mutate / apply / audit / baseline / attribution event (git-tracked). Arms are tagged via `promote_policy` / `promote_policy_seed`, so you can split the stream by arm. |
| Promoted baseline | `~/.geode/self-improving/baseline.json` | The promoted baseline `dim_means` + `dim_stderr`. Advances only on a gate promote; a reject leaves it untouched. |
| Per-cycle eval | `~/.geode/petri/logs/*.eval` (+ `latest.eval`) | The Petri `.eval` per cycle, the single source for per-dim evidence. |
| Run logs | `~/.geode/self-improving/run.log` (single audit), `state/campaign/` (campaign progress + runs) | Stdout / progress for inspection. |
| Self-improving hub | `docs/self-improving/` (`index.html`) | The rendered pages: baseline epochs and the cross-generation evidence page. The held-out fitness curve, partitioned by baseline epoch and by arm, is the curve that counts. |

Read order for a finished run: the per-arm held-out curves on the hub
(`never` and `random` set the reference the `gate` arm must beat), then
`mutations.jsonl` to see which mutations were proposed and whether any promoted.
A flat or non-promoting `gate` arm is a valid result: the gate refused to promote
within measurement noise.

## 3. Common failures and fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Audit aborts immediately: `inspect` CLI not found on PATH | The `[audit]` extra is not installed, so `inspect_ai` / Petri are absent and the run aborts loudly before measuring | `uv sync --extra audit` (and `uv tool install -e ".[audit]" --force` if using the installed CLI), then re-run. |
| Audit aborts or `fitness=None` (degenerate, never promoted) | Auth missing or subscription quota exhausted on auditor / judge / target | Refresh OAuth / add the missing key in `~/.geode/.env`; wait for quota reset, or set `fallback_to_payg = true` to opt into PAYG charges. |
| Every cycle replays an identical (often fake) score | `inspect_ai` trajectory cache pollution: it keys on input messages, so an identical-scaffold repeat hits the same cached score | Purge `~/Library/Caches/inspect_ai/generate/`. A real campaign run purges it at start; for ad-hoc single audits, clear it by hand. |
| Audit killed mid-run | Per-audit wall-clock budget exceeded (`budget_minutes`, subprocess timeout `budget_minutes * 60 + 120`; campaign per-audit timeout via `GEODE_PER_AUDIT_TIMEOUT_S`, default 2700s) | Raise `budget_minutes` in config or `GEODE_PER_AUDIT_TIMEOUT_S` for the campaign, or shorten `max_turns` / `seed_limit` so each audit fits the budget. |

## 4. Where to go deeper

- `docs/self-improving/campaign-procedure.md`: the full procedure SoT. Scaffold
  surface (the 7 behaviour kinds), the two-audit measurement (selection vs frozen
  held-out), the gen-0 noise band, the promote gate and its margin, the 3-arm
  attribution design, and the fixed parameters / guards.
- `docs/architecture/autoresearch.md`: the design + fitness spec. Mission, the
  Petri x GEODE pipeline, tier classification and weights, the cross-axis
  monotone gate, and the git-as-optimiser ratchet.
- `docs/examples/self_improving_loop.config.toml.example`: the annotated config
  template, every `[self_improving_loop.*]` key with its default and precedence.
- `core/self_improving/program.md`: the single-audit driver's instruction sheet,
  including the `train.py` output format and the cross-axis gate semantics.
