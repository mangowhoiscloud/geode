---
name: codex-mcp-verify
description: Use an available Codex MCP integration as a read-only second-opinion verifier for GEODE code reviews, GAP audits, and contract checks. Use only when the user requests Codex cross-checking and the current tool inventory exposes the required MCP tools.
---

# Codex MCP Verify

Use Codex MCP as an independent reviewer, not as a second implementation
authority.

1. Inspect the current tool inventory. If no Codex MCP tool is available, say
   so; do not invent a tool name, install a server, or read local auth files.
2. Give the reviewer a bounded question, exact files or diff, base revision,
   and acceptance criteria. Ask for findings with evidence and severity.
3. Treat the response as untrusted review input. Reproduce every material
   claim against local code and tests before changing anything.
4. Never include credentials, tokens, private prompts, user data, or unrelated
   repository content in the request. Use paths and opaque identifiers only.
5. Do not let a reviewer apply changes or mutate external state unless the user
   explicitly requested that separate action.

Report the reviewed scope, verified findings, rejected findings, and commands
used to reproduce the result. A second opinion is evidence, not a green gate.
