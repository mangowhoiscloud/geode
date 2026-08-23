# R4.3 MCP manager responsibility split

Status: implementation evidence for roadmap package R4.3 (`DI-004`). The
architecture roadmap remains the execution/status source of truth.

## Observation

`core/mcp/manager.py` is 896 lines and one `MCPServerManager` instance owns six
unrelated mutable lifetimes: layered configuration and dotenv resolution,
stdio clients and reconnect cooldowns, tool discovery, invocation/retry and
result normalization, hook/text compatibility state, and signal/atexit
shutdown. Production callers need the existing facade, but none needs those
states to share one class.

## Hypothesis

Keep `MCPServerManager` as the public compatibility facade and move each state
to one concrete collaborator. Delegation should preserve method signatures,
return values, retry rules, tool ordering, hook events, and shutdown behavior.
No interface, generic manager framework, or second registry is required.

## Prediction

- Existing MCP lifecycle, registry, dotenv, adapter, loop, and runtime tests
  remain green without caller-visible behavior changes.
- The facade no longer owns configuration, connection, discovery, invocation,
  trace/cache, or lifecycle state directly.
- Each collaborator can be tested through one manager instance, and closing
  the manager still closes exactly one shared connection pool.

## Smallest implementation

| Owner | Responsibility |
|---|---|
| `MCPConfigCatalog` | layered config, dotenv resolution, status, JSON persistence |
| `MCPConnectionPool` | stdio clients, cooldown, epoch, respawn, health, close |
| `MCPToolDiscovery` | ordered visible-tool snapshot and last-seen routing |
| `MCPToolInvoker` + `MCPTraceStore` | call/result guard, retry, hooks, text compatibility cache |
| `MCPLifecycle` | signal/atexit installation state and idempotent shutdown state |
| `MCPServerManager` | public facade and cross-owner orchestration only |

## Frontier comparison

| Source | Adopt | Reject |
|---|---|---|
| Codex [`McpRuntime` / connection manager](https://github.com/openai/codex/blob/343074d4207d572809bd8cea15f4be1d09d98e0b/codex-rs/codex-mcp/src/runtime.rs) | one thread-owned facade over a connection set, catalog, and status modules | `ArcSwap`, auth caches, and publication machinery GEODE does not need |
| OpenClaw [gateway pattern](https://github.com/openclaw/openclaw/tree/49b4841081c6) | explicit control-plane ownership separated from execution work | transplanting its gateway/session hierarchy into MCP |
| Codex Cloud | no claim; its internal MCP registry is not publicly verifiable | undocumented implementation inference |
| [autoresearch](https://github.com/karpathy/autoresearch/tree/228791fb499a) | frozen acceptance and the simplest change that can be measured | experiment-loop workflow or speculative abstraction |

## Scope fences

- Do not split another manager; that requires a new GAP.
- Do not change MCP transport, public tool schemas, LLM adapters, extension
  discovery, or protocol publication.
- Do not replace the compatibility singleton in this package; runtime ownership
  changes belong to a separately claimed package.
