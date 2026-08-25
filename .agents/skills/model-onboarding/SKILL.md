---
name: model-onboarding
description: Add or update a GEODE model or provider from current primary documentation and repository call-site evidence. Use for model IDs, context limits, pricing, reasoning controls, provider routes, capability gates, or fallback changes.
---

# Model Onboarding

Do not maintain a model catalog in this skill; it becomes stale faster than the
runtime. Establish the current contract for every change:

1. Read `AGENTS.md`, then `core/llm/`, provider adapters, configuration,
   capability gates, model selection UI, pricing/context accounting, and their
   tests. Search for every occurrence of the affected model or provider.
2. Verify unstable facts against the provider's current primary documentation:
   exact model ID, API surface, context/output limits, supported controls,
   authentication route, retirement date, and pricing when cost accounting is
   affected. Record the source and retrieval date in the PR.
3. Separate model capability from account policy and route availability. Do
   not infer support from a similar model name or an SDK type alone.
4. Add the smallest characterization that fails on a stale ID, missing
   capability, or wrong route. Run provider tests without live calls; live or
   paid probes require explicit user approval.
5. Update `CHANGELOG.md` and user-facing model docs when behavior changes, then
   follow the repository workflow and GitFlow gates.

Credentials come only from the existing provider configuration path. Never ask
for, print, commit, or copy API keys, OAuth tokens, or credential files into a
prompt, test fixture, log, PR, or research note.
