"""CLI helpers for GEODE benchmark harness setup and preflight."""

from __future__ import annotations

import argparse
from pathlib import Path

from .env import env_status, missing_required
from .manifest import BENCHMARK_HARNESSES, HarnessSpec, get_harness


def setup_commands(
    spec: HarnessSpec, *, include_install: bool, include_healthcheck: bool
) -> list[str]:
    path = spec.checkout_path
    commands = [
        f"mkdir -p {path.parent}",
        f"test -d {path}/.git || git clone {spec.repo} {path}",
        f"git -C {path} fetch origin",
        f"git -C {path} checkout {spec.commit}",
    ]
    if include_install:
        commands.extend(f"cd {path} && {command}" for command in spec.install)
    if include_healthcheck:
        commands.extend(f"cd {path} && {command}" for command in spec.healthcheck)
    return commands


def ensure_checkout(spec: HarnessSpec) -> Path:
    for command in setup_commands(spec, include_install=False, include_healthcheck=False):
        print(command)
    return spec.checkout_path


def install_harness(spec: HarnessSpec) -> None:
    for command in setup_commands(spec, include_install=True, include_healthcheck=False):
        print(command)


def healthcheck_harness(spec: HarnessSpec) -> None:
    for command in setup_commands(spec, include_install=False, include_healthcheck=True):
        print(command)


def print_preflight(spec: HarnessSpec, *, dotenv_path: Path) -> int:
    missing = missing_required(spec.required_env, dotenv_path=dotenv_path)
    combined = spec.required_env + spec.optional_env
    statuses = env_status(combined, dotenv_path=dotenv_path)
    print(f"{spec.name}: {spec.repo}@{spec.commit}")
    print(f"checkout: {spec.checkout_path}")
    print(f"adapter: {spec.public_adapter}")
    for name in combined:
        label = "SET" if statuses.get(name) else "EMPTY"
        print(f"{name}={label}")
    if missing:
        print("missing required: " + ", ".join(missing))
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List known public benchmark harnesses")

    for command in ("ensure", "install", "healthcheck", "preflight"):
        child = subparsers.add_parser(command)
        child.add_argument("harness", choices=sorted(BENCHMARK_HARNESSES))
        child.add_argument("--env-file", type=Path, default=Path(".mcp_env"))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "list":
        for name, spec in sorted(BENCHMARK_HARNESSES.items()):
            print(f"{name}\t{spec.repo}\t{spec.commit}\t{spec.public_adapter}")
        return 0

    spec = get_harness(args.harness)
    if args.command == "ensure":
        print(ensure_checkout(spec))
        return 0
    if args.command == "install":
        install_harness(spec)
        return 0
    if args.command == "healthcheck":
        healthcheck_harness(spec)
        return 0
    if args.command == "preflight":
        return print_preflight(spec, dotenv_path=args.env_file)

    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
