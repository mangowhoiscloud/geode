---
name: geode-frontend
visibility: unlisted
description: GEODE 포트폴리오 프론트엔드 개발 플러그인. 페이지 흐름, 디자인 시스템, 컴포넌트 인벤토리, GAP 분석 가이드. "geode", "frontend", "리뉴얼", "디자인", "페이지", "flow", "component" 키워드로 트리거.
---

# GEODE Frontend Development Plugin

> Target: `public/geode.html` (single-file portfolio, ~9400 lines)
> Theme: Deep Sea Discovery — Ocean Gem Palette
> Mascot: Geodi (Pink Axolotl Explorer)
> Design DNA: `plans/geode-design-dna.md`, `plans/geode-design-concept-v2.md`

---

## 1. Page Architecture

### Section Flow (Current)
```
Hero (#overview)
  └─ Geodi hero illustration + badge + GEODE v0.8.0 + 4 stats

Agentic Engineering (#agentic) — 6 pillar cards (3×2)
  └─ Autonomous Reasoning, Goal-Driven Planning, Self-Correction,
     Multi-Agent Coordination, Dynamic Tool Selection, Confidence-Gated Learning

[Mascot Divider: idle — "심해로 안내합니다"]

Section 00: Agent Reasoning Flow (#pipeline)
  └─ 8-node pipeline flow + 4-analyst fan-out + agent loop SVG

Section 01: Agent Architecture (#architecture)
  └─ 6-layer cards (L1-L6) + Expert Panel (4 cards) + C2-C5 Flexibility grid

[Mascot Divider: focus — "IP 데이터 분석 중"]

Section 02: Causal Scoring & Diagnosis (#scoring)
  └─ PSM radar chart SVG + 6-cause decision tree + fixture results

Section 03: Self-Correction & Guardrails (#verification)
  └─ G1-G4 cards + BiasBuster + Cross-LLM + Rights Risk

[Mascot Divider: discover — "보석 발견!"]

Section 04: Multi-Agent Coordination (#orchestration)
  └─ 3-tier memory + Plan Mode FSM SVG + SubAgent DAG + HITL Safety

Section 05: Self-Improvement & Runtime (#automation)
  └─ CUSUM drift + Feedback 5-phase + Graceful Degradation
  └─ G2: LangSmith Observability + G3: Auto-Learning Loop

Section 06: Multi-LLM Ensemble (#tech)
  └─ Claude Client + Multi-LLM + Tool Registry + Prompts + CLI + Rich Display
  └─ G1: Claude Code-style UI + G5: Report Generation

[Mascot Divider: idle — "지금까지의 여정"]

Section 07: Timeline (#timeline)
  └─ v0.6.0 → v0.6.1 → v0.7.0 → v0.8.0 (current) → v0.9.0 (next)

Footer
  └─ GitHub link + "Discovered by Geodi" + copyright
```

### Nav Links
Overview, Agentic, Reasoning, Architecture, Scoring, Guardrails, Coordination, Self-Improve, LLM Ensemble, Timeline

---

## 2. Design System — Deep Sea Discovery

### Color Tokens
```css
/* Ocean Backgrounds */
--bg-deep: #0B1628        /* abyss */
--bg-primary: #0F1F3A     /* deep sea */
--bg-secondary: #162D50   /* mid ocean */
--bg-card: rgba(26,61,110,0.4)      /* glass card */
--bg-card-hover: rgba(31,61,94,0.6) /* glass hover */

/* Accent System */
--accent-primary: #818CF8   /* indigo — primary UI */
--accent-secondary: #C084FC /* purple — secondary */
--bubble-teal: #4ECDC4      /* teal — interaction, router, CLI */
--mascot-pink: #F4B8C8      /* soft pink — agent, L3 */
--gem-gold: #F5C542         /* warm gold — discovery, L5 */
--sand-warm: #D4A574        /* warm tan — tool belt, labels */
--coral-pink: #E87080       /* coral — error, critical */
--kelp-green: #34D399       /* emerald — success, L1 */

/* 6-Layer Colors */
L1 Foundation:   #34D399 (emerald/kelp)
L2 Memory:       #60A5FA (blue/ocean)
L3 Agentic Core: #F4B8C8 (mascot pink)
L4 Orchestration: #818CF8 (indigo/deep)
L5 Automation:   #F5C542 (gem gold)
L6 Extensibility: #C084FC (purple/bubble)

/* Borders */
--border-subtle: rgba(78,205,196,0.08)   /* teal hint */
--border-glow: rgba(78,205,196,0.2)      /* teal glow */
Card hover border: rgba(244,184,200,0.25) /* pink on hover */
Card hover shadow: rgba(245,197,66,0.06)  /* gold glow */
```

