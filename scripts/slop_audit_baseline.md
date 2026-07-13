# GEODE slop audit operational baseline

> Historical source:
> [`geode-eval-artifacts/sil/audit-reports/2026-05-18-slop-audit-baseline.md`](https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/main/sil/audit-reports/2026-05-18-slop-audit-baseline.md)

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
