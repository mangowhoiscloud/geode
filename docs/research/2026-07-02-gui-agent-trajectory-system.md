# GUI Agent Trajectory System

Date: 2026-07-02

## Goal

Build the next computer-use layer for GEODE around three durable facts:

- observe the current GUI as a structured screen observation;
- recover from GUI failures by re-observing or escalating, not by generic tool fallback;
- evaluate GUI work from deterministic trajectory rows.

This is intentionally not a semantic screen model. GEODE should not invent a
DOM-like abstraction for arbitrary desktop apps until there are multiple live
consumers that need it.

## Official Provider Grounding

### OpenAI

Official source: <https://developers.openai.com/api/docs/guides/tools-computer-use>

OpenAI's current Responses API computer-use surface is `tools: [{ "type":
"computer" }]`. The model emits `computer_call` items with batched `actions[]`.
The harness executes all actions in order and returns a `computer_call_output`
whose output is a screenshot. The official action set is click, double click,
scroll, type, wait, keypress, drag, move, and screenshot.

GEODE already maps this batched action surface into the local `computer` tool.
This PR adds trajectory events and metrics to that batch result.

### Anthropic Claude

Official source:
<https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool>

Claude computer use is a beta tool contract. Current models use
`computer_20251124` plus the `computer-use-2025-11-24` beta header. The tool
definition carries display dimensions and the provider owns the input schema.
The application supplies a sandboxed desktop/VM/container, executes tool_use
actions, and returns screenshots as `tool_result` image content.

GEODE already injects the Anthropic tool definition and serializes computer
results as image blocks. This PR adds structured observation metadata to the
same result without changing the image path.

### Z.ai / Zhipu

Official sources:

- <https://docs.z.ai/guides/vlm/glm-5v-turbo>
- <https://docs.z.ai/api-reference/llm/chat-completion>
- <https://docs.z.ai/guides/capabilities/function-calling>
- <https://docs.z.ai/guides/vlm/autoglm-phone-multilingual>

Z.ai does not expose an OpenAI/Anthropic-style desktop `computer` tool in the
chat docs. GLM-5V-Turbo supports multimodal visual grounding through image
input plus text instructions; tool calling is JSON-schema function calling.
AutoGLM Phone is an Android/ADB GUI automation framework, not a generic desktop
computer-use API.

GEODE's Zhipu path should therefore remain a grounding/data producer:
screenshot + instruction -> bbox/click point. It can attach a grounding box to
`ScreenObservation`, but the desktop actuation still belongs to the existing
computer harness.

## Desktop Control Readiness

The current harness is not browser-only:

- host mode uses `pyautogui` mouse, keyboard, and screenshots against the whole
  OS display;
- sandbox mode dispatches the same action vocabulary to a container shim that
  drives its own Xvfb desktop;
- actions are coordinate/keyboard primitives, so they can target Finder, system
  settings, VSCode, terminal emulators, browser windows, and arbitrary GUI apps
  if the desktop is visible.

What is missing for robust general desktop control:

- live container E2E for action -> Xvfb -> screenshot;
- desktop profile setup: installed apps, display manager, fonts, clipboard,
  window manager, and stable startup state;
- application/window metadata, OCR/accessibility extraction, and active-window
  signals;
- deterministic trajectory contracts for replay/eval;
- bounded GUI recovery policy.

This PR addresses the deterministic trajectory contract and keeps the execution
surface generic enough for non-browser GUI apps. It does not add OCR, accessibility
tree capture, or app-specific controllers.

## Subscription Backend Emulation

OpenAI Platform can use the native Responses `computer` tool, but the ChatGPT /
Codex subscription backend rejects that hosted tool type. GEODE therefore keeps
the native `computer` path disabled for the Codex backend and exposes a separate
normal function tool, `computer_use`, only when the active route is OpenAI
subscription and computer-use is enabled.

The emulated path deliberately differs from native computer-use:

- it is a JSON function tool, not a hosted provider computer tool;
- raw screenshot base64 is stripped from tool results so normal function output
  does not explode context or replay as a native `computer_call_output`;
- `capture` returns compact observation metadata;
- `locate` uses the API-based GLM-5V grounding helper to turn a visual target
  description into target-space coordinates;
- click/type/key/scroll/drag actions reuse the existing host/sandbox
  `ComputerUseHarness`;
- the same HITL and headless denylist gates apply as for native `computer`.

This is an interoperability layer, not a full SOM/AX screen model. Hermes'
`cua-driver` design remains the stronger next step for robust desktop use:
structured AX/SOM element indices, app/window narrowing, stale element
detection, and richer auxiliary vision summaries.

## PR Boundary

Added:

- `ScreenObservation`: screenshot hash/ref, target size, screen size, env,
  driver, desktop surface, optional cursor/grounding metadata.
- `ComputerActionEvent`: redacted action params, status/error kind, recovery
  hint, observation reference.
- trajectory metrics: total/success/failure/observed actions, final screenshot
  availability, unknown actions, out-of-bounds coordinate count.
- transcript-safe `gui_step` lifecycle rows.
- `computer` exclusion from generic adaptive recovery.

Deferred:

- semantic UI element model;
- OCR/accessibility tree providers;
- `cua-driver`/SOM/AX backend for the emulated function path;
- planner changes;
- OSWorld adapter;
- live Docker/noVNC desktop E2E.

## Eval Direction

The first deterministic checks are local and provider-neutral:

- every successful computer action returns a screenshot observation;
- final OpenAI batched result always carries a screenshot for the next model
  turn;
- text typed by the model is redacted from trajectory rows;
- unknown actions surface as errors, not silent skips;
- sandbox failures escalate and never fall back to host execution;
- coordinates can be flagged when outside the harness target size.

Once this schema has live desktop runs, OSWorld-style replay/eval can read the
same rows instead of requiring a second trajectory format.

## GEODE Capability/Evidence Runtime

GEODE's distinct layer is not long-term chat memory or raw replay. It is a
provider-aware evidence runtime:

- `CapabilityGraph` projects the active model, provider, source, visible tools,
  and GEODE harnesses into a compact support matrix.
- `TaskPreflight` classifies the user request before the first LLM turn and
  records recommended tools plus required evidence classes.
- `EvidenceLedger` appends compact JSONL rows for preflight and final outcomes
  using the same Tier-1 event envelope (`ts`, `seq`, `session_id`, `component`,
  `level`, `event`, `payload`), redacting secrets and hashing payloads.
- `evaluate_trajectory` scores GUI action rows for observation coverage,
  failures, coordinate sanity, and final screenshot availability.

Official grounding:

- OpenAI documents function tools as application-executed JSON-schema tools and
  the hosted Responses computer-use flow as action batches followed by a returned
  screenshot.
- Anthropic documents client tools, server tools, and the computer-use tool as a
  client-executed desktop control surface.
- Z.ai documents GLM function calling and GLM-5.1 as a text model with 200K
  context and tool invocation support; GEODE still treats Z.ai desktop use as
  grounding/data production rather than a provider-native computer tool.

This gives GEODE a concrete operating style: before acting, it explains which
route is available; while acting, it records the evidence class; after acting,
it can evaluate the trajectory without trusting model prose.
