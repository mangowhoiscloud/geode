# GEODE NL Routing Demo Scenario

> Recording script for demonstrating GEODE's Natural Language Routing system.
> Total runtime: ~8-10 minutes | 7 scenes

---

## Pre-recording Checklist

```bash
# 1. Verify API key is configured
uv run python -c "from core.config import settings; print('API key:', bool(settings.anthropic_api_key))"
# Expected: API key: True

# 2. Verify readiness (force_dry_run should be False)
uv run python -c "from core.cli.startup import check_readiness; r = check_readiness(); print(f'dry_run={r.force_dry_run}')"
# Expected: dry_run=False

# 3. Verify NL Router is functional (LLM call)
uv run python -c "from core.cli.nl_router import NLRouter; r = NLRouter(); i = r.classify('test'); print(i.action)"
# Expected: chat or help (should NOT error)

# 4. Clear terminal
clear
```

---

## Scene 1: Startup & Readiness Check (1 min)

**Goal:** Show GEODE boots up, detects API key, enables live LLM mode.

```
$ uv run geode
```

**Expected output:**
```
╭─── GEODE v0.6.0 — Undervalued IP Discovery Agent ───╮
│                                                       │
╰───────────────────────────────────────────────────────╯

  ✓ LLM Analysis          claude-opus-4-6
  ✓ Environment            .env loaded
  ✓ Project Memory         .claude/MEMORY.md
  ✓ Dry-Run Analysis
  ✓ IP Search              203 IPs indexed

  Ready — LLM analysis enabled
```

**Narration point:** "API key is configured, so `force_dry_run` is False. All natural
language inputs will route through the full LLM pipeline — not dry-run."

---

## Scene 2: NL Intent — Single IP Analysis (2 min)

**Goal:** Demonstrate Korean NL input triggers full LLM pipeline (not dry-run).

```
> Berserk 분석해줘
```

**What happens under the hood (explain with overlay/diagram):**
1. NL Router receives "Berserk 분석해줘"
2. Claude Opus 4.6 Tool Use API classifies → `analyze_ip(ip_name="Berserk")`
3. `_handle_natural_language()` maps action="analyze"
4. `readiness.force_dry_run` = False → full pipeline executes
5. Pipeline: Router → Signals → Analyst ×4 → Evaluator ×3 → Scoring → Verification → Synthesizer
6. Post-analysis: LLM Commentary generates natural language summary

**Expected output (abbreviated):**
```
▸ [GATHER] Loading IP data from MonoLake...
├── IP: Berserk (manga, 1989, Hakusensha)
├── MonoLake: DAU=0, Revenue=$0 (no active game)
└── Signals: YouTube 25M | Reddit 520K | FanArt +65% YoY

▸ [ANALYZE] Running 4 Analysts (Clean Context)...
┏━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Analyst        ┃ Score ┃ Key Finding                               ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Discovery      │  4.5  │ Massively underexploited dark fantasy IP   │
│ Game_mechanics │  4.5  │ Elite-tier action combat system potential  │
│ Growth_potent… │  4.5  │ Exceptional organic fandom growth          │
│ Player_experi… │  4.6  │ One of the most emotionally intense ...    │
└────────────────┴───────┴───────────────────────────────────────────────┘

▸ [EVALUATE] 14-Axis Rubric Scoring...
  Quality    █████████████████████░░░ 88/100

▸ [SCORE] PSM + Final Calculation
  Final Score: 80.0/100  |  Tier: S
```

**Narration point:** "Notice — 4 independent LLM calls for analysts, 3 for evaluators,
plus scoring and verification. This is NOT dry-run. Every score is generated live by the LLM."

---

## Scene 3: NL Intent — IP Search (1 min)

**Goal:** Show search intent classification (no LLM pipeline, but NL routing uses LLM).

```
> 소울라이크 게임 찾아줘
```

**Under the hood:**
1. NL Router: Claude Tool Use → `search_ips(query="soulslike")`
2. Search engine runs (synonym expansion, TF-IDF scoring)
3. LLM Commentary summarizes results

**Expected output:**
```
🔍 Search Results for "soulslike"

┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ IP                  ┃  Score  ┃ Genre               ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ Nine Sols            │  0.85  │ Action Metroidvania  │
│ Dead Cells           │  0.72  │ Roguelike Action     │
│ Hollow Knight        │  0.68  │ Metroidvania         │
│ ...                  │  ...   │ ...                  │
└──────────────────────┴────────┴─────────────────────┘
```