### Typography
```
Hero Title:  Inter 800, clamp(3rem,8vw,6rem), -0.03em, text-shadow pink glow
Stat Value:  Inter 800, 2.5rem, gem-gold color
Section:     Inter 700, 2.5rem, -0.02em
Category:    Inter 700, 1.5rem, -0.01em, category-color
Body:        Inter/NotoSansKR 400-500, 0.85-0.9rem, line-height 1.7
Code Badge:  Fira Code 400, 0.65-0.75rem
Micro Label: Fira Code 400, 0.65rem, uppercase, 0.1em tracking
```

### Component Patterns
```css
/* Glass Card */
background: var(--bg-card);
border: 1px solid var(--border-subtle);
border-radius: 20px;
backdrop-filter: blur(8px);
/* hover: */
border-color: rgba(244,184,200,0.25);
box-shadow: 0 20px 60px var(--glow), 0 8px 32px rgba(245,197,66,0.06);
transform: translateY(-5px);

/* Modal */
background: rgba(15,31,58,0.95);
border: 1px solid rgba(78,205,196,0.15);
backdrop-filter: blur(20px);
box-shadow: 0 25px 80px rgba(0,0,0,0.5), 0 0 60px rgba(244,184,200,0.04);

/* Table Header */
color: var(--bubble-teal);
background: rgba(78,205,196,0.06);

/* Explanation Block */
background: rgba(78,205,196,0.04);
border-left: 3px solid var(--bubble-teal);

/* Code Block */
background: rgba(11,22,40,0.5);
```

### Animations
```css
@keyframes mascot-float   { 0%,100% { translateY(0) } 50% { translateY(-10px) } }  /* 6s */
@keyframes float-gem       { 0%,100% { translateY(0) rotate(0) opacity:0.25 } 50% { translateY(-20px) rotate(12deg) opacity:0.5 } }  /* 8s */
@keyframes fadeInUp        { from { opacity:0; translateY(30px) } to { opacity:1; translateY(0) } }
@keyframes pulse           { 0%,100% { opacity:1; scale(1) } 50% { opacity:0.5; scale(1.2) } }
```

---

## 3. Mascot Integration Points

| Location | Image | Size | Purpose |
|----------|-------|------|---------|
| Hero | `geode-hero.png` (800×533, 738KB) | max-width 480px | 풀 일러스트, float animation + glow |
| Section divider ×4 | `geode-idle/focus/discover.png` (~128px) | 64px display | 포즈별 가이드 캐릭터 |
| Footer | `geode-idle.png` | 48px | "Discovered by Geodi" 크레딧 |
| (Reserved) Empty state | `geode-focus.png` | 80px | 로딩/검색 중 상태 |
| (Reserved) Error | `geode-discover.png` | 80px | 404/에러 페이지 |

---

## 4. Modal Architecture (47 total)

### Structure Template (모든 모달 통일)
```html
<div class="modal-overlay" id="modal-geode-{name}">
  <div class="modal-content" style="max-width: {800-900}px;">
    <button class="modal-close" onclick="closeModal('modal-geode-{name}')">×</button>
    <h2 class="modal-title">{emoji} {Title KO/EN}</h2>
    <div class="modal-explanation">{2-3줄 에이전트 관점 설명}</div>
    <div class="modal-metrics">{3 metric cards}</div>
    <div class="modal-code"><pre><code>{실제 코드 기반}</code></pre></div>
    <div class="modal-section">{Details Table (optional)}</div>
  </div>
</div>
```

### Modal Quality Tiers (Completed)
- **P0 (8)**: router, scoring, guardrails, biasbuster, planner, task-system, hooks, adaptive-loop
- **P1 (8)**: cortex, signals, analyst-detail, evaluator-detail, scoring-overview, synthesizer, cross-llm, clean-context, decision-tree, confidence-calc
- **P2 (12)**: stategraph, send-api, reducer, node-contract, expert-panel, feedback, org/project/session-context, settings, bootstrap, factory
- **P3 (13)**: claude-client, structured-output, prompts, cli, rich-display, nl-router, di, cusum, drift-monitor, model-registry, triggers, verification-flow, rights-risk

---

## 5. JavaScript API

```javascript
setLang(lang)              // 'ko' | 'en' — body.classList.toggle('en')
switchTab(btn, tabId)      // Modal tab switching
openModal(modalId)         // Display modal overlay
closeModal(modalId)        // Hide modal overlay

// Observers
IntersectionObserver       // Scroll-triggered fade-in animations
timelineObserver           // Timeline item state: viewed → current → next
scrollObserver             // Nav active state tracking
```

