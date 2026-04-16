# Contributing to GEODE

Thank you for your interest in contributing to GEODE! This document provides
guidelines and information for contributors.

## Getting Started

```bash
# Clone and install
git clone https://github.com/mangowhoiscloud/geode.git
cd geode
uv sync

# Run tests
uv run python -m pytest tests/ -m "not live" -q

# Lint and type check
uv run ruff check core/ tests/
uv run mypy core/
```

## Development Workflow

We use GitFlow branching:

```
feature/<name> → develop → main
```

1. Create a feature branch from `develop`
2. Make your changes
3. Ensure all quality gates pass (see below)
4. Submit a PR to `develop`

## Quality Gates

All PRs must pass these checks:

| Gate | Command | Criteria |
|------|---------|----------|
| Lint | `uv run ruff check core/ tests/` | 0 errors |
| Format | `uv run ruff format --check core/ tests/` | 0 diffs |
| Type | `uv run mypy core/` | 0 errors |
| Test | `uv run python -m pytest tests/ -m "not live"` | All pass |

## Pull Request Guidelines

- Keep PRs focused — one feature or fix per PR
- Write clear commit messages (conventional commits preferred)
- Include tests for new functionality
- Update documentation if behavior changes
- PR body must include: **Summary**, **Why**, **Changes**, **Verification**

## Code Style

- Python 3.12+
- Ruff for linting and formatting (line-length=100)
- Type annotations required for public APIs
- No emojis in code or prompts (allowed in reports only)

## Developer Certificate of Origin (DCO)

By contributing to this project, you certify that:

1. The contribution was created in whole or in part by you and you have the
   right to submit it under the Apache 2.0 license; or
2. The contribution is based upon previous work that, to the best of your
   knowledge, is covered under an appropriate open source license and you
   have the right to submit that work with modifications under the
   Apache 2.0 license; or
3. The contribution was provided directly to you by some other person who
   certified (1) or (2) and you have not modified it.

You indicate your acceptance of the DCO by adding a `Signed-off-by` line
to your commit messages:

```
Signed-off-by: Your Name <your.email@example.com>
```

Use `git commit -s` to add this automatically.

## Reporting Issues

- **Bugs**: Use the [Bug Report](https://github.com/mangowhoiscloud/geode/issues/new?template=bug_report.md) template
- **Features**: Use the [Feature Request](https://github.com/mangowhoiscloud/geode/issues/new?template=feature_request.md) template
- **Security**: See [SECURITY.md](SECURITY.md) — do NOT open public issues

## License

By contributing, you agree that your contributions will be licensed under the
Apache License 2.0. See [LICENSE](LICENSE) for details.
