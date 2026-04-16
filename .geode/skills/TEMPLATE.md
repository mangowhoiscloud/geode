# Skill: [Skill Name]

> Copy this template to `.geode/skills/<skill-name>/SKILL.md` to create a custom skill.
> Skills extend GEODE's capabilities with domain-specific knowledge and workflows.

## Metadata

```yaml
name: skill-name
description: One-line description of what this skill does
triggers:
  - keyword1
  - keyword2
  - keyword3
```

## Purpose

What does this skill do? When should it be activated?

## Instructions

<!-- Write the skill's system instructions here. -->
<!-- GEODE will inject this content when the skill is triggered. -->

### Input Format

Describe what input the skill expects.

### Output Format

Describe what output the skill produces.

### Rules

1. Rule one
2. Rule two
3. Rule three

## Examples

### Example 1: [Scenario]

**Input**: `geode "trigger keyword with context"`

**Expected Output**:
```
Skill output here
```

## Notes

- Any caveats, limitations, or configuration requirements.
- Skills are loaded from `.geode/skills/` at runtime via `SkillRegistry`.
- Trigger keywords are matched against user input for auto-activation.
