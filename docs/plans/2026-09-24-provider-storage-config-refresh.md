# Provider, persistence and configuration refresh

## Scope and authority

The operator requested a 2026-09-24 primary-source refresh of OpenAI,
Anthropic and Z.AI API/subscription support, deprecated-surface removal,
model prices/specifications and simple typed adapters. The follow-up extends
the same inspection to DB, trajectory and configuration ownership, with
small reviewed PRs accumulated on `develop`, then a versioned GitFlow
promotion to `main` and a verified release. This authorizes commits, PRs,
CI-gated merges and stable publication. The operator subsequently requested
E2E and Harbor checks for the new model families through both API and
subscription routes after all implementation is complete. The operator
approved a total US$20 paid-validation cap on 2026-09-24; freeze the execution
matrix and budget before calling models. The subsequent operator instruction
requires every implementation PR owned by this refresh to pass its exact-head
CI ratchet and merge into `develop` in dependency order before paid validation.
Freeze that clean, integrated `develop` revision; a local integration candidate
is eligible for offline checks only. Record subscription consumption
separately from API charges. Running services and globally installed tools
remain outside scope.

## Acceptance

- Every current model, price, lifecycle or route claim links to primary
  evidence retrieved on 2026-09-24. Account access remains distinct.
- Picker, login routing and adapters consume one active model offering
  list. Historical evidence is retained; explicit selections never change
  model or billing source silently.
- Provider model records drive request and UI controls. Completion,
  streaming and auxiliary calls preserve supported controls and replay.
- Native computer changes preserve coordinates, action meaning and raw
  protocol history; unsupported actions fail before effects.
- Storage/config cleanup starts with actual producers, persisted fields,
  readers and decisions. Deduplication must preserve transaction, recovery,
  validation, precedence and compatibility behavior.
- Each PR includes narrow regressions, applicable static checks, independent
  review, current main ancestry and exact-head required CI before merge.
- Release version, wheel/sdist contents, generated docs, GitHub/PyPI assets
  and exact-version clean install are verified separately.

## Review units and order

| Unit | Scope | Dependency | State |
|---|---|---|---|
| P1 | Price/context refresh, typed tariff rules, active offering catalogue | none | PR #3395 merged into develop at `7ea17cceb`; required CI passed |
| P2 | OpenAI model/effort/output and API/Codex request boundaries | P1 | PR #3397 merged into develop at `be48160a1`; required CI passed |
| P3 | Claude typed capabilities, thinking, schemas, streaming parity | P2 shared selection helper | PR #3400; required CI in progress |
| P4 | GLM request deduplication, exact effort and subscription admission | P2 shared selection helper | PR #3401; required CI in progress |
| P5 | Native Claude computer toolset and action translation | P3 | local implementation |
| P6 | CLI/default/config selection and bilingual public documentation | P2–P5 | local implementation and independent review |
| S1 | Actual event-schema/digest references owned by the event store | audit | PR #3390, `c4fc65477` required CI passed; current-base integration pending |
| S2 | Runtime-state DB connection ownership, serialized use and teardown | audit | PR #3393, `a98fda9a8` required CI passed; current-base integration pending |
| C1 | Validate complete settings before publishing a reload | audit | PR #3389 merged into develop at `a5b23bdc2`; required CI passed |
| C2 | One global config path for writer, reader, explanation and watchers | C1 | PR #3396, `32e8811cb` required CI passed; current-base integration pending |
| D1 | Bound compatible SDK majors and deduplicate HTTPX construction | independent migration audit | PR #3394, `fb8fdb118` required CI passed; current-base integration pending |
| D2 | Test current major SDK/evaluation compatibility | D1 | incompatible OpenAI/Inspect import reproduced; migration deferred |
| E1 | Runtime construction, shutdown outcomes, request context and cache generation ownership | C1 | PR #3403; required CI in progress; existing error convention extended |
| E2 | Atomic gateway reload and owned watcher/poller lifecycle | C1, C2 | local implementation and independent review |
| E3 | Shared SDK transport ownership at actual process/thread event-loop teardown | E1 | local implementation and independent review |
| K2 | Claude cache marker validity and 1-hour write accounting through durable records | P6 | local implementation and independent review; activity schema v11, trajectory v1 unchanged |
| K1 | OpenAI explicit static prefixes and OpenRouter route/session cache shaping | P6, K2 | local implementation and independent review |
| V1 bounds | Optional Harbor output/round limits and shared wrap-up cap preservation | runtime owners | local implementation and offline verification |
| V1 execution | New-model API/subscription E2E, cache and Harbor validation | all implementation PRs merged into develop with required CI | not started; total US$20 paid cap approved |
| F1 | Repeatable onboarding and audit scaffold in existing contributor skills | completed refactoring and checks | pending; preserve runtime/contributor prompt separation |
| R1 | Patch release preparation, packaging/docs, develop→main, stable publication | all accepted units | pending |

