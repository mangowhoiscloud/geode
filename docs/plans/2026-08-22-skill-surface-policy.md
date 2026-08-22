# Plan: runtime and cross-host skill surfaces

Date: 2026-08-22
Base: `origin/develop@5ece291ec`
Branch: `codex/skill-mirror-policy-land`

## Objective

Keep `.geode/skills` as GEODE's packaged runtime source of truth while making
`.agents/skills` the shared development scaffold and exposing identical shared
bytes to Claude Code through `.claude/skills` aliases.

## Frontier research summary

| System | Primary contract | Adoption | Rationale |
|---|---|---|---|
| Codex | [Repository skills live in `.agents/skills`; skill-directory symlinks are supported](https://developers.openai.com/codex/skills/#where-codex-loads-local-skills) | Adopt | `.agents` is a real Codex discovery surface, not a GEODE runtime directory. |
| Claude Code | [Project skills live in `.claude/skills`; each skill entry may symlink to another directory](https://code.claude.com/docs/en/slash-commands#where-skills-live) | Adapt | Claude Code does not document `.agents` discovery, so use relative per-skill aliases. |
| Agent Skills | [`SKILL.md` defines the portable package shape](https://agentskills.io/specification) | Adopt | Keep shared metadata portable and isolate host extensions. |
| OpenClaw | Workspace skills override lower tiers | Reference | GEODE already uses later-scope override; no new loader is needed. |
| autoresearch | One mutable source and simplicity selection | Adopt | One owner plus checked aliases is smaller and safer than copied trees. |

## GAP audit

| Surface | Status | GAP | Closure |
|---|---|---|---|
| `.geode/skills` runtime discovery | Existing | Installed smoke checked files, not parsing | Parse packaged `geo` and `grilling` with `SkillLoader`. |
| `.agents/skills` scaffold | Existing | Runtime/meta ownership was prose-only | Require same-name scaffolds to reference the runtime contract. |
| `.claude/skills` bridge | Partial | Two of four shared skills lacked aliases | Add aliases and test every tracked shared skill. |
| Copied cross-host trees | Avoided | Copies can drift | Keep relative per-skill symlinks; leave Claude-only skills local. |

## Design contract

1. Runtime behavior is authored only in `.geode/skills` and shipped as regular
   files in wheel/sdist artifacts.
2. `.agents/skills` contains development procedures. A name collision with a
   runtime skill is allowed only for a thin scaffold that references the
   runtime contract.
3. Every tracked `.agents` skill has a relative `.claude/skills/<name>`
   symlink resolving to the same directory.
4. No loader change, duplicate registry, sync generator, or new dependency is
   introduced.

## Verification

- Targeted surface-policy and SkillLoader tests.
- Fresh wheel/sdist artifact validation and isolated installed-package smoke.
- Ruff, format, mypy for the touched script, repo hygiene, and `git diff --check`.
