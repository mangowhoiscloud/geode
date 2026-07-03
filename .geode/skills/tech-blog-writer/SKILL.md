---
name: tech-blog-writer
visibility: public
triggers: blog, 블로그, 포스팅, 기술 글, tistory, tech blog
description: Write Korean technical blog posts in the operator's Tistory style — formal Korean prose, architecture diagrams, code blocks with design-intent commentary, comparison tables, checklist wrap-up.
---

# Tech Blog Writer (Tistory Style)

Write the post body in Korean; follow these structural rules regardless of
topic. No emoji unless the operator explicitly asks.

## Style rules

| Item | Rule |
|------|------|
| Tone | Formal Korean endings ("합니다", "됩니다", "입니다") |
| Perspective | First person ("이번 글에서는", "이는 설계상의 결정입니다") |
| Code explanation | Design-intent commentary in `>` quote blocks after each code block |
| Emphasis | **Bold**, `inline code`, `>` note blocks |
| Flow | Prose that flows; avoid choppy single-clause sentences |

## Post structure

```
# Title: [Technical concept] — [Subtitle / core value]

> Date: YYYY-MM-DD | Tags: [tag1, tag2]

1. Introduction — problem definition (1 paragraph) + solution strategy (1 paragraph);
   make clear why the reader should keep reading.
2..N. Body — per section: one-line concept summary → architecture diagram
   (Mermaid or ASCII) → core code block (typed Python) → design-intent quote
   block → comparison table (config values, trade-offs).
N+1. Wrap-up — summary table + actionable checklist.
```

## Checklist before delivering

- Every code block has a design-intent commentary block after it.
- At least one diagram and one comparison table in the body.
- Wrap-up contains a summary table and a checklist the reader can apply.
- No emoji, no box-card decoration; dense tables and plain prose only.