The implementation workspace holds the combined candidate while changes
are tested. Integration PRs are assembled in dependency order; the combined
workspace is not itself one oversized PR. Split a unit further when its
native protocol or persistence contract warrants independent review. The
architecture roadmap remains authoritative for any existing program GAP;
ordinary provider maintenance does not create an unrelated program claim.

The table records observed commit-specific evidence, not permission to reuse
stale checks after a base or head change. Every merge still runs the current
merge guard. API and Subscription are separate validation routes; unavailable
Claude or Z.AI subscription admission remains an explicit rejection test, never
a PAYG substitution. OpenRouter credentials were subsequently supplied for the
scoped validation process and are not stored in repository artifacts.

## Verification record

No successful live inference has been executed in this maintenance work. A
broad test invocation accidentally removed the default live-test exclusion;
one live case failed at adapter dispatch before SDK construction. The
corrected offline run excluded live tests explicitly. Initial narrow checks found old tests
pinning retired picker choices and old context/effort contracts. Update
only assertions whose documented behavior changed and retain route, replay,
credential-isolation and no-silent-fallback checks. Passing local tests are
not remote CI or publication evidence. Final PR/run/release receipts will
be recorded when observed.

## SWE review record

The requested follow-up review uses the repository's convention, dependency,
simple-design and anti-deception lenses. The review follows each changed
producer through its actual consumer and covers both success and failure.

- No new provider hierarchy, generic persistence framework or config store is
  introduced. Model records, event references and the existing config resolver
  are the smallest owners that must change together.
- Price tests preserve free versus missing values, disjoint versus inclusive
  input, aliases, strict long-context thresholds and reported-cost priority.
  The concurrent Jev tariff remains intact after develop integration.
- Settings checks cover failed validation, removal of environment overrides,
  singleton identity, global/project precedence, redirected writes, explanations
  and watcher reloads. A lazy-singleton test fixture was corrected instead of
  suppressing the integration failures it exposed.
- DB connection checks cover construction failure, concurrent close/use and
  normal shutdown. Actual SQLite fault injection found failed writes retained
  in an open transaction and persisted by a later unrelated commit. The shared
  connection boundary rolls those writes back and discards a connection when
  rollback fails. Constructor failure closes its connection. Trajectory
  references do not rewrite stored source events.
- Independent picker review reproduced mismatched routing/settings defaults,
  implicit changes to saved GLM effort on Enter, and GLM rows inheriting the
  OpenAI billing source. Corrections preserve explicit settings and native
  arrow-key choices; plan roundtrips cover absent and explicit legacy quotas.
- API web-search accounting and public Claude streaming lost completed response
  information; provider PRs connect the existing response translators and test
  the actual adapter boundary.
- Latest SDK compatibility is not assumed from model-name support. An isolated
  Inspect 0.3.268 + Anthropic 1.8.0 + OpenAI 2.x probe failed at OpenAI provider
  import. Version bounds retain the verified installation; no dependency
  downgrade, monkeypatch or compatibility shim conceals the failure.
- Retired experimental grounding has no verified model/coordinate contract or
  production caller. Its orphan request path is removed with its obsolete
  parser tests; the no-hidden-billing and unsupported-action checks survive.

These are scoped review findings and local verification results, not a claim
that every repository behavior has passed. Required CI, integrated packaging,
main promotion and distribution receipts remain separate completion gates.

The additional error review follows the operator's lifecycle clarification:
runtime and database creation, publication, use, failure cleanup, shutdown and
recreation. Naming conventions §5 already owns exception naming, narrow catches,
causal chaining and explicit failure results. Extend that owner only for missing
reusable lifecycle rules; introduce a distinct error only when a caller makes a
different recovery decision. Compare relevant current primary agent sources,
then fix demonstrated gaps in E1 without creating a parallel exception framework.
