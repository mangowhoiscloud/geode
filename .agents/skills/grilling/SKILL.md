---
name: grilling
description: Design or audit GEODE's dependency-aware grilling flow and slash integration without speculative branch execution or parser-heavy interviews.
---

# GEODE grilling scaffold

1. Read `.geode/skills/grilling/SKILL.md` for the runtime interview contract.
2. Read `docs/plans/2026-08-20-slash-goal-geo.md` for the Tree-of-Thought
   boundary and Codex grounding.
3. Resolve repository facts before asking the user. Ask all independent
   frontier decisions together and defer only dependency-blocked questions.
4. Use internal candidate tree comparison only before side effects. Do not
   describe shared-state execution as MCTS, LATS, or branch rollback.
5. Verify slash input routes through `SkillRegistry → AgenticLoop` and that the
   command does not gain execution authority beyond an ordinary prompt.