### Bilingual System
```html
<span class="lang-ko">한국어 텍스트</span>
<span class="lang-en">English text</span>
<!-- body.en → .lang-ko { display: none } .lang-en { display: inline } -->
```

---

## 6. GAP Analysis — 리뉴얼 체크리스트

### Flow & Structure Gaps
- [ ] Section 00 (Agent Reasoning Flow) 이 너무 밀도 높음 — pipeline + agent loop + summary stats 분리 고려
- [ ] Agentic Engineering 섹션이 Hero 바로 아래인데 Section 00과 역할 중복
- [ ] Section 05-06의 G1-G3, G4-G5 카드들이 기존 섹션에 append 형태 — 네이티브 통합 필요
- [ ] 47 모달 중 P2/P3 (25개)는 아직 에이전트 프레이밍 미적용

### Visual Gaps
- [ ] SVG 다이어그램 6개의 스타일이 통일되지 않음 (일부 old void-black 색감 잔존)
- [ ] 일부 인라인 카드 그리드가 CSS 클래스 대신 style="" 사용 — 유지보수 어려움
- [ ] 반응형(모바일) 미최적화 — 768px 이하에서 pipeline flow 깨짐 가능
- [ ] LangSmith/Auto-Learning/Report Generation 카드가 기존 섹션 하단에 부록 느낌

### Content Gaps
- [ ] Section 07 Timeline에 v0.9.0+ 로드맵 미표시
- [ ] Hero 4개 stats 외에 "Key Achievement" 하이라이트 부재
- [ ] Cross-reference: 모달 간 관련 링크 시스템 미구현
- [ ] 코드 예시의 syntax highlighting이 일부 모달에서 불완전

### Technical Debt
- [ ] CSS 커스텀 프로퍼티 사용률 낮음 — 인라인 rgba() 직접 사용 다수
- [ ] onmouseover/onmouseout 인라인 핸들러 → CSS :hover 또는 JS delegation 으로 전환 필요
- [ ] 9400줄 단일 HTML → CSS/JS 분리 또는 빌드 시스템 도입 고려
- [ ] 이미지 lazy loading 미적용 (hero 제외)

---

## 7. Renewal Implementation Guide

### Phase 0: Audit & Plan
1. Read `plans/geode-design-concept-v2.md` for design direction
2. Read `.claude/skills/geode-portfolio/SKILL.md` for SOT numbers
3. Verify current page against SOT (run verification checklist)

### Phase 1: Page Flow Restructure
1. 섹션 순서/그루핑 재설계 — narrative flow 기준
2. Agentic Engineering + Section 00 통합/분리 결정
3. G1-G5 갭 카드들을 네이티브 섹션 내 위치로 이동
4. 네비게이션 구조 업데이트

### Phase 2: Component Standardization
1. 인라인 style → CSS 클래스 전환 (특히 카드 그리드, 호버 효과)
2. 모달 P2/P3 에이전트 프레이밍 적용
3. SVG 다이어그램 스타일 통일 (ocean theme)
4. 반응형 breakpoint 최적화

### Phase 3: Visual Polish
1. 섹션 간 depth zone 배경색 변화 (수심 증가 효과)
2. 마스코트 인터랙션 강화 (스크롤 반응, 상태 변화)
3. 코드 블록 syntax highlighting 통일
4. 모달 간 관련 링크 네트워크

### Phase 4: Performance & DX
1. CSS/JS 외부 파일 분리 (optional)
2. 이미지 lazy loading + WebP 전환
3. Critical CSS 인라인 + defer non-critical
4. Lighthouse audit → Core Web Vitals 최적화

---

## 8. File References

| File | Purpose |
|------|---------|
| `public/geode.html` | 메인 포트폴리오 페이지 (~9400 lines) |
| `public/images/geode-hero.png` | 히어로 풀 일러스트 (800×533) |
| `public/images/geode-idle.png` | 픽셀아트 기본 포즈 (149×128) |
| `public/images/geode-focus.png` | 픽셀아트 분석 포즈 (158×128) |
| `public/images/geode-discover.png` | 픽셀아트 발견 포즈 (145×128) |
| `plans/geode-design-dna.md` | v1 디자인 DNA (Crystal from Chaos) |
| `plans/geode-design-concept-v2.md` | v2 디자인 컨셉 (Deep Sea Discovery) |
| `plans/geode-modal-overhaul.md` | 모달 오버홀 계획 + 실행 현황 |
| `plans/geode-agent-rebrand.md` | 에이전트 리브랜딩 기록 |
| `plans/geode-portfolio-sot-fix.md` | SOT 정합성 수정 기록 |
| `.claude/skills/geode-portfolio/SKILL.md` | SOT 정합성 가이드 (수치/공식) |
