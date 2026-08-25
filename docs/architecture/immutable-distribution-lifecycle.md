# Immutable distribution lifecycle audit

> Design evidence, not a status ledger. R10.1 and DIST-001–004 in
> `extensibility-roadmap.md` own execution status and closure evidence.

## Decision

Python wheel is the right public artifact for GEODE's Python runtime, four
console entry points, and immutable resources. It is not a data wheel, agent
workspace, Git checkout, state store, sandbox image, or generated-output root.

Keep one `geode-agent` wheel. Split a second distribution only after an
independent embedding contract, dependency budget, or release cadence is
measured. The current kernel wheel remains a CI-only architecture projection.

## G-of-4 comparison

Audit date: 2026-08-25. External claims below use primary documentation or
source.

| System | Observed boundary | GEODE decision |
|--------|-------------------|----------------|
| Codex CLI (`465eafac`) | Installer/Homebrew/npm deliver immutable executables and target helpers; prompts and system skills are embedded, while config, threads, history, logs, and SQLite state live under `CODEX_HOME`. [package layout](https://github.com/openai/codex/blob/465eafacbc2db4ff828cd6d18ed8f25d22e48f53/scripts/codex_package/layout.py), [skills](https://github.com/openai/codex/blob/465eafacbc2db4ff828cd6d18ed8f25d22e48f53/codex-rs/skills/src/lib.rs), [config](https://github.com/openai/codex/blob/465eafacbc2db4ff828cd6d18ed8f25d22e48f53/codex-rs/core/src/config/mod.rs) | Adopt immutable code/assets plus external mutable home. |
| Codex Cloud | A task gets a container, selected repository checkout, setup phase, agent phase, diff, and optional PR. Repository `AGENTS.md` and repo/user skills belong to their scopes, not the client package. [cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environment), [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [skills](https://learn.chatgpt.com/docs/build-skills) | Require a real GEODE checkout for git-as-optimizer mutation and promotion. Keep image/sandbox policy outside the wheel. |
| OpenClaw (`ee4bb5f8`) | One npm product package ships runtime and bundled skills. Mutable state uses `OPENCLAW_STATE_DIR`; the agent workspace and managed/personal skills are separate. [workspace](https://github.com/openclaw/openclaw/blob/ee4bb5f85b56fb64ccf57a34048fb2c85348062b/docs/concepts/agent-workspace.md), [paths](https://github.com/openclaw/openclaw/blob/ee4bb5f85b56fb64ccf57a34048fb2c85348062b/src/config/paths.ts), [skills](https://github.com/openclaw/openclaw/blob/ee4bb5f85b56fb64ccf57a34048fb2c85348062b/docs/tools/skills.md) | Adopt one product artifact, exact bundled defaults, and external workspace/state tiers. Adapt updater sequencing; do not copy its plugin manager. |
| autoresearch (`228791fb`) | The experiment loop explicitly creates a Git branch, mutates source in that checkout, runs the fixed evaluator, commits kept candidates, and leaves `results.tsv` untracked. [program](https://github.com/karpathy/autoresearch/blob/228791fb499afffb54b46200aca536f79142f117/program.md) | Preserve Git as promotion authority. Do not reinterpret installed package data as the repository. |

## Local writer-reader audit

| GAP | Before | Resolved boundary |
|-----|--------|-------------------|
| DIST-001 | `core.paths` derived the scaffold SoT from installed `core/paths.py`; ledger, policy, epoch, mutation, and promotion writers could change `site-packages` and attempt Git operations there. | Reads may use packaged reference inputs. Every mutation/promotion writer calls `require_evolve_workspace()` before its first side effect. Rolling ledgers are excluded from wheel/sdist. Installed smoke hashes all distribution files, attempts a write, and requires byte-identical `RECORD` ownership afterward. |
| DIST-002 | The helper build script and runtime lookup defaulted to `<distribution>/.geode/ComputerUseHelper`. | Packaged Swift/build sources remain read-only. `geode setup`, the script default, and runtime lookup share `GEODE_HOME/helpers/computer-use`. |
| DIST-003 | Hatch force-included all `.geode/skills`; several entries required repository files, missing scripts, or one operator's filesystem. | Hatch and artifact gates list eight self-contained built-ins exactly. Repository and personal skills remain external tiers. Installed smoke loads the exact set and its companion files. |
| DIST-004 | The updater replaced a live uv-tool before stopping the old daemon, and the tracked distribution skill repeated that obsolete order. | Source and uv-tool paths plus operator guidance share stop-before-replace. Stop failure prevents installation, install failure leaves serve stopped, `--no-restart` remains stopped, and a restart succeeds only when CLI output and IPC greeting versions match. |

## Invariants

- Package data is immutable and reproducible; user and experiment state is not
  package data.
- A wheel may expose `geode-evolve`, but real mutation/promotion requires an
  explicit writable GEODE Git checkout (`GEODE_EVOLVE_WORKSPACE` when not
  launched inside it).
- Worker `GEODE_STATE_ROOT` remains a per-worker scratch override; it does not
  become promotion authority.
- Built-in skills are exact release inputs. Project and personal skills keep
  their existing higher-precedence external roots.
- Upgrades never run old daemon code against newly replaced package files.

## Rejected additions

- no second public core/eval/evolve wheel;
- no workspace manager or package-state registry;
- no public kernel-wheel SKU;
- no candidate-install/atomic-swap framework until zero-downtime rollback is a
  measured requirement;
- no new plugin manager.
