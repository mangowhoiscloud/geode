---
title: DESIGN.md · `/geode/self-improving/autoresearch/policies/` (Policies)
geode_version: 0.99.65
schema_version: 1
last_updated: 2026-05-26
applies_to_geode: ">=0.99.65"
parent: self-improving-hub-system.md
---

# DESIGN.md · `/geode/self-improving/autoresearch/policies/` (Policies)

> Read [self-improving-hub-system.md](./self-improving-hub-system.md) first.

## 1. Page purpose

Renders the 14 policy SoT files under `autoresearch/state/policies/`. Each policy is a JSON file that the self-improving loop mutates. This page is the read-side reference: what the live policies *are*, what was last modified.

## 2. Data sources

14 files at `docs/self-improving/autoresearch/policies/`:

| File | Domain |
|---|---|
| `wrapper-sections.json` | Wrapper system-prompt sections (sycophancy_guardrail etc.) |
| `tool-policy.json` | Per-tool allow/deny + parameter constraints |
| `decomposition.json` | Goal decomposition prompt + rules |
| `retrieval.json` | Memory retrieval policy |
| `reflection.json` | Reflection-node policy |
| `tool-descriptions.json` | Per-tool description prose |
| `skill-catalog.json` | Registered skills + triggers |
| `style-guide.json` | Output style rules |
| `provider-routing.json` | LLM provider routing |
| `cache-policy.json` | Prompt-cache policy |
| `heuristics.json` | Ad-hoc heuristics for the loop |
| `in-context-slots.json` | Slot orchestrator config |
| `agent-contracts.json` | Agent contract registry |

## 3. Sidebar `.active`

`Autoresearch > Policies`

## 4. Sections

1. **Policies table** — 14 rows, one per file
2. **Per-file drill-down** (HTML `<details>`) — JSON pretty-printed in `<pre>`

## 5. Policies table columns

| col | source |
|---|---|
| file | filename + `.bucket.autoresearch` chip |
| last write | `os.path.getmtime` formatted |
| size | bytes (human-readable) |
| mutated by gen | last `mutations.jsonl` row with this `target_section` |
| view | `<details>` toggle |

## 6. Drill-down

```html
<details>
  <summary>view JSON</summary>
  <pre class="policy-json">{ ... }</pre>
</details>
```

JSON syntax-highlighting: CSS-only via `<pre>` mono. No JS highlighter.

## 7. Empty state

If `policies/` directory absent or empty: `<em>No policies mirrored yet. Run the autoresearch publisher.</em>`

## 8. Verification checklist

- [ ] All 14 policies render even if some are empty objects
- [ ] Each row links to most-recent mutation in mutations.jsonl that touched it
- [ ] JSON pretty-print works for nested structures
- [ ] Size column human-readable (KB / MB)
