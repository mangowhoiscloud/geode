---
name: skill-name
description: One-line description of what this skill does
visibility: public
triggers: [keyword1, keyword2, keyword3]
---

# Skill Name

> Copy to `.geode/skills/<skill-name>/SKILL.md` and replace the authoring guidance
> below, or start with `geode skill create <skill-name> --desc "Description"`.
> Keep metadata between the opening `---` lines. Trigger lists must use an
> inline list or comma-separated string, not multi-line YAML lists.

## Purpose and scope

Name the task, useful result, activation conditions, and explicit non-goals.
Apply the workflow only within the user's authorized task and available tools.

## Inputs and ownership

Identify required inputs and the existing file, service, or state owner to
inspect or change. State what missing input would block the task.

## Procedure

Describe only necessary steps and branches. Refer to existing instructions
instead of copying them; do not turn reference sections into mandatory steps.

## Output and verification

Name the result and its consumer. Give the smallest check that demonstrates
the requested outcome, including where to run it and what passing means.

## Failure and recovery

Identify likely failures, where evidence remains, and the next permitted
action. Preserve failed results separately from reruns; do not weaken checks.

## Invocation

The runtime advertises metadata, including triggers, in `<available_skills>`;
trigger text does not automatically inject the body. The model loads it with
`use_skill(name="skill-name")`, or the user invokes `/skill skill-name [args]`.
`$ARGUMENTS` in the body receives the supplied argument string.

Project skills live in `.geode/skills/`; personal skills belong in
`~/.geode/skills/` (`geode skill create <skill-name> --private`). `visibility: unlisted`
hides a skill from `geode skill list` unless `--all` is used; it is not an
access-control boundary. `user-invocable: false` hides it from `/skills`.
