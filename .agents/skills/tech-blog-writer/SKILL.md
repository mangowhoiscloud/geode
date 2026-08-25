---
name: tech-blog-writer
description: Technical blog post writing guide. rooftopsnow.tistory.com style — Korean formal technical prose, architecture diagrams, code blocks + design intent commentary, table comparisons, checklist wrap-up. Triggers on "blog", "포스팅", "블로그", "기술 글", "tech blog".
---

# Tech Blog Writer (Tistory Style)

## Writing Style Rules

| Item | Rule |
|---|---|
| Tone | Formal Korean ("합니다", "됩니다", "입니다") |
| Perspective | First person ("In this post", "This is a design decision") |
| Code explanation | Design intent commentary in `>` quote blocks |
| Emphasis | **Bold**, `inline code`, > Note boxes |
| Emoji | Do not use (only when explicitly requested by user) |

## Post Structure

```
# Title: [Technical Concept] — [Subtitle/Core Value]

> Date: YYYY-MM-DD | Author: geode-team | Tags: [tag1, tag2]

## Table of Contents
1. Introduction (Problem definition)
2~N. Body sections (Architecture → Implementation → Verification)
N+1. Wrap-up (Summary table + Checklist)

---

## 1. Introduction

Problem definition in 1 paragraph → Solution strategy in 1 paragraph.
Make clear "why the reader should read this."

## 2~N. Body

### Section title: "N. Concept Name + Detailed Description"

Each section pattern:
1. One-line concept summary
2. Architecture diagram (Mermaid or ASCII)
3. Core code block (Python, with type hints)
4. > Design intent commentary block
5. Comparison table (config values, trade-offs, etc.)

## N+1. Wrap-up

### Summary

| Item | Value/Description |
|---|---|
| ... | ... |

### Checklist

- [ ] Item 1
- [ ] Item 2
```

## Code Block Rules

1. **Interface/Protocol first** → Implementation later
2. Type hints must be included
3. `>` quote block immediately after code block explaining "why this design"
4. File path as comment above code block: `# geode/infrastructure/ports/llm_port.py`

```python
# geode/infrastructure/ports/llm_port.py
class LLMClientPort(Protocol):
    def generate(self, system: str, user: str, **kwargs) -> str: ...
    def generate_json(self, system: str, user: str, **kwargs) -> dict: ...
```

> By abstracting the concrete LLM call implementation (Claude, GPT), models can be swapped by simply replacing the adapter.
> This is a design decision following the Hexagonal Architecture Port/Adapter pattern.

## Diagram Rules

- Prefer Mermaid (GitHub rendering compatible)
- Use ASCII diagrams alongside for complex flows
- 1-2 sentence explanation of core flow immediately after diagram
- Colors: Tailwind CSS based (`fill:#3B82F6`, `fill:#10B981`, etc.)

## Length Guide

| Type | Length | Code:Explanation ratio |
|---|---|---|
| Concept introduction | 3000-5000 chars | 3:7 |
| Architecture deep-dive | 6000-10000 chars | 4:6 |
| Implementation tutorial | 8000-12000 chars | 6:4 |

## Korean Technical Terminology Rules

- English technical terms: Korean annotation on first appearance: "Port(포트)"
- Thereafter use English original: "Port"
- Proper nouns (LangGraph, Anthropic, FastMCP) always in English
- Abbreviations: spell out on first appearance: "PSI(Population Stability Index)"
