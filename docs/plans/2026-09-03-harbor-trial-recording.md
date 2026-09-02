# Harbor trial recording reconstruction

## Evidence and gap

- Harbor documents `agent/recording.cast` as an agent-owned trial artifact.
- Harbor 0.22.0 records it in Terminus-2, but neither GEODE's external agent nor
  Harbor's installed Codex agent emits it.
- Both agents already emit timestamped ATIF 1.7 `trajectory.json` files. The
  active frozen comparison therefore must not be re-run or PTY-wrapped merely
  to obtain a replay artifact.

## Decision

Render a Harbor-compatible asciicast v2 file from the existing ATIF trajectory
after the trajectory is finalized. Store it at `agent/recording.cast` and bind
it to the source trajectory with `agent/recording.receipt.json`.

This is a trajectory reconstruction, not a raw terminal capture. It omits
reasoning content, redacts known secret forms, requires a separate PII/public
review, and has no score authority. Existing native recordings are never
overwritten by default.

GEODE writes the replay after its ATIF export. A thin Codex instrumentation
subclass writes it after Harbor's native Codex converter. The same renderer has
a dry-run/backfill command for closed historical jobs.

## Acceptance

- asciicast v2 JSONL validates and preserves monotonic ATIF-relative timing;
- commands, observations, and final responses are replayable without provider
  reasoning;
- receipt hashes bind source and output and state the reconstruction boundary;
- malformed or missing trajectories fail closed and existing casts remain
  untouched;
- targeted tests plus ruff and mypy pass without a paid or live benchmark run.

## Primary sources

- [Harbor job output layout](https://www.harborframework.com/docs/run-jobs/run-evals)
- [Harbor 0.22.0 Terminus-2 source](https://github.com/harbor-framework/harbor/blob/v0.22.0/src/harbor/agents/terminus_2/terminus_2.py)
- [asciicast v2 format](https://docs.asciinema.org/manual/asciicast/v2/)
