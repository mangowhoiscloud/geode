# Runtime simplicity audit — 2026-10-14

## Scope and verdict

GEODE has concrete complexity that does not earn its place: duplicated login
flows, implicit permission promotion, and accepted configuration fields without
a consuming decision. This is evidence for bounded simplification, not a claim
that the whole runtime is nonfunctional or that file counts measure quality.

Audited base: `9255529ae89d2c40f723f30445c0d49a3de3c48f` on fetched
`origin/develop`. Local candidate: `codex/runtime-simplicity-20261014`.
Inspection covers credential onboarding, auth recovery guidance, approval
serialization and selected opt-in policy-injection fields. This is not an
exhaustive codebase or security audit. Existing worktrees were preserved.

The useful boundary is the user's decision: choose a credential route once,
save through the existing owner, and expose the resulting state. Authentication,
permission decisions and operating-system confinement are distinct concerns.
Flattening the menu does not require collapsing their enforcement.

## Frontier evidence

REA 6.4.0 captured the installed CLIs through a PTY; only help and version
commands were executed. No login, paid model call, credential extraction,
process injection or service restart was performed.

| Observation | Artifact / evidence | Established limit |
|---|---|---|
| Codex help and login help | Installed `codex-cli 0.157.0`; executable SHA-256 `ad0be20d04e2ba6146ecdb51d7f8b7b0fe15420a15dc9b0057518d858f1f3714`; REA `ev_e79f0e0c0b06b6b08b0d7f3a082b661c56df9c17b431273bdad9fba49348eeb4`, `ev_223b64d871d3f274aa1d1c45402e6dce7089910320b94af16c4a79e65409ec6e` | Advertised login entry point, stdin credential options, approval/sandbox options; not authentication success or internal implementation. |
| Claude help and auth help | Installed `2.1.290`; executable SHA-256 `b8412a3826b2dc8ecb1c0605970c28dea28355de5faa740407dd881acdd40237`; REA `ev_6985e17ebe8992c116922ad951ce50b6253bc1947231ae489952e6d51b4cce1e`, `ev_7ec1f349f800bc0a98512f300562987fcc534e9ebf18c95624d9f4c1ba3a8d09` | Auth login/logout/status and permission modes are visible. Some rendered help frames were omitted by the output budget; raw PTY output remained available. |
| GEODE help | Local source at audited base; REA `ev_9066451e3ea0e2c276398a687a834bd99faa553b6e421caceeade456a44d579b` | CLI surface only. Interpreter/entry-point digest is not a digest of the whole Python source tree. |
| GEODE revised login menu | Local candidate; REA `ev_413e5389302ba96673598edb37f4ff9b7c94078e83bb48fc98ff534a2c026bdf` | Five credential routes rendered; `q` cancelled. GEODE_HOME was isolated and four provider key variables cleared. No key was entered. |

REA process evidence is `controlled-replay`. It samples executable bytes before
launch and reports unknown ambient environment/filesystem effects. It does not
prove atomic OS image binding, whole-runtime reconstruction, or source/binary
equivalence. The local exported bundle is under
`artifacts/runtime-simplicity-20261014/rea-evidence.json` (gitignored).

Public upstream source was inspected separately from those installed binaries:

