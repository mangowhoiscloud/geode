"""Remove private reasoning and host-home paths from an Inspect archive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_DROP = object()


def sanitize(value: Any, stats: dict[str, int], host_home: str) -> Any:
    if isinstance(value, dict):
        if value.get("type") == "reasoning":
            stats["reasoning_blocks"] += 1
            return _DROP
        return {
            key: cleaned
            for key, item in value.items()
            if (cleaned := sanitize(item, stats, host_home)) is not _DROP
        }
    if isinstance(value, list):
        return [
            cleaned for item in value if (cleaned := sanitize(item, stats, host_home)) is not _DROP
        ]
    if isinstance(value, str):
        count = value.count(host_home)
        stats["local_paths"] += count
        redacted_home = str(Path(host_home).parent / "REDACTED")
        return value.replace(host_home, redacted_home)
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--host-home", default=str(Path.home()))
    args = parser.parse_args()

    from inspect_ai.log import EvalLog, read_eval_log, write_eval_log

    source = read_eval_log(args.source)
    stats = {"reasoning_blocks": 0, "local_paths": 0}
    payload = sanitize(source.model_dump(mode="python"), stats, args.host_home)
    public = EvalLog.model_validate(payload)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    write_eval_log(public, args.destination)

    readback = read_eval_log(args.destination)
    assert readback.status == source.status
    assert readback.samples[0].scores == source.samples[0].scores
    print(json.dumps(stats, sort_keys=True))


if __name__ == "__main__":
    main()
