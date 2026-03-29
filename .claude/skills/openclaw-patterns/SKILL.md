---
name: openclaw-patterns
description: Agent system design patterns distilled from the OpenClaw codebase. Gateway-centric control, Session Key hierarchy, Binding routing, Lane Queue concurrency, Sub-agent Spawn+Announce, 4-tier automation, Plugin architecture, Policy Chain, Failover strategies. Triggered by "gateway", "session", "binding", "lane", "spawn", "announce", "heartbeat", "cron", "hook", "plugin", "policy", "failover" keywords.
user-invocable: false
---

# OpenClaw Patterns — Agent System Design Distillation

> **Source**: `github.com/openclaw/openclaw` (TypeScript, ~48 source files)
> **Philosophy**: Everything is a session, every execution goes through a queue, every extension is a plugin.

## System Architecture — Gateway + Agent Dual System

```
┌─────────────────────────────────────────────────────────┐
│  Gateway (Control Plane)                                  │
│  ├── Channel Manager — 7+ channel plugin integration     │
│  ├── Session Manager — Hierarchical session key mgmt     │
│  ├── Binding Router  — Deterministic message→agent map   │
│  └── Node Registry   — Distributed node register/lookup  │
├─────────────────────────────────────────────────────────┤
│  Agent Runtime (Execution Plane)                          │
│  ├── Attempt Loop    — LLM call + tool execution cycle   │
│  ├── Tool System     — Policy-based tool access control  │
│  ├── Skill Loader    — 4-tier priority skill loading     │
│  └── Sub-agent Pool  — Spawn + Announce parallel exec    │
└─────────────────────────────────────────────────────────┘
```

Core principle: Gateway decides only "where to send," Agent decides "what to do." Separation of concerns.

---

## 1. Session Key Hierarchy

Session keys are hierarchical strings combining agent, channel, and peer.

```
agent:{agentId}:{context}

agent:main:main                    # Main agent default session
agent:main:telegram:dm:123456      # Telegram DM session
agent:work:discord:group:789       # Discord group session
agent:main:subagent:run-abc123     # Sub-agent isolated session
cron:{jobId}                       # Cron isolated session
hook:{hookId}                      # Webhook isolated session
```

**Design Points**:
- String-based → zero serialization/deserialization cost
- Hierarchical → prefix matching enables scope filtering
- Session = context isolation boundary (same agent with different sessions are independent)

**Application**: Apply `ip:{name}:{phase}` format to `thread_id`, used as key for Checkpoint-based recovery.

---

## 2. Binding-based Deterministic Routing

Route inbound messages to agents via **static matching rules**.

```json5
{
  bindings: [
    { agentId: "home", match: { channel: "whatsapp", accountId: "personal" } },
    { agentId: "work", match: { channel: "whatsapp", accountId: "biz" } },
    { agentId: "work", match: {
      channel: "whatsapp",
      peer: { kind: "group", id: "work-group@g.us" }
    }}
  ]
}
```

**Priority (Most-Specific Wins)**:
```
peer match > guildId > teamId > accountId > channel > default agent
```

**Features**:
- Routing via config only, no LLM judgment (deterministic, predictable)
- Config hot reload possible (no code changes/redeployment needed)
- 1 message → exactly 1 agent (fan-out via Sub-agent)

**Application**: Same principle applied to pipeline mode (`full_pipeline`, `evaluation`, `scoring`) node routing.

---

## 3. Lane Queue — Concurrency Control

The default execution model is **serial**. Parallelism must be explicitly requested.

```
Session Lane — Same-session requests preserve order (serial)
Global Lane  — Entire agent concurrency limit (N)
Subagent Lane — Sub-agent dedicated (maxConcurrent: 8)
Hook Lane    — Webhook dedicated
```

**Flow**:
```
Request → Acquire Session Lane → Acquire Global Lane → Execute → Release
```

**Design Points**:
- Serial by default eliminates state conflicts (safety first)
- Explicit switch to Sub-agent only where parallelism is needed
- Per-lane independent `maxConcurrent`, `runTimeoutSeconds` settings

---

## 4. Sub-agent Spawn + Announce Pattern

**Explicitly create Sub-agents when parallel execution is needed.**

