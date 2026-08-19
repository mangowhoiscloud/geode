# Runtime prune audit — 2026-08-07

> Superseded note: the later
> [runtime evidence debt modernization plan](2026-08-19-runtime-evidence-debt-modernization.md#p1--retire-ineffective-count-ratchets)
> retires the slop and selected-test count ratchets. Their results below remain
> historical evidence for this completed cleanup.

## Goal

Remove migration residue that has no live caller while preserving public
compatibility, plugin capability contracts, and user-data migrations.

## Measured baseline

- `scripts/slop_audit.py`: 0 unused imports, 196 heuristic private candidates,
  130 duplicate signatures, 0 abandoned TODOs, 162 bypass markers.
- `scripts/check_slop_ratchet.py`: all ceilings pass; one bypass marker is
  already below the recorded ceiling.
- `CLIPoller.start()` starts only the asyncio server. The old socket/thread
  chain has no caller and terminates in an intentional `RuntimeError` stub.
- The legacy-import allowlist names only files that no longer exist.

## Frontier grounding

| System | Keep | Do not copy |
|---|---|---|
| Hermes | Explicit plugin capability no-ops and public middleware bridges | Unmarked private leftovers |
| Codex | Named deprecation/migration boundaries; one canonical execution path | Parallel legacy execution paths |
| GEODE | User-data fallback and public schema/plugin contracts | Caller-free aliases, empty startup hooks, dead sync IPC |

## GAP and migration map

| Old surface | Current surface | Action |
|---|---|---|
| sync IPC socket/thread chain | asyncio Unix server and `_AsyncClientEndpoint` | delete old chain |
| raw-socket `_StreamingWriter` | endpoint-only writer | narrow type and implementation |
| `suppress_noisy_warnings()` | no action required | delete no-op and wrappers |
| public compatibility aliases | canonical APIs | retain thin bridges; use canonical APIs internally |
| `_parse_yaml_frontmatter` alias | shared `_frontmatter.parse_yaml_frontmatter` | import canonical helper |
| dead one-line/private helpers | existing direct implementation | delete delegates |
| legacy-import file exemptions | no extant exempt files | delete empty allowlist |
| disconnected IPC approval | 120-second timeout | wake immediately with fail-closed denial |
| eager `sub_agent → worker` import | local `WorkerRequest` construction dependency | defer the import and pin clean-interpreter import liveness |

The duplicate-signature list is dominated by protocol-shaped names such as
`main`, `stop`, and `create`; the private-function list includes dynamically
dispatched UI handlers. They are audit leads, not deletion proof. The precise
top-level module graph has 542 nodes, 842 edges, and no static SCC, but a clean
interpreter exposed one import-order cycle through package initialization; the
deferred `WorkerRequest` import removes that runtime cycle.

## Acceptance

1. IPC approval, streaming, graceful drain, auth, skills, config, UI, and audit
   targeted tests pass.
2. Ruff, mypy, import-linter, non-live pytest, architecture baseline, and slop
   ratchet pass.
3. No new dependency, abstraction, compatibility layer, or feature flag.
4. An independent committed-diff review finds no missed live caller.
5. The selected-test ratchet records the justified removal of two raw-socket
   tests while the replacement endpoint-level disconnect regression test stays
   in the suite.
6. The existing live hook E2E publishes a deterministic seven-scenario action
   matrix covering block, deny, cancellation, failure, middleware replay
   prevention, and sub-agent timeout alongside its normal live path.
