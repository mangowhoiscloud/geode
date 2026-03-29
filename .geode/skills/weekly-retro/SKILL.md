---
name: weekly-retro
description: Weekly retrospective — git log + memory-based work summary + next week planning. Triggers: 'retrospective', '회고', '주간', 'weekly', 'retro', '이번 주'.
tools: run_bash, memory_save
risk: safe
---

# Weekly Retrospective

Automatically summarizes the past week's work and creates a plan for the next week.

## Data Sources

1. **git log** — Commits from the last 7 days (main + develop)
2. **progress.md** — Done items on the kanban board
3. **CHANGELOG.md** — Release records
4. **Project memory** — Insights and decision records

## Retrospective Format

```markdown
## Weekly Retrospective — YYYY-MM-DD ~ YYYY-MM-DD

### Completed Work
| PR | Task | Category |
|----|------|----------|
| #NNN | ... | feat/fix/refactor |

### Metrics
- Commits: N
- PRs merged: N
- Test delta: +N / -N (current XXXX)
- Module count: NNN

### What Went Well
- ...

### What to Improve
- ...

### Next Week Plan
- [ ] Item 1 (priority)
- [ ] Item 2
- [ ] Item 3

### Lessons Learned
- ...
```

## Schedule Integration

```
/schedule create "every friday at 18:00" action="Generate this week's retrospective"
```

## Guidelines

- Based on actual data from `git log --oneline --since="7 days ago"`
- Auto-classify from commit messages: feat/fix/refactor/docs
- Cross-validate with kanban (progress.md) Done section
- "Next Week Plan" recommends items from Backlog based on priority
- After completion, record the retrospective via memory_save
