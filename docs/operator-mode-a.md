# Mode A — operator manual (external agent runs the self-improving loop)

> **Status**: doc-only (PR-C6, 2026-05-21). The GEODE CLI does NOT
> trigger this mode — Mode A is a *manual long-horizon agent*
> workflow. See `docs/plans/2026-05-21-self-improving-loop-ux.md`
> for the Mode A vs Mode B comparison matrix.

## TL;DR

| Mode | Trigger | LLM that proposes mutations |
|------|---------|----------------------------|
| **A (this doc)** | An external Claude Code / Codex CLI session, manually started by you | Whatever model the external session runs |
| **B** (`/self-improving run`) | The GEODE CLI slash command | `[self_improving_loop.mutator] default_model` (defaults to `Settings.model` via PR-MINIMAL-2 G1a) |

Both modes write to the same 5 policy SoTs at
`autoresearch/state/policies/*.json` (git-tracked since
PR-RATCHET-1) and append the same `autoresearch/state/mutations.jsonl`
ledger — so a campaign can mix Mode A and Mode B turns freely.
Choose Mode A when you want a long-horizon agent reasoning over
multiple mutations across a single session; choose Mode B when you
want one tightly-scoped iteration with explicit confirmation.

## Boot recipe (Claude Code)

The original Karpathy-autoresearch idiom: the agent reads
`autoresearch/program.md` as its baseline contract, then runs the
loop autonomously.

1. Open the repo at the branch you want to evolve:
   ```bash
   cd ~/workspace/geode
   git checkout -b autoresearch/<run-tag> origin/develop
   ```
   The branch name convention is `autoresearch/<tag>` (per
   `autoresearch/program.md` § Setup). The agent will commit each
   experiment to this branch; the branch tip is "current best".

2. Start a fresh Claude Code session in this repo root.

3. Send the boot prompt (literally — Karpathy minimal idiom):
   ```
   Read program.md and start a new experiment. Begin with the
   baseline for this PR.
   ```
   Claude Code resolves `program.md` to `autoresearch/program.md`
   from its filesystem context (the repo root is the working
   directory). The agent picks up the full 5-row mutation-kind
   table introduced in PR-MINIMAL-2 C5 and the agent CAN/CANNOT
   rules from § 63–78 of program.md.

4. The agent will:
   - Confirm the in-scope files with you (`prepare.py`,
     `train.py`, `program.md`, `README.md`).
   - Verify the seed pool tree at
     `plugins/petri_audit/seeds/<tier>/<dim>/<NN>_<variant>.md`.
   - Initialise `autoresearch/state/results.tsv` header.
   - Wait for your "go" before the first audit.

5. Each experiment iteration:
   - Agent reads the current baseline + meta-review + 5 policy SoTs
     from `autoresearch/state/policies/`.
   - Agent edits ONE mutation target (per the program.md CAN list).
   - Agent runs `uv run python autoresearch/train.py` and waits
     for the `---` separator output.
   - Agent decides promote/reject per the 3-rule gate in
     `_should_promote`.
   - Agent commits the change (the wrapper diff + the
     `mutations.jsonl` append + the new `baseline.json` if
     promoted). Branch tip advances.

6. End the run: `git push origin autoresearch/<run-tag>` for
   archival, or `git reset --hard origin/develop` to discard the
   branch.

## Boot recipe (Codex CLI)

Mirror of the Claude Code recipe. Codex CLI also reads
`autoresearch/program.md` from the working directory.

```bash
cd ~/workspace/geode
git checkout -b autoresearch/<run-tag> origin/develop
codex
# Then send: "Read program.md and start a new experiment.
# Begin with the baseline for this PR."
```

Codex CLI's OAuth flow handles model selection; the agent picks
target/judge per the `[self_improving_loop.autoresearch]` toml
section (PR-MINIMAL-2 G1a defaults to `Settings.model` for both).

## Comparison with Mode B (`/self-improving run`)

