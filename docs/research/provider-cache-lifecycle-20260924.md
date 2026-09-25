# Provider cache lifecycle audit — 2026-09-24

Scope: the shared static/dynamic prompt boundary, provider wire shaping and
logical-session ownership. SDK transport lifetime and provider cache lifetime
are separate. The accompanying TTL/accounting change has its own review unit.

## Primary contracts and implementation

| Route | Source checked on 2026-09-24 | GEODE behavior |
|---|---|---|
| OpenAI Platform | [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) | Registered GPT-5.6/GPT-6 models send the static prefix in developer input_text with an explicit breakpoint; dynamic text follows unchanged. Top-level instructions cannot carry that breakpoint. Implicit conversation caching remains enabled. |
| OpenAI Codex | [Existing route evidence](codex-oauth-request-spec.md) | Retain instructions and the existing cache-key contract; Platform breakpoint acceptance does not establish Codex acceptance. |
| Anthropic | [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) | Reuse the existing system and message cache helpers. Request-wide limits, permitted targets and TTL write accounting are reviewed separately. |
| Z.AI | [Cache capability](https://docs.z.ai/guides/capabilities/cache) | Retain automatic repeated-prefix caching and returned cached-token detail. Do not invent a numeric TTL or forward another provider's markers. |
| OpenRouter | [Cache and routing contract](https://openrouter.ai/docs/guides/best-practices/prompt-caching) | Preserve markers only for explicit supported upstream model routes. Send the logical-session hash as session_id; leave validated provider ordering intact. |

OpenAI's stable cache key alone does not establish an eligible static
breakpoint. OpenRouter's default affinity can depend on the first system
message, which contains changing dynamic context. A session hash keeps the
affinity hint stable across those changes and recreated SDK clients without
sending the raw local identifier. No session means no invented shared ID.
Provider/account namespaces still apply; a hash is an affinity hint, not an
authentication or isolation boundary.

Changes to model, account, tools/order, output schema, reasoning settings or
compacted history can change the rendered prefix. Local client close does
not delete remote cache entries. No process-global response cache, expiry
scheduler or new cache configuration is introduced.

## Evidence and limits

Baseline characterization failed because Platform requests retained the
whole prompt in instructions and OpenRouter requests lacked session affinity.
The revised checks assert exact static bytes across dynamic-tail changes,
legacy/Codex guards, actual SDK wire markers, cache usage and provider cost
preservation, stable session hints after client recreation and different hints
after a logical-session change. HTTPX MockTransport supplies all responses.

Mocked cached-token values prove translation, not a cache hit. Live backend
acceptance, account/model access, provider selection, positive reuse and billed
cost remain part of the separately authorized E2E/Harbor validation after all
implementation is complete. OpenRouter credentials were not available during
the read-only preflight; that route cannot be reported as live-verified.

## Offline integration review — 2026-09-25

Rechecked the three linked OpenAI, OpenRouter and Z.AI primary contracts and
merged the final Claude TTL/accounting candidate before validating K1. The
SDK fixture checks now also cover absent session identity, explicit metadata
precedence, concurrently bound task-local sessions, and retained provider
ordering/fallback policy. Claude route fixtures count the actual serialized
markers with and without a marked static system block over short and longer
histories. They preserve input messages and the request-wide four-marker cap.

These are offline wire and ownership checks. The runner rejects network
connect attempts and access to operator credential files; it does not establish
live API or subscription acceptance, cache reuse, account routing, or charges.
