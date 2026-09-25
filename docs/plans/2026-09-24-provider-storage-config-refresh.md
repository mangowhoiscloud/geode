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
| P3 | Claude typed capabilities, thinking, schemas, streaming parity | P2 shared selection helper | PR #3400 merged into develop at `1e419af4d` |
| P4 | GLM request deduplication, exact effort and subscription admission | P2 shared selection helper | PR #3401 merged into develop at `88b2385a4`; required CI passed |
| P5 | Native Claude computer toolset and action translation | P3 | PR #3407 merged into develop at `39b0f6ba0`; required CI passed |
| P6 | CLI/default/config selection and bilingual public documentation | P2–P5 | PR #3408 merged into develop at `2a074aaed`; required CI passed |
| S1 | Actual event-schema/digest references owned by the event store | audit | PR #3390 merged into develop at `0f3d88fe0` |
| S2 | Runtime-state DB connection ownership, serialized use and teardown | audit | PR #3393 merged into develop at `e0c982f50` |
| C1 | Validate complete settings before publishing a reload | audit | PR #3389 merged into develop at `a5b23bdc2`; required CI passed |
| C2 | One global config path for writer, reader, explanation and watchers | C1 | PR #3396 merged into develop at `3436579dc` |
| D1 | Bound compatible SDK majors and deduplicate HTTPX construction | independent migration audit | PR #3394 merged into develop at `4b414c63a` |
| D2 | Test current major SDK/evaluation compatibility | D1 | incompatible OpenAI/Inspect import reproduced; migration deferred |
| E1 | Runtime construction, shutdown outcomes, request context and cache generation ownership | C1 | PR #3403 merged into develop at `f44cdbf5c`; existing error convention extended |
| E2 | Atomic gateway reload and owned watcher/poller lifecycle | C1, C2 | PR #3410 merged into develop at `1decea9ba`; required CI passed |
| E3 | Shared SDK transport ownership at actual process/thread event-loop teardown | E1 | PR #3411 merged into develop at `93532f825`; required CI passed |
| K2 | Claude cache marker validity and 1-hour write accounting through durable records | P6 | PR #3412 merged into develop at `37138a82d`; required CI passed; activity schema v11, trajectory v1 unchanged |
| K1 | OpenAI explicit static prefixes and OpenRouter route/session cache shaping | P6, K2 | PR #3413 merged into develop at `99e897f70`; required CI passed |
| MCP | Preserve connection and subprocess ownership across creation and cleanup failures | existing runtime audit; queued after K1 | PR #3414 merged into develop at `780992e08`; required CI passed |
| TQ | Strengthen test outcome oracles and remove an identical duplicate | existing quality audit; queued after MCP | PR #3415 merged into develop at `edc0ca901`; all ten required checks passed |
| grill ownership | Move daemon skill-prompt builders from CLI to runtime skills owners | existing dependency audit; queued after TQ | PR #3416 merged into develop at `0fd68aaa9`; all ten required checks passed |
| V1 bounds | Optional Harbor output/round limits and shared wrap-up cap preservation | runtime owners | PR #3404 merged into develop at `3e6e5d988` |
| CI-1 | Conservative document-only full-test selection | existing CI gates | PR #3405 merged into develop at `ebeee591d` |
| CI-2 | Fail closed on invalid comparison refs; enforce locked dependency installation | CI-1 | PR #3406 merged into develop at `6aaaf796d`; required CI passed |
| CI-3 | Four complete, disjoint test shards and combined coverage gate | CI-2 | PR #3409 merged into develop at `0ae4705f6`; required CI passed |
| Compaction | Route-aware context admission, overflow recovery, next-turn task state and public-hook read-only/re-entry/persistence/cancellation contracts | runtime and hook owners | PR #3417 merged at `6cb71da02`; evidence and auxiliary-input follow-ups #3418 and #3420 merged at `580927e1a` and `54ed9cf78` |
| Readiness | Recognize actual OAuth runtime readiness without overriding explicit audit policy | V1 observations | PR #3419 merged at `cf5851dcd` |
| Relay completion | OpenRouter text completion and preserved native effort through auxiliary calls | V1 observations | PR #3421 merged at `567755848` |
| Effort fidelity | Preserve supported selections and reject unsupported values before client construction | actual request audit | PR #3422 merged at `cbb4e33bf`; supported-choice UI #3424 merged at `43ce8e827` |
| Relay sampling | Omit unsupported default temperature for known OpenAI reasoning relay requests | actual failed request | PR #3423 merged at `8d525ca83`; sole cause of the observed endpoint rejection still requires live confirmation |
| Probe identity | Bind resumed checks to route, endpoint and source; observe actual OpenRouter Chat serialization | verification tooling audit | PR #3425 merged at `a22bc119d`; forty targeted checks and required CI passed |
| Session application | Coherent initial/explicit model policy, actual-state ACK and session-local consumers | IPC and runtime counterexamples | PR #3428 open; three stale CI test contracts corrected with 23 passing adjacent checks; new-head remote CI pending |
| Auth persistence | Pin/order persistence and file-owned removal without mutating borrowed credentials | auth serializer/consumer counterexamples | PR #3426 merged at `89f9a9579`; 185 targeted checks and required CI passed |
| Credential adoption | Explicit API-key choices reach actual SDK requests and retained adapter generations | Auth persistence | PR #3427 merged at `abfcf05db`; all ten required checks passed on `bd99842bf`, ordered merge parents verified |
| Configuration authority | One shallow source/account decision owner and shared config reads; remove duplicate parsing, unused drift and hidden PAYG fallback | Credential adoption and Session application | implementation in owned `codex/config-authority-20260925`; Codex/Hermes/OpenCode source grounding completed; not merged |
| Resume | Restore the admitted nonsecret session policy through IPC, gateway and worker callers | Session application and Configuration authority | implementation in owned `codex/session-resume-policy-20260925`; invalid-present and absent legacy records remain distinct; not merged |
| V1 execution | New-model API/subscription E2E, cache and Harbor validation | final implementation PRs merged into develop with required CI | selected earlier-source runs complete; final-source follow-ups pending; total US$20 paid cap unchanged |
| F1 | Repeatable onboarding and audit scaffold in existing contributor skills | completed refactoring and checks | local preparation reviewed; added dated DeepSeek Harness, Google AX and Grok Build research references and version/responsibility follow-up; final integration pending |
| Report | Reconcile all session changes with the existing report and update stale or missing content, including OpenRouter and compaction; exclude Jev | Compaction and V1 execution | pending separate feature PR; publication through main Pages |
| R1 | Patch release preparation, packaging/docs, develop→main, stable publication | all accepted units, including Report | pending |

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

