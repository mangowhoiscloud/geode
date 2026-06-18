# Computer-use sandbox (Phase E)

Opt-in isolation for computer-use: instead of pyautogui driving the operator's
real desktop, the GEODE harness becomes a thin HTTP client that dispatches each
action to a container running its own virtual display.

This is the frontier **in-container shim** model (E2B Desktop, trycua) — the
only one that works regardless of host OS. On macOS, Docker is a Linux VM that
cannot reach the host display, so a "host sets `DISPLAY=:99`" model (a prior
plan draft) is physically impossible; the in-container shim sidesteps it because
the host only speaks HTTP.

## Wiring

- Host: `core/tools/computer_use.py` — `aexecute` routes to `_sandbox_execute_sync`
  when `computer_use_env=sandbox`, POSTing `{action, params}` to `<url>/cmd`.
- Container: `shim_server.py` — runs the same `ComputerUseHarness` against the
  container's Xvfb and returns the identical result shape.
- **fail-loud**: if the container is unreachable the action errors; it NEVER
  falls back to the host (opting into isolation must not silently re-expose the
  real desktop).
- **audit safety**: under `GEODE_AUDIT_UNRESTRICTED=1`, computer-use is disabled
  unless `computer_use_env=sandbox` — a Petri audit can never drive the real
  desktop (`core/llm/providers/anthropic.py::is_computer_use_enabled`).

## Run (Linux Docker host)

```bash
docker build -t geode-cu-sandbox -f docker/computer-use-sandbox/Dockerfile .
docker run --rm -p 8787:8787 geode-cu-sandbox
# host:
GEODE_COMPUTER_USE_ENV=sandbox \
GEODE_COMPUTER_USE_SANDBOX_URL=http://127.0.0.1:8787 \
geode
```

## Status

`unverified — live test required`. The host-side client + env branch + fail-loud
+ audit guard are unit-tested (`tests/core/tools/test_computer_use_sandbox.py`).
The actual container round-trip (action → Xvfb → screenshot) needs a real Docker
host and is not exercised in CI. Observation via noVNC is a follow-up.