- Codex default-branch SHA:
  [`4906ddf5b80d4cf4e54ac1a22dc000c389835e9c`](https://github.com/openai/codex/commit/4906ddf5b80d4cf4e54ac1a22dc000c389835e9c).
  Retrieved stable tag: `rust-v0.162.1`; prerelease: `rust-v0.163.0-alpha.11`.
  These are not the installed binary version above.
- Claude Code public repository SHA:
  [`9b4f0d6ef8ceaf62f6b46babb9a4d84bec541a2e`](https://github.com/anthropics/claude-code/commit/9b4f0d6ef8ceaf62f6b46babb9a4d84bec541a2e),
  latest release `v2.1.299`. Runtime behavior beyond the CLI capture is grounded
  in official documentation, not recovered proprietary source.

| Mechanism | Primary source | GEODE decision |
|---|---|---|
| Direct login dispatch after method selection | [Codex CLI](https://github.com/openai/codex/blob/4906ddf5b80d4cf4e54ac1a22dc000c389835e9c/codex-rs/cli/src/main.rs#L1621-L1651) | Adapt: remove the extra kind/provider menu in `/login add`. |
| Serialized refresh, reread stored auth, preserve account identity | [Codex AuthManager](https://github.com/openai/codex/blob/4906ddf5b80d4cf4e54ac1a22dc000c389835e9c/codex-rs/login/src/auth/manager.rs#L2841-L2878) | Preserve GEODE transaction, ownership and client invalidation boundaries; no new auth layer. |
| Read Only / Default / Full Access presets retain approval and permission fields | [Codex presets](https://github.com/openai/codex/blob/4906ddf5b80d4cf4e54ac1a22dc000c389835e9c/codex-rs/utils/approval-presets/src/lib.rs#L8-L60) | Candidate UX grouping; no permission widening in this patch. |
| Sandbox auto-allow retains scoped ask and deny | [Claude permissions](https://code.claude.com/docs/en/permissions#how-permissions-and-sandboxing-work-together) | Preserve enforcement; reduce only duplicated decisions with an actual enforcing owner. |
| Credential precedence remains complex; status explains selected and unused credentials | [Claude authentication](https://code.claude.com/docs/en/authentication#authentication-precedence) | Prefer an accurate effective-state view over copying more fallback layers. |

## Findings and dispositions

### Implemented locally: login choices and key entry

Before: `onboarding._wizard_api_key_path` prompted for Anthropic, OpenAI and
GLM in sequence and omitted OpenRouter. `/login add` separately asked kind,
then provider, then a key. Direct Anthropic login duplicated hidden input.

After: `/login add` presents ChatGPT subscription or one of four API-key
providers in one menu. Setup retains its explicit subscription/API-key/dry-run
choice, then asks for one provider and one key. All three key-entry routes use
`core/cli/commands/login.py::prompt_api_key` and the existing
`core/auth/auth_toml.py::save_api_key` owner. Run `/login add` again for more
providers. Existing aliases, plan selection and billing-source semantics remain.

The tests preserve hidden input, validated atomic persistence, owner-only file
mode, active profile publication, cancellation and existing credentials. No
credential schema, refresh protocol, permission policy or provider adapter was
replaced. This intentionally changes the interaction from a three-provider batch
to one selected provider per registration; it preserves multi-provider support.

### Implemented locally: cancelled approval waiter

`ApprovalWorkflow._with_approval_locks` previously awaited a blocking
`threading.Lock.acquire` through `asyncio.to_thread`. Cancelling the awaiting
task did not stop the worker: it could later acquire the lock without releasing
it, leaving subsequent approvals waiting indefinitely.

The shared acquisition is now shielded and a cancelled waiter releases a late
grant. The regression calls the real async approval entry, cancels while queued,
checks that its prompt never ran, then completes a subsequent approval. The old
code failed this test with `TimeoutError`. Sync API compatibility remains.
Cancellation during an already-running blocking prompt is a separate lifecycle
problem and is not claimed solved here.

### Open: approval frequency silently changes permission

`core/agent/approval.py::track_decision` promotes three `y` decisions into
`_always_approved_tools`; `_auto_grant_reason` / `is_bash_auto_approved` consume
that state. This is tool-wide rather than bound to the three approved commands.
An offline callback reproduction confirmed a later unrelated write was then
auto-approved. There is already an explicit `a` choice.

Recommendation: remove implicit promotion and preserve explicit `a`, scoped
denials, per-invocation sensitive-data consent and sandbox enforcement. This
changes existing approval semantics, so it is recorded separately from the
behavior-preserving cancellation fix. Required oracle: fourth `y` request still
asks; explicit `a` retains the documented scope. Unchanged in this candidate.

### Open: accepted settings without a consuming decision

`InContextSlot.rank_by` and `injection_point` are accepted fields, including
`tool_descriptions`, but the inspected consumers in
`core/agent/policy_injection/in_context_wiring.py` use fixed ranking and prepend
tool hints to system text. The actual fields read are chiefly `max_entries`.
This is opt-in middleware, not proof of overhead on every normal turn.

Recommendation: retire unsupported choices with compatibility handling for
existing policy files; do not implement a generic injection framework merely
to justify the knobs. Required oracle: existing supported output remains and
unsupported settings no longer imply behavior they cannot select.

### Open: auth recovery text and reset semantics

- `/login health` and `credential_breadcrumb.py` suggest plan `use` as a
  cross-provider fix. `_login_use` only changes routing for the plan's own
  provider; `manage_login use` does not switch the current session model.
  Point cross-provider recovery to the existing model-selection path instead.
- Expired OAuth health guidance only recommends external `codex login`, while
  GEODE-native OAuth is stored independently. Native versus imported credential
  recovery should be distinguished, as the existing breadcrumb already does.
- `core/cli/typer_commands.py::setup(reset=True)` unlinks the entire global
  `.env`, even though registered credentials now live in `auth.toml` and `.env`
  may contain unrelated integrations. No reset was executed during this audit.
  Define a narrow reset contract and test unrelated-key preservation before
  changing deletion behavior; do not expand deletion to all auth.toml contents.

### Defer: sync approval branch removal and a Rust rewrite

The inspected runtime calls async approval methods; sync public methods and
some source-text tests remain. Test-only visibility does not establish absence
of external consumers. Move surviving behavioral oracles to async entries and
confirm compatibility before deleting those methods.

No measured latency, memory, packaging or concurrency evidence justifies a full
Rust rewrite. The inspected Codex Rust source also retains separate auth manager,
storage, refresh and policy responsibilities. Keep the Python credential and
tool contracts; consider a bounded Rust component only for a measured remaining
bottleneck with the same behavioral oracle. No binary decompilation or complete
runtime reconstruction is claimed.

## Verification

- Targeted login/startup/approval/consent/skip-permission/processor suites:
  **292 passed**, exit 0. Exact commands, results and six file SHA-256 values
  are preserved in `artifacts/runtime-simplicity-20261014/verification.json`.
- Ruff check passed for all six changed Python files; mypy passed for the three
  changed production files; import-linter kept all seven contracts.
- REA rendered the revised real terminal menu and observed cancellation.
- Public auth documentation and `[Unreleased]` were updated. Generated mirrors
  are refreshed through the existing site scripts.
- Site build, changed-page ESLint, docs navigation/export tests, and internal
  link validation passed. The built auth HTML contains both updated language
  branches; the generated Markdown twin contains the revised login description.
- An independent reviewer inspected the six exact source/test digests and their
  direct callers, then ran the approval/login/startup subset successfully.
  No introduced correctness regression was found in that bounded review.
- The initial architecture baseline check correctly reported changed source/test
  line counts. `scripts/architecture_baseline.py --update` completed with only
  core/test LOC changes in the generated JSON and roadmap block; no roadmap
  package status changed. Runtime source is 27 lines smaller across the three
  changed production files. Tests and documentation grew to retain the checks
  and research evidence; total repository diff is not a net deletion.
- A separate reviewer checked the frontier section against the collected primary
  sources and found no actionable claim errors. Render-gated Markdown lint passed.

No paid provider calls, OAuth round trip, full suite, benchmark, protected-branch
merge, release, reinstall or runtime restart was performed. Offline checks do
not establish provider acceptance or end-to-end task performance.