**Narration point:** "The NL Router itself makes an LLM call to classify intent.
The search execution is local (no LLM), but the commentary afterwards is another LLM call."

---

## Scene 4: NL Intent — Compare Two IPs (2 min)

**Goal:** Show comparison triggers two full pipeline executions + comparative commentary.

```
> Berserk vs Cowboy Bebop 비교해줘
```

**Under the hood:**
1. NL Router: `compare_ips(ip_a="Berserk", ip_b="Cowboy Bebop")`
2. Runs `_run_analysis("Berserk")` → full pipeline (or cache hit)
3. Runs `_run_analysis("Cowboy Bebop")` → full pipeline
4. Side-by-side result rendering
5. LLM Commentary with comparative analysis

**Expected output (abbreviated):**
```
╭─── Comparison: Berserk vs Cowboy Bebop ───╮

  Berserk          80.0  ████████████████████  S
  Cowboy Bebop     69.4  ████████████████      A

  Winner: Berserk (+10.6)
╰───────────────────────────────────────────╯

💬 Berserk가 Cowboy Bebop보다 10.6점 높은 S 등급입니다.
   게임 메카닉스와 커뮤니티 성장성 모두에서 우위를 보이며...
```

**Narration point:** "Two separate full pipelines run — that's 8 analyst calls + 6 evaluator
calls. The comparison commentary synthesizes both results into a single narrative."

---

## Scene 5: NL Intent — Batch Analysis (1.5 min)

**Goal:** Show batch intent triggers multiple concurrent pipeline executions.

```
> 상위 3개 IP 배치 분석해줘
```

**Under the hood:**
1. NL Router: `batch_analyze(top=3)`
2. ThreadPoolExecutor runs 3 parallel pipeline executions
3. Rich table renders all results

**Expected output:**
```
▸ Batch Analysis (top 3)

┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━┓
┃ #  ┃ IP                    ┃ Score  ┃ Tier ┃ Status     ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━┩
│ 1  │ Berserk               │  80.0  │  S   │ ✓ Complete │
│ 2  │ Cowboy Bebop           │  69.4  │  A   │ ✓ Complete │
│ 3  │ Ghost in the Shell     │  54.0  │  B   │ ✓ Complete │
└────┴───────────────────────┴────────┴──────┴────────────┘
```

---

## Scene 6: NL Intent — System Operations (1 min)

**Goal:** Show non-analysis intents that still use LLM routing.

### 6a. System Status
```
> 시스템 상태 확인해줘
```

**Expected:**
```
╭─── GEODE System Status ───╮
│ Model:    claude-opus-4-6  │
│ API Key:  ✓ configured     │
│ Mode:     live (LLM)       │
│ IPs:     203 indexed       │
│ Memory:  .claude/MEMORY.md │
╰────────────────────────────╯
```

### 6b. Memory Search
```
> Berserk 관련 이전 분석 기억나?
```

**Expected:**
```
🧠 Memory Search: "Berserk"
  Found 2 insights:
  - [2026-03-10] Berserk scored S-tier (80.0/100)
  - [2026-03-10] Dark fantasy + no active game = high discovery signal
```

---

## Scene 7: NL Dry-run Request (1 min)

**Goal:** Show users can request dry-run in natural language.

```
> Berserk dry-run으로 분석해줘
```

**Under the hood:**
1. NL Router: `analyze_ip(ip_name="Berserk")` (LLM may or may not set `dry_run=true`)
2. Hybrid detection: `_text_requests_dry_run()` pattern matches "dry-run" keyword
3. Handler overrides `force_dry = True` regardless of API key status
4. Fixture data used, no LLM pipeline calls

**Supported dry-run trigger phrases (Korean + English):**
```
dry-run, 드라이런, LLM 없이, LLM 호출 없이,
fixture로만, without LLM, no-LLM, 간단히
```

**Works across all commands:**
```
> Berserk dry-run으로 분석해줘          → analyze (dry-run)
> 상위 3개 dry-run 배치 분석            → batch (dry-run)
> Berserk vs Cowboy Bebop dry-run 비교  → compare (dry-run)
> Berserk 리포트 LLM 없이 만들어       → report (dry-run)
> /analyze Berserk --dry-run            → slash command (dry-run)
> /compare Berserk Cowboy_Bebop --dry-run → slash command (dry-run)
> /batch --top 3 --dry-run              → slash command (dry-run)
```