```
Parent Agent (agent:main:main)
    │
    ├── spawn("Reddit analysis")  → run-001 (isolated session)
    ├── spawn("YouTube analysis") → run-002 (isolated session)
    ├── spawn("Twitch analysis")  → run-003 (isolated session)
    │
    │   [3 concurrent, maxConcurrent=8]
    │
    ├── ← announce(run-001, result)
    ├── ← announce(run-002, result)
    ├── ← announce(run-003, result)
    │
    └── Consolidate results
```

**SubagentRunRecord**:
```typescript
{
  runId, childSessionKey,     // Isolated session identifier
  requesterSessionKey,        // Parent session identifier
  task,                       // Execution instruction (string)
  cleanup: "delete" | "keep", // Session handling after completion
  outcome: { status: "ok" } | { status: "error", error? },
  archiveAtMs,                // Auto-archive after 60 minutes
}
```

**Announce**: Sub-agent completion → result injected as system event into Parent session.

**Application**: LangGraph Send API is the structured version of this pattern. Private State provides type safety + Reducer provides automatic merge.

---

## 5. 4-Tier Automation Architecture

```
┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
│ L1 Heartbeat│  │ L2 Cron    │  │ L3 Internal│  │ L4 Gateway │
│ Runner      │  │ Service    │  │ Hooks      │  │ Hooks      │
│             │  │            │  │            │  │            │
│ Fixed       │  │ at/every/  │  │ command:new│  │ HTTP POST  │
│ interval    │  │ cron expr  │  │ agent:boot │  │ + Bearer   │
│ polling     │  │            │  │            │  │            │
└──────┬──────┘  └──────┬─────┘  └──────┬─────┘  └──────┬─────┘
       └────────────────┴───────────────┴───────────────┘
                         │
              System Events Queue (in-memory, max 20)
```

### L1: Heartbeat Runner

Fixed-interval polling. All 5 conditions must be met before execution:
- `heartbeatsEnabled` global flag
- `agents.size > 0`
- `now >= nextDueMs`
- `isWithinActiveHours()` — active hours per timezone
- `getQueueSize(MainLane) === 0` — only when main lane is empty

**Active Hours**: Automatic handling of midnight crossing (`22:00-06:00`), independent timezone settings per agent.

### L2: Cron Service — 3 Schedule Types

```
at    — One-shot absolute time (auto-disable/delete after success)
every — Fixed interval (aligned to anchorMs → drift prevention on restart)
cron  — Expression (timezone support)
```

**Payload 2 types**:
- `systemEvent` → text injection into main session (sessionTarget: "main")
- `agentTurn` → full agent execution in isolated session (sessionTarget: "isolated")

### L3: Internal Hooks — Event-driven

```
command:new     → session memory save
command:reset   → state reset
agent:bootstrap → system prompt injection/replacement
gateway:startup → initialization script
```

Hook structure: `my-hook/HOOK.md` (YAML frontmatter) + `handler.ts` (handler function)

### L4: Gateway Hooks — External Webhooks

HTTP POST → Hook Mapping (URL/source matching) → wake (system event) or agent (isolated execution)

Mustache template: `"New email from {{payload.from}}: {{payload.subject}}"`

---

## 6. Plugin Architecture — 4 Extension Points

| Extension Point | Registration Method | Discovery |
|----------------|-------------------|-----------|
| **Channel** | Register plugin with ChannelManager | Config-based |
| **Tool** | createOpenClawTools + Policy filter | Policy-based |
| **Skill** | 4-tier priority loading | Filesystem-based |
| **Hook** | Auto-discovery from 4 locations | Directory-based |

**Skill Loading Priority** (low → high):
```
1. Bundled Skills     (built into package)
2. Extra Dirs         (specified in config)
3. Managed Skills     (~/.openclaw/skills)
4. Workspace Skills   (./skills)  ← highest priority
```

**Application**: GEODE ToolRegistry is the Python implementation of this pattern. `register()` → `get()` → `to_anthropic_tools()`.

---

## 7. Policy Resolution Chain — Multi-layer Tool Access Control

```
Profile Policy → Global Policy → Agent Policy
    → Group Policy → Sandbox Policy → Subagent Policy
    → [Final allowed tool list]
```

