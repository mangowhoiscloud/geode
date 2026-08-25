# Reporting

## Tone rules

The user explicitly set these constraints during the 2026-05-21 audit
session — encode them into every audit report.

| Rule | Reason |
|------|--------|
| No self-evaluative adjectives ("perfect", "great", "완벽") | The user reads them as naive self-congratulation |
| Past-tense "fix applied" + verification timestamp instead of "fixed it" | Claims must be verifiable per timestamp, not narrative |
| Always classify against the four categories (naive arrow / padding / glyph / frame-order) | Consistent taxonomy across audits |
| Never auto-apply a fix without user approval | The user judges whether a layout choice is intentional design vs. defect |

## Initial defect report — format

```markdown
**Bit X (zone, ~tt s)**
- Category N: <one-line symptom> at <file:line or arrow/box id>
- Category M: <one-line symptom>

→ Ask whether to fix. Do NOT proceed with edits until the user confirms.
```

Example from the 2026-05-21 hero audit:

```markdown
**Bit 9 (compute_fitness + auto-promote, ~25 s)**
- Category 1: arrow head s2→s3 too small at 1080p (head_size=0.24)
- Category 1: `→ auto-improve` label sliced by dashed line — label at
  `arrow.get_center() + UP * 0.25` and arrow is near-vertical
- Category 2: fitness formula right edge near canvas right limit
  (closing paren cropping risk)
```

## After-fix verification — format

```markdown
| # | Defect | Fix | Verification timestamp |
|---|--------|-----|------------------------|
| 1 | "GE ODE" letter-spacing drift in Bit 2 outer_label | dropped "GEODE " prefix | EN_9s OK |
| 2 | `→ auto-improve` label sliced by dashed line | label moved to `LEFT * 0.72 + UP * 0.05` | EN_25s OK |
| 3 | arrow head too small at 1080p | `head_size: 0.24 → 0.32` default | EN_25s OK (head visible) |
```

Verification timestamp must reference the actual extracted frame
(`EN_<t>s.png` from the post-fix render). "OK" means the model has Read the
frame and confirmed the targeted defect is no longer visible.

## Reporting categories the user may push back on

When the user says "this is intentional", record it as a known acceptable
state — don't try to fix it again next audit. Examples observed:
- The Bit 11-12 simultaneous display of multiple zones (s1, s2, s3) is
  intentional information accumulation, not a layering bug.
- The horizontal commit chain (a3f → b7c → d92 + HEAD) being separate from
  the outro vertical commit column is intentional visual contrast.

If a "same defect" appears across multiple audits despite user
intentionality, append a note to
[references/defect-catalogue.md](../references/defect-catalogue.md) under
"Intentional design exceptions" with the rationale.

## When the report is for a KO render

Korean-only defects (KO width vs EN, Pretendard glyph behavior) get the
same Bit / category format. Cross-reference EN versions of the same Bit if
they pass — the divergence often points to lang-specific layout sizing
that needs a per-lang constant.
