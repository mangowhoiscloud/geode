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
| `native` | Provider officially supports the surface | Enable direct path |
| `emulated` | GEODE can project the feature through local tools | Enable explicit emulation |
| `unsupported` | Provider cannot accept the feature | Return clear unsupported result |
| `live_test_required` | Docs/types are ambiguous | Keep disabled or guarded |

## Required Notes

When changing a provider capability:

- cite the official source or local source file in code comments or docs
- record unsupported models explicitly
- keep subscription backends separate from platform APIs when their contracts
  differ
- do not infer backend acceptance from an SDK union alone
- document any live-test gap in the final report

## GEODE-Specific Surfaces

- PDF/document input: provider file contract, context limits, page range, and
  local extraction fallback.
- GUI/computer-use: screenshot support, coordinate action support, safety
  guard, recovery path, and trajectory evaluation.
- Web/search tools: hosted-tool acceptance and local-tool fallback.
- Model router: source family, selected model, visible tools, and unsupported
  reasons.
