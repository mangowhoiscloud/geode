## Summary
<!-- 1-3 bullet points: what changed and why -->

## Why
<!-- Problem statement: what broke, what was missing, what user reported -->

## Changes
| File | Change |
|------|--------|
| `path/to/file.py` | description |

## Verification
- [ ] `uv run ruff check core/ tests/` — clean
- [ ] `uv run ruff format --check core/ tests/` — clean
- [ ] `uv run mypy core/` — clean
- [ ] `uv run pytest tests/ -m "not live"` — pass
