---
name: arxiv-digest
visibility: public
description: Auto-search and summarize latest AI/agent papers. Triggers: 'paper', '논문', 'arxiv', 'research', '연구', '최신 연구', '학회'.
tools: web_search, web_fetch, memory_save
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
- `agentic AI autonomous agent tool use 2026`
- `LLM orchestration multi-agent framework`
- `MCP model context protocol`
- `code generation agent benchmark`

### Sources
- arXiv cs.AI, cs.CL, cs.LG (latest via web_search)
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

```
/schedule create "daily at 8:00" action="Generate today's AI/agent paper digest"
```

## Guidelines

- Include only papers published within the last 7 days
- 1-2 key sentences per paper + 1 sentence on GEODE/agent relevance
- Minimum 5, maximum 10 papers
- Summarize in English, keep original titles as-is
- After completion, record insights via memory_save
