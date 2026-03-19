# Clarification Pipeline

> Status: Implemented | Date: 2026-03-11

## Problem

"Berserk 분석하고 비교하고 리포트 만들어줘" → `compare_ips` with empty `ip_b`
→ handler silently processes empty string → LLM retries → **max_rounds reached**

## Solution: 3-Layer Clarification

### Layer 1: Tool Parameter Validation (Handler-level)

Each handler validates required params before execution.
Returns `clarification_needed: true` with `missing` fields and `hint`.

**Affected handlers:**
- `handle_analyze_ip` — requires `ip_name`
- `handle_compare_ips` — requires both `ip_a` and `ip_b`
- `handle_generate_report` — requires `ip_name`

**Response format:**
```json
{
  "error": "compare_ips requires two IPs to compare",
  "clarification_needed": true,
  "provided": {"ip_a": "Berserk", "ip_b": ""},
  "missing": ["ip_b"],
  "hint": "어떤 IP와 비교할까요?"
}
```

### Layer 2: Prompt-based Guidance (AGENTIC_SUFFIX)

Updated `router.md` AGENTIC_SUFFIX with clarification rules:
- Verify ALL required params before calling a tool
- Never call a tool with empty required values
- Never retry a tool that returned `clarification_needed`
- Ask user a concise question in their language

### Layer 3: Context-aware Flow

The LLM now handles the flow:
```
User: "Berserk 분석하고 비교하고 리포트 만들어줘"
  1. analyze_ip(ip_name="Berserk") → Success ✓
  2. compare_ips(ip_a="Berserk", ip_b="") → clarification_needed
  3. LLM asks: "Berserk와 비교할 IP를 알려주세요."
  → Stops (no max_rounds hit), waits for user response
```

## Changed Files

| File | Change |
|------|--------|
| `core/cli/__init__.py` | Parameter validation in 3 handlers |
| `core/llm/prompts/router.md` | Clarification rules in AGENTIC_SUFFIX |

## Terminology

| Term | Use Case |
|------|----------|
| `clarifying_question` | User-facing: 추가 정보 요청 |
| `clarification_needed` | API response flag |
| `slot_filling` | 필수 파라미터 수집 |
| `disambiguation` | 의미 해석 좁히기 |