| Dimension | Mode A | Mode B |
|-----------|--------|--------|
| Boot effort | New agent session, manual prompt | One slash command |
| Iterations | Many per session (operator-controlled exit) | 1 per `/run` (or `--n N`, max 10) |
| Confirmation | Agent self-reviews per its program.md contract | Per-iteration `y/N/d/s` interactive prompt |
| Mutator LLM | Whatever the external agent runs (typically Claude) | `MutatorConfig.default_model` (toml-only) |
| Audit log | `git log` over branch | `/self-improving status` + `/self-improving history` (= same `git log`) |
| Rollback | `git revert` / `git reset --hard <ref>` | `/self-improving rollback <id>` (= `git revert <commit>`) |
| Subscription quota | External session's quota | `MutatorConfig.source` (auto / api_key / claude-cli / openai-codex) |
| Cost gate | Manual — agent watches its quota | `~/.geode/config.toml` `warn_threshold` / `abort_threshold` + `fallback_to_payg` |

## SoTs shared by both modes

- `autoresearch/state/policies/wrapper-sections.json` —
  WRAPPER_PROMPT_SECTIONS dict (legacy "prompt" target_kind)
- `autoresearch/state/policies/tool-policy.json` — tool selection
  policy
- `autoresearch/state/policies/decomposition.json` —
  decomposition heuristics
- `autoresearch/state/policies/retrieval.json` — retrieval /
  memory policies
- `autoresearch/state/policies/reflection.json` — self-reflection
  gate parameters
- `autoresearch/state/mutations.jsonl` — git-tracked audit ledger
  (one row per applied / rejected / rolled_back mutation)
- `autoresearch/state/baseline.json` — fitness baseline snapshot
  (writer: `autoresearch/train.py:_should_promote`)
- `autoresearch/state/results.tsv` — operator-facing 12-col
  results journal (writer: `autoresearch/train.py:main`)
- `autoresearch/state/results.jsonl` — full 20-dim per-row
  archive

All paths are in-repo + git-trackable (PR-RATCHET-1 / B7 RATCHET).
A campaign mixing Mode A and Mode B sees the same files — there
is no "Mode A history" vs "Mode B history".

## When Mode A is the right choice

- **Long-horizon reasoning across mutations**. The external agent
  can reflect on N consecutive mutation results, spot a pattern,
  and decide to revert + retry differently — Mode B's single-iter
  confirmation doesn't see N rounds of context.
- **Cross-kind multi-step mutations**. The agent can decide that
  `tool_policy` change A enables `prompt` change B; Mode B's
  per-iteration scope doesn't carry that dependency.
- **Cost-conscious campaigns**. Subscription OAuth on the agent
  side keeps cost flat across many iterations.
- **Exploratory hyperparameter sweeps** on `BUDGET_MINUTES` /
  `MAX_TURNS` / `SEED_LIMIT` in `train.py` — Mode B doesn't expose
  these knobs, the agent edits them directly per program.md.

## When Mode B is the right choice

- **Operator wants explicit consent per mutation**. The
  confirmation prompt prevents surprise.
- **Scheduled jobs**. Mode B is invokable from a `geode schedule`
  task without booting a new agent session.
- **Reproducibility**. The mutator LLM (model + source) is pinned
  in `~/.geode/config.toml` — easier to audit "what model
  proposed this mutation".

## References

- Karpathy autoresearch upstream:
  https://github.com/karpathy/autoresearch (228791f, MIT 2026-03)
- `autoresearch/README.md` — driver overview + role split with Petri
- `autoresearch/program.md` — agent baseline instruction
  (5-kind table in § 63–78)
- `docs/plans/2026-05-21-self-improving-loop-ux.md` — Mode A vs B
  matrix + UX design
- PR-MINIMAL-2 #1398 — G1a Settings.model inherit (mutator) +
  C5 program.md 5-kind table
- PR-RATCHET-1 #1396 — 5 SoT files moved in-repo
