---
status: historical
authority: reference-only
measured_at: 2026-05-18
source_repository: https://github.com/mangowhoiscloud/geode
source_commit: 4fe594eb66b5de6bb3daedef7b433d59fcf719bb
operational_copy_commit: 755662298b741e0cb37c3792ff9d68613200f875
archive_import_commit: 22fb7f4650182e655b7c76edc145e916e6a3f6d8
scope:
  - core/
  - plugins/
  - autoresearch/
  - scripts/
superseded_by: docs/plans/2026-08-19-runtime-evidence-debt-modernization.md
---

# GEODE slop audit — 2026-05-18 baseline

This is a historical measurement, not an accepted-debt floor or promotion
gate. The repository grew and moved substantially after this snapshot, so
comparing today's absolute heuristic counts to it is not actionable. Run
`scripts/slop_audit.py` without a baseline for diagnostic candidates; promotion
uses behavioral tests, coverage, and deterministic lint/type/dependency gates.

Immutable provenance:

- [original measured report in GEODE](https://github.com/mangowhoiscloud/geode/blob/4fe594eb66b5de6bb3daedef7b433d59fcf719bb/docs/audits/2026-05-18-slop-audit-baseline.md)
- [later operational copy in GEODE](https://github.com/mangowhoiscloud/geode/blob/755662298b741e0cb37c3792ff9d68613200f875/scripts/slop_audit_baseline.md)
- [archived report imported into geode-eval-artifacts](https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/22fb7f4650182e655b7c76edc145e916e6a3f6d8/sil/audit-reports/2026-05-18-slop-audit-baseline.md)

| Lens | Count | Severity |
|------|------:|----------|
| unused_imports | 0 | info |
| dead_private_functions | 139 | warning |
| duplicate_signatures | 76 | info |
| abandoned_todos | 0 | info |
| lint_bypass_markers | 91 | info |
| stale_references | 0 | info |

## Samples (first 5 per lens)

### unused_imports

- _(none)_

### dead_private_functions

- `core/ui/event_renderer.py :: _handle_round_start`
- `core/ui/event_renderer.py :: _handle_thinking_start`
- `core/ui/event_renderer.py :: _handle_thinking_end`
- `core/ui/event_renderer.py :: _handle_tool_start`
- `core/ui/event_renderer.py :: _handle_tool_end`

### duplicate_signatures

- `main (17 copies): core/mcp_server.py`
- `stop (9 copies): core/ui/event_renderer.py`
- `start (6 copies): core/ui/status.py`
- `update (4 copies): core/ui/status.py`
- `name (32 copies): core/tools/web_tools.py`

### abandoned_todos

- _(none)_

### lint_bypass_markers

- `core/runtime.py:72`
- `core/runtime.py:76`
- `core/runtime.py:78`
- `core/runtime.py:81`
- `core/ui/context_local.py:91`

### stale_references

- _(none)_
