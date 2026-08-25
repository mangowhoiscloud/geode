"""Compatibility entrypoint for the MCPMark runner."""

from .mcpmark.runner import main

__all__ = ["main"]

if __name__ == "__main__":
    main()
