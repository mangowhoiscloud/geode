# `.geode/` -- Agent Context Lifecycle

> **English** | [한국어](context-lifecycle.ko.md)

The `.geode/` directory is the project-local persistent store for the agent. It survives across sessions and provides sources used by runtime context. Not every source is injected into every model call.

## Directory Layout

```
.geode/
├── config.toml              # Gateway bindings, MCP servers, model settings
├── MEMORY.md                # Human-readable memory index (deprecated, migrating)
├── LEARNING.md              # Agent learning log
│
├── memory/                  # Tier 2: Project Memory
│   └── PROJECT.md           # Structured IP analysis history (max 50, LRU rotate)
│
├── rules/                   # Auto-generated domain rules
│   ├── dark-fantasy.md      # Pattern: *berserk*, *dark*soul*, *elden*
│   ├── anime-ip.md          # Pattern: *cowboy*, *ghost*, *evangelion*
│   └── indie-steam.md       # Pattern: *satisfactory*, *factorio*
│
├── vault/                   # Permanent artifacts (never auto-deleted)
│   ├── reports/             # Generated analysis reports (md/html/json)
│   ├── research/            # Deep research outputs
│   ├── profile/             # User career profile, resume
│   └── applications/        # Job application tracking
│
├── skills/                  # Runtime Skills (20 domain-specific prompt injections)
│   ├── arxiv-digest/        # Auto-search and summarize AI papers
│   ├── daily-briefing/      # Morning news/trend summary
│   ├── deep-researcher/     # Systematic web research + report
│   ├── job-hunter/          # Job posting search + match analysis
│   └── ...
│
├── result_cache/            # Pipeline result LRU cache (SHA-256 key, 24h TTL)
└── user_profile/            # Tier 0.5: User identity + preferences
```

## Context Hierarchy

`ContextAssembler` merges five tiers for callers that explicitly invoke `GeodeRuntime.assemble_context()`. Lower tiers override higher tiers for the same key. The default `AgenticLoop` does not call this facade: `core/agent/system_prompt.py` builds the live model-visible prompt from its declared sources, while conversation history is supplied separately.

```
Tier 0   SOUL           GEODE.md — agent identity, mission, constraints
Tier 0.5 User Profile   ~/.geode/user_profile/ — role, expertise, language, format prefs
Tier 1   Organization   MonoLake — cross-project IP data (DAU, revenue, signals)
Tier 2   Project        .geode/memory/PROJECT.md — project-local analysis history
Tier 3   Session        In-memory — current conversation, tool results, plans
```

### Assembly Flow

```
GeodeRuntime.assemble_context()  # explicit facade
└── ContextAssembler.assemble(session_id, ip_name)
│
├── T0  load GEODE.md (identity)
├── T0.5 load user_profile (preferences)
├── T1  load org_memory.get_ip_context(ip_name)
├── T2  load project_memory.get_context_for_ip(ip_name)
├── T3  load session_store.get(session_id)
│
├── inject project_env (detected harness: Python/Node/etc.)
├── inject run_history (recent execution summaries, Karpathy P6 L3)
├── inject journal_context (learned patterns)
└── inject vault_context (relevant artifacts)
```

### Budget Allocation (280-char compression)

When the explicit facade exceeds its budget, `ContextAssembler.compress()` allocates proportionally:

| Tier | Budget | Strategy |
|------|--------|----------|
| SOUL | 10% | Extract mission line (first non-header line) |
| User Profile | (shared with SOUL) | One-line summary |
| Organization | 25% | Key metrics only |
| Project | 25% | Latest analysis entry |
| Session | 40% | Recent messages + tool results |

## Persistence Lifecycle

| Store | Scope | TTL | Rotation | Write Trigger |
|-------|-------|-----|----------|---------------|
| `memory/PROJECT.md` | Project | Permanent | Max 50 entries, LRU evict | Pipeline completion |
| `rules/` | Project | Permanent | Manual | Agent auto-generates from repeated patterns |
| `vault/` | Project | Permanent | Never deleted | Report generation, research completion |
| `result_cache/` | Project | 24h | SHA-256 dedup, TTL evict | Pipeline completion |
| `skills/` | Project | Permanent | Manual reload | User or agent creates |
| `config.toml` | Project | Permanent | Hot-reload (chokidar 300ms debounce) | User edits |

## Runtime Context Sources (beyond `.geode/`)

| Source | Location | Injected As |
|--------|----------|-------------|
| GEODE.md | Project root | T0 SOUL identity |
| `~/.geode/user_profile/` | Global | T0.5 User preferences |
| `~/.geode/.env` | Global | API keys (baseline) |
| `.env` | Project root | API keys (override, non-empty only) |
| `~/.geode/scheduler/jobs.json` | Global | Scheduler state (atomic JSON) |
| `~/.geode/cli.sock` | Global | IPC socket (serve daemon) |

## Context in the 4-Layer Stack

```
Agent Layer    build_system_prompt reads declared sources + conversation history
                 │
Facade Layer   GeodeRuntime.assemble_context() -> ContextAssembler (explicit only)
                 │
Runtime Layer  Memory modules provide raw data to both paths
                 │
Model Layer    receives the live system prompt, not the facade dict automatically
```

Runtime readers access `.geode/` through their owning memory or prompt modules. `ContextAssembler` enforces tier priority, budget allocation, and freshness only for its explicit facade; it is not a universal model-call gateway.