**Narration point:** "Dry-run detection uses a hybrid approach — the NL Router's LLM
tool definition supports `dry_run=true`, and a regex pattern scanner catches keywords
the LLM might miss. This ensures reliable dry-run routing regardless of LLM behavior."

---

## Scene 8: Graceful Degradation — Explicit CLI Dry-run (1 min)

**Goal:** Show `--dry-run` flag forces fixture-only mode even with API key.

```
> /quit
$ uv run geode analyze "Berserk" --dry-run
```

**Expected output:**
```
╭─── GEODE v0.6.0 — Undervalued IP Discovery Agent ───╮
│   Analyzing: berserk                                  │
│   Pipeline: full_pipeline | Model: dry-run (no LLM)   │  ← No LLM calls
╰───────────────────────────────────────────────────────╯

▸ [GATHER] Loading IP data from MonoLake...
▸ [ANALYZE] Running 4 Analysts (Clean Context)...    ← fixture data
▸ [EVALUATE] 14-Axis Rubric Scoring...               ← fixture data
▸ [SCORE] PSM + Final Calculation
  Final Score: 82.2/100  |  Tier: S
```

**Narration point:** "Even though the API key is set, `--dry-run` explicitly
bypasses LLM calls. This is now opt-in only — the default is live analysis."

---

## Scene Summary — LLM Call Breakdown

| Scene | User Input | NL Router LLM | Pipeline LLM | Commentary LLM | Total Calls |
|-------|-----------|---------------|--------------|----------------|-------------|
| 2 | "Berserk 분석해줘" | 1 (classify) | ~8 (4 analyst + 3 eval + 1 synth) | 1 | ~10 |
| 3 | "소울라이크 찾아줘" | 1 (classify) | 0 (search is local) | 1 | 2 |
| 4 | "Berserk vs Cowboy Bebop" | 1 (classify) | ~16 (2 × pipeline) | 1 | ~18 |
| 5 | "상위 3개 배치" | 1 (classify) | ~24 (3 × pipeline) | 0 | ~25 |
| 6a | "시스템 상태" | 1 (classify) | 0 | 0 | 1 |
| 6b | "이전 분석 기억나?" | 1 (classify) | 0 | 1 | 2 |
| 7 | "dry-run으로 분석해" | 1 (classify) | 0 (forced dry-run) | 0 | 1 |
| 8 | `--dry-run` CLI flag | 0 (CLI flag) | 0 | 0 | 0 |

**Total LLM calls across demo: ~60**

---

## Architecture Overlay Diagram (for video)

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INPUT (Korean/English)               │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │   NL Router (LLM Call)  │
              │   Claude Opus 4.6       │
              │   Tool Use API          │
              │   17 tool definitions   │
              └────────────┬────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │ analyze  │    │  search  │    │ compare  │  ... (17 intents)
    └────┬─────┘    └────┬─────┘    └────┬─────┘
         │               │               │
         ▼               ▼               ▼
  ┌─────────────┐  ┌──────────┐  ┌─────────────────┐
  │ Full        │  │ Local    │  │ 2× Full         │
  │ Pipeline    │  │ Search   │  │ Pipeline        │
  │ (8+ LLM)   │  │ Engine   │  │ (16+ LLM)       │
  └──────┬──────┘  └────┬─────┘  └───────┬─────────┘
         │               │               │
         └───────────────┼───────────────┘
                         ▼
              ┌──────────────────────┐
              │  LLM Commentary      │
              │  (contextual summary)│
              └──────────────────────┘
```

---

## Key Messages for Video

1. **NL routing is LLM-native** — Claude Opus 4.6 Tool Use API, not regex patterns
2. **Default is live analysis** — dry-run only when explicitly requested or no API key
3. **NL dry-run is reliable** — hybrid detection (LLM tool arg + regex pattern scanner)
4. **Every intent triggers at least 1 LLM call** (the router itself)
5. **Analysis intents trigger 8+ additional LLM calls** (4 analysts + 3 evaluators + synthesizer)
6. **Graceful degradation** — if LLM unavailable, falls back to offline patterns (no crash)
7. **Bilingual** — Korean and English inputs both work seamlessly
8. **Commentary** — post-action LLM generates contextual natural language response
9. **Consistent dry-run across all paths** — NL, slash commands, and CLI all support `--dry-run`
