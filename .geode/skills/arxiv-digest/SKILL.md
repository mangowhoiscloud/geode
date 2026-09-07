---
name: arxiv-digest
visibility: public
triggers: paper, 논문, arxiv, research, 연구, 최신 연구, 학회
description: Auto-search and summarize latest AI/agent papers.
tools: general_web_search, web_fetch, memory_save
risk: safe
---

# arXiv Digest

Searches and summarizes the latest papers in AI/ML, agentic systems, and LLM fields.

## Areas of Interest (priority order)

1. **Agentic AI** — autonomous agents, tool use, multi-agent, agent orchestration
2. **LLM Engineering** — prompting, fine-tuning, evaluation, RLHF, MoE
3. **Retrieval & RAG** — retrieval-augmented generation, knowledge grounding
4. **Code Generation** — code agents, program synthesis, SWE-bench
5. **Multimodal** — vision-language, video understanding

## Search Strategy

### Keyword Combinations

- `agentic AI autonomous agent tool use`
- `LLM orchestration multi-agent framework`
- `MCP model context protocol`
- `code generation agent benchmark`

### Sources

- arXiv cs.AI, cs.CL, cs.LG (discovery via `general_web_search`, primary text via `web_fetch`)
- Hugging Face Daily Papers
- Semantic Scholar trending

## Summary Format

```markdown
## arXiv Digest — YYYY-MM-DD

### Top Papers (last 7 days)

#### 1. [Paper Title]
- **Authors**: ...
- **Field**: cs.AI / cs.CL
- **Key Point**: 1-2 sentence summary
- **GEODE Relevance**: Applicable points for agent design
- **Link**: arxiv.org/abs/...

#### 2. ...

### Trending Keywords
- keyword1 (N papers), keyword2 (N papers)
```

## Schedule Integration

Create a recurring digest only when the user asks for scheduling. Example
user request: "Every day at 8:00 in my timezone, summarize recent AI and agent
papers." Resolve the timezone and use the available scheduling interface;
report a created schedule only after its creation is confirmed.

## Guidelines

- Use the user's requested period; default to the last 7 days and state the as-of date
- 1-2 key sentences per paper + 1 sentence on GEODE/agent relevance
- Include up to 10 relevant, verified papers; do not pad a sparse result to reach a minimum
- Use the user's language, keeping original paper titles as-is
- Use only available, permitted tools. If current sources cannot be reached,
  report the limitation rather than presenting remembered papers as a fresh scan
- Save insights via `memory_save` only when the user requests persistence;
  completing a digest does not itself authorize a memory write
