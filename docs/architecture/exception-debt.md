# Architecture exception debt

`exception-debt.toml` is the machine-readable source of truth for temporary
architecture exceptions. It does not replace `pyproject.toml`: import-linter
and Ruff still execute from their native configuration. The checker requires
the executable configuration and the ownership ledger to agree exactly.

## Record model

An `import_edge` record owns one unique `source -> target` edge and lists every
import-linter contract that ignores it. An edge shared by two contracts has one
metadata record and two checked contract occurrences.

A `ruff_debt` record owns one rule/path/symbol tuple:

- `mode = "ceiling"` identifies every symbol exactly at a configured global
  Ruff ceiling.
- `mode = "override"` identifies a symbol above that ceiling. The source must
  also carry a rule-specific `# noqa`; a bare or unrelated suppression is not
  accepted.

Both record types require an ID, owner module, rationale, creation date, target
GAP or closure package, and a measurable expiry condition. Ruff records also
pin the measured value. Paths and targets are validated against the current
repository and architecture roadmap.

## Ratchet behavior

Run:

```bash
uv run python scripts/check_architecture_exceptions.py \
  --check \
  --base-ref origin/develop
```

The checker fails when:

- an import-linter ignore has no record, or a record no longer has a configured
  contract occurrence;
- governed Ruff rules are disabled globally or for a production path;
- the symbols at a Ruff ceiling differ from the registered witnesses;
- a symbol exceeds a ceiling without both an `override` record and a
  rule-specific suppression;
- a configured ceiling is above the current measured maximum;
- a ceiling increases relative to the target branch.

Ruff is probed one point below each configured ceiling with inline suppressions
disabled. The probe runs in isolated mode over an explicit list of every Python
file under `core/`, `plugins/`, and `scripts/`, so project excludes,
force-excludes, and per-file ignores cannot hide a measurement. This exposes
only ceiling witnesses and overrides, so the ledger does not duplicate metrics
for thousands of ordinary functions.

## Changing an exception

Prefer removing the dependency or splitting the symbol. When an ignored edge
is removed, delete it from both `pyproject.toml` and the ledger in the same PR.
When a maximum falls, lower the corresponding Ruff value and update the
remaining witness records in that PR. New exceptions must be registered with
complete metadata; the diff is the approval surface, not a baseline update
command.