## Integration queue

At develop `39b0f6ba0` on September 25, the original seven-PR queue is
merged: P3 (#3400) → D1 (#3394) → C2 (#3396) → E1 (#3403) → S1 (#3390) →
S2 (#3393) → V1 bounds (#3404). CI-1 (#3405) then added conservative
document-only full-test selection. CI-2 (#3406) hardened failure and dependency-lock
contracts; P5 (#3407) connected native computer actions. The following integration
order was P6 → E2 → E3 → K2 → K1. Keep audit-confirmed CI and runtime defects in small,
separate PRs before freezing final V1 inputs. This is a single integration
queue operated under the existing [GitFlow manual](../../.agents/skills/geode-gitflow/SKILL.md),
not a change to GitHub protection settings or a new merge-queue service.

At develop `abfcf05db`, the original provider, lifecycle, cache, compaction and
CI units and PRs #3418–#3427 are merged. The remaining implementation queue is
session application (#3428), shared config/source authority, then checkpoint/worker resume.
Remove redundant resolvers, repeated TOML reads and unused drift options while
preserving actual selection and lifecycle tests. Keep
these as cohesive review units; fixing one model picker alone does not close
the client/daemon contract. Final source freeze and selected V1 follow-ups
precede F1, Report and R1.
The separate Report feature follows V1 observations and must precede R1. Review
all session changes against the report, including OpenRouter; the ACT3 page 34
update and two added compaction pages do not limit that scope. Jev belongs to a
separate report. No report content is implemented by this integration.
The operator's September 25 compaction follow-up was implemented before V1.
Subsequent live observations produced the bounded readiness, auxiliary-context,
relay and effort corrections above. Each passed required CI before its develop
merge; earlier-source results are not silently promoted to the latest source.
Compare pinned Codex and Hermes sources, xAI's public contracts, and primary
long-context research. Distinguish documented model/API/subscription limits
from account admission and unavailable proprietary harness details.

The compaction work reproduced and corrected two offline counterexamples:
a confirmed provider overflow below the local estimated critical threshold
skipped compaction, and successful token reduction with unchanged message count
was treated as failed recovery. Its acceptance covers bounded recovery and useful task-state preservation
in the actual next request, including constraints, causal tool pairs, and
checkpoint/resume behavior; a smaller transcript alone is insufficient. Audit
public-hook read-only behavior, duplicate/re-entrant dispatch, and the distinction
between artifact persistence, session commit and cancellation before claiming
successful compaction.

- Freeze waiting feature heads after their scoped fixes finish. Update only
  the next PR against the fetched develop base; do not refresh all waiting
  branches after every merge. Finish already-running checks and retain their
  exact source identities without treating old green results as current.
- Fix a defect in its original owner PR and propagate that commit through
  dependencies. Review the actual combined diff; do not apply the same patch
  independently to several branches or use commit counts as content proof.
- Close a failure with its cause, smallest regression and affected consumer
  checks. Reuse unchanged local evidence; rerun changed boundaries and the
  mandatory remote checks. External-service failures retain the failed attempt
  and may be rerun after diagnosis, without removing the check or changing its
  acceptance criteria.
- Admit one merge only after current main ancestry, latest-base compatibility,
  exact-head required CI and the existing merge guard pass. Verify the two
  ordered parents in the receipt before advancing the queue. No bypass,
  squash, rebase, direct protected-branch push or standalone main sync PR.
- Complete integrated develop verification before paid V1. Final scaffold
  closure and release preparation follow their own review gates; no unreviewed
  fixes enter main through a release-only bypass.

The quality criteria follow [Google's review standard](https://google.github.io/eng-practices/review/reviewer/standard.html)
and [small change guidance](https://google.github.io/eng-practices/review/developer/small-cls.html):
cohesive changes, evidence of improved code health and concrete review findings,
without speculative perfection work. [GitHub's strict-check contract](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches#require-status-checks-before-merging)
requires an up-to-date base; the queue limits redundant updates while preserving
that requirement. These references do not imply external certification.

## Verification record

The initial offline stage had no successful live inference. A broad test
invocation accidentally removed the default live-test exclusion;
one live case failed at adapter dispatch before SDK construction. The
corrected offline run excluded live tests explicitly. Initial narrow checks found old tests
pinning retired picker choices and old context/effort contracts. Update
only assertions whose documented behavior changed and retain route, replay,
credential-isolation and no-silent-fallback checks. Passing local tests are
not remote CI or publication evidence.

Later source-bound measurements include successful Astra/Sol/Luna subscription
E2E, Astra/Sol native Harbor tasks, and one Sol subscription compaction
diagnostic. Luna Harbor also has a valid semantic failure; keep its native
verifier outcome despite a model judge's false acceptance. These bounded
observations do not establish model rankings or universal provider support.
OpenRouter compaction attempts hit credit and endpoint admission failures;
retain their invalid/unknown classifications and fresh replacement lineage.
Historical cache responses retain their raw observations even where export
metadata prevented promotion of the selected result. Prepared cache candidates
are not executed measurements. Direct OpenAI/Anthropic/Zhipu credit failures
remain unverified paths until authorised funded calls succeed. The later
OpenRouter US$5 top-up does not expand the existing total US$20 campaign cap.

Final publication must bind its claims to the eventual integrated source,
native results, complete usage and verifier receipts. Main promotion, public
report readback, package publication and installed-version verification remain
separate pending gates. The Jev owner receives the final validated-main
handoff afterward and retains its own implementation, experiment and film queue;
this refresh neither claims those results nor inserts Jev into the GEODE report.

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
