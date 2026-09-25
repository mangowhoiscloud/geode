# Provider Grounding

Use this for OpenAI, Anthropic, Zhipu, Codex subscription routes, browser/OS
automation, PDF input, hosted tools, model availability, or SDK behaviour.

## Source Order

1. Official provider docs
2. Official SDK source or generated types
3. GEODE's existing adapter behaviour and tests
4. Live test, only with explicit user approval
5. Secondary sources, only as context and never as sole proof

## Capability States

| State | Meaning | Runtime behaviour |
|---|---|---|
| `native` | Provider officially supports the surface | Enable the implemented path for the verified model/route and allowed account/tool policy |
| `emulated` | GEODE can project the feature through local tools | Enable explicit emulation |
| `unsupported` | Provider cannot accept the feature | Return clear unsupported result |
| `live_test_required` | Docs/types are ambiguous | Keep disabled or guarded |

## Required Notes

When changing a provider capability:

- cite the official source or local source file in code comments or docs
- record unsupported models explicitly
- establish API, subscription and relay contracts separately; claim sameness
  only where the selected route's primary evidence supports it
- do not infer backend acceptance from an SDK union alone
- document any live-test gap in the final report

## Route and lifecycle boundaries

Record the effective model/provider/source, API surface, source revision or
retrieval date, and unverified account constraints. Distinguish total context,
known input cap, requested output reserve, planning defaults, native compaction
and fallback provenance. Resolve these after request selection; catalog maxima
and relay aggregate metadata are not endpoint admission guarantees.

Trace explicit native-control selections from the UI or persisted configuration
through model/route validation to the actual SDK request; translating a provider
field name must preserve the selected value. Reject unsupported explicit
selections instead of silently substituting, clamping or omitting them.

For cache/pricing changes, follow the existing
[usage contract](../../../../docs/architecture/usage-accounting.md).
Check static-prefix/dynamic-context boundaries, legal marker blocks/count/TTL,
and session-routing identity across client recreation where relevant. Verify
complete and streaming responses against the same usage authority, including
iteration totals and missing detail. Serialization does not prove a cache hit,
TTL billing or savings. Use feature-specific SDK surfaces only for requests
that need them, preserving the ordinary route's compatibility.

For routing changes, use the existing decision owner for configured defaults
and model plans, and pass the same policy sources to affected primary, auxiliary
and resumed consumers; later default changes must not rewrite an admitted
session route. For credential changes, verify the selected account and endpoint
in the actual SDK request while preserving that route, then trace client
creation, use, retirement and owner shutdown, including borrowed resources and
failed cleanup. Reuse
[lifecycle and error conventions](../../../../docs/architecture/naming-conventions.md#33-construction-and-lifecycle);
a session ending does not by itself own shared client teardown.

## GEODE-Specific Surfaces

- PDF/document input: provider file contract, context limits, page range, and
  local extraction fallback.
- GUI/computer-use: screenshot support, coordinate action support, safety
  guard, recovery path, and trajectory evaluation.
- Web/search tools: hosted-tool acceptance and local-tool fallback.
- Model router: source family, selected model, visible tools, and unsupported
  reasons.