Each layer can add or remove tools. The most specific policy takes priority.

**Application**: Can be used for per-analysis-mode tool access control in GEODE (e.g., blocking LLM tools during dry_run).

---

## 8. Failover Strategy — 4-Stage Auto-Recovery

```
1. Auth Profile Rotation — Rate Limit/Auth Error → next profile → retry
2. Thinking Level Fallback — high unsupported → medium → low → off
3. Context Overflow — detect → Auto-compaction → retry after compression
4. Model Failover — Primary failure → Fallback model → retry
```

**Application**: Extension of GEODE Feedback Loop. Strategy of switching models and retrying when confidence < 0.7.

---

## 9. Operational Patterns

### Coalescing (Request Merging)

```
Multiple wake requests within 250ms window → merged into 1 execution
Main lane occupied → retry at 1-second intervals
timer.unref() → heartbeat alone does not keep process alive
```

### Atomic Store (Safe Writes)

```
Create tmp file → rename (atomic) → .bak backup (best-effort)
```

### Run Log (JSONL + Pruning)

```
File: ~/.openclaw/cron/runs/{jobId}.jsonl
Auto Pruning: maxBytes=2MB, keepLines=2000
```

### Config Hot Reload

```
chokidar file watch → debounce 300ms
hooks change → reload-hooks
cron change  → restart-cron
gmail change → restart-gmail
```

### Stuck Job Detection

```
runningAtMs over 2 hours → considered stuck → runningAtMs cleared
```

---

## 10. Source Structure (Reference)

```
openclaw/src/
├── gateway/              # Control Plane
│   ├── routing.ts        # Binding routing
│   ├── hooks.ts          # Gateway Hooks (HTTP)
│   ├── hooks-mapping.ts  # URL/source mapping
│   ├── config-reload.ts  # Hot Reload
│   └── server/           # HTTP/WS server
├── agents/               # Execution Plane
│   ├── run.ts            # runEmbeddedPiAgent
│   ├── attempt.ts        # Attempt Loop
│   ├── tools/            # Tool factory + execution
│   └── bootstrap-hooks.ts
├── infra/                # Shared Infrastructure
│   ├── lane-queue.ts     # Lane Queue concurrency
│   ├── heartbeat-runner.ts # Heartbeat
│   ├── heartbeat-wake.ts # Coalescing
│   └── system-events.ts  # Event queue
├── cron/                 # Scheduled Jobs
│   ├── service/          # CronService (timer, execution, lock)
│   ├── store.ts          # Atomic Store
│   ├── run-log.ts        # JSONL history
│   └── types.ts          # Job types
├── hooks/                # Internal Hooks
│   ├── internal-hooks.ts # Event engine
│   ├── workspace.ts      # 4-location auto-discovery
│   ├── loader.ts         # Hook loading
│   └── bundled/          # 4 bundled hooks
├── skills/               # Skill System
│   └── loader.ts         # 4-tier priority loading
└── config/               # Configuration
    ├── types.hooks.ts    # Hook types
    └── zod-schema.*.ts   # Zod validation
```

---

## Pattern Application Checklist

When applying OpenClaw patterns to GEODE:

- [ ] Session Key: Is a hierarchical key (`ip:{name}:{phase}`) applied to `thread_id`
- [ ] Concurrency: Does it follow the principle of serial by default + explicit parallelism (Send API)
- [ ] Plugin: Can new features be registered without modifying existing code (ToolRegistry)
- [ ] Policy: Is there a policy chain controlling tool access per mode/context
- [ ] Failover: Is there an auto-recovery path when LLM calls fail
- [ ] Coalescing: Is there a mechanism to merge duplicate execution requests
- [ ] Atomic Write: Does state file writing use the tmp+rename pattern
- [ ] Hot Reload: Are config changes reflected without restart
- [ ] Stuck Detection: Are long-running tasks automatically released
- [ ] Run Log: Is execution history recorded in JSONL with auto-pruning

## References

- **OpenClaw full analysis**: `research/openclaw-analysis-report.md`
- **4-tier automation**: `research/openclaw-automation-analysis.md`
- **Routing comparison**: `research/openclaw-routing-analysis.md`
- **Routing diagram**: `diagrams/openclaw-routing.mmd`
