# Slack Socket Mode runtime hardening

Status: IMPLEMENTED — local verification complete
Date: 2026-08-15

## Question

What is the smallest change that makes GEODE's existing Socket Mode receiver
robust against the failures observed in `~/.geode/logs/serve.log`, without
adding a second gateway queue or state authority?

## Grounding

- Slack requires acknowledgement by `envelope_id`, refreshes WebSocket URLs
  every few hours, and documents `warning`, `refresh_requested`, and
  `link_disabled` disconnect reasons in its
  [Socket Mode protocol](https://docs.slack.dev/apis/events-api/using-socket-mode/).
- GEODE logs contained repeated `too_many_websockets` disconnects followed by
  immediate reconnects. The current frame handler treated every disconnect as
  a healthy refresh and skipped the existing exponential backoff.
- [Hermes at `5fffe560`](https://github.com/NousResearch/hermes-agent/blob/5fffe560661c87d988c4ef2834df14bfb8acba55/plugins/platforms/slack/adapter.py)
  uses a one-hour, size-bounded Slack dedup window after observing reconnect
  redelivery beyond the previous 300-second window. Its additional watchdog is
  specific to the Slack SDK client; GEODE's raw `websockets` loop already owns
  receive timeouts, ping/pong, reconnect, and shutdown.
- [Codex app-server](https://github.com/openai/codex/blob/23094236acac6fdc22f67a408ea8ccb8fac8e6e1/codex-rs/app-server/README.md)
  and its [rollout recorder](https://github.com/openai/codex/blob/23094236acac6fdc22f67a408ea8ccb8fac8e6e1/codex-rs/rollout/src/recorder.rs)
  demonstrate the stronger long-term model: stable submission identity plus
  persisted thread/turn admission. GEODE does not currently have an approved
  gateway-inbox owner, so adding one here would duplicate session/checkpoint
  authority rather than harden the existing transport.

## GAP and decision

- Keep immediate reconnect for the existing scheduled `warning` and
  `refresh_requested` paths.
- Route every other disconnect reason through the existing 1–30 second
  exponential backoff.
- Reject an `events_api` envelope without `envelope_id`; it cannot be
  acknowledged safely.
- Extend dedup from 300 seconds to one hour and cap it at 5,000 entries.
- Keep the ACK-to-handler crash window as an explicit ceiling. Register a
  measured persistence GAP before adding a durable inbox or changing authority.

## Affected scope

- `core/messaging/slack_socket_mode.py`: disconnect classification and
  fail-closed envelope admission.
- `core/server/supervised/slack_poller.py`: bounded one-hour duplicate
  suppression.
- The two existing Slack Socket Mode test modules: protocol, reconnect,
  long-redelivery, and cache-bound regressions.

No dependency, public configuration, outbound Slack transport, session key,
lane policy, or persistence owner changes.

## Verification

- Targeted Slack Socket Mode and receiver tests — PASS (38).
- Touched-file Ruff check and format check — PASS.
- Touched-module mypy — PASS.
- All Slack, gateway, and adjacent hardening tests — PASS (164).
- Import contracts and generated architecture baseline — PASS.
- Live Slack traffic — not run; requires explicit approval.
