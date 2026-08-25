"""Compatibility entrypoint for the MCPMark paired runner."""

from .mcpmark.pair_runner import PairRunError, main, run_pair

__all__ = ["PairRunError", "main", "run_pair"]

if __name__ == "__main__":
    main()
