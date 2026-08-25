"""Compatibility facade for the tau2 public adapter."""

from .assays.tau2_geode_agent import main, parse_args, register_geode_tau2_participants

__all__ = ["main", "parse_args", "register_geode_tau2_participants"]

if __name__ == "__main__":
    raise SystemExit(main())
