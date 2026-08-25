---
name: scandinavian-design
description: Apply a refined Scandinavian visual system with a neutral black-and-white foundation, restrained sans-serif typography, purposeful product imagery, generous spacing, clear page chapters, and minimal decoration. Use when the user invokes /scandinavian-design or requests a Nordic, monochrome, calm, spacious, restrained, or minimalist interface.
compatibility: Optional verification scripts require Node.js and playwright-core plus browser access to a user-approved URL.
---

# Scandinavian Design

## Verification Safety

The companion scripts can navigate a URL and write screenshots or measurement
artifacts. Run them only for a URL the user put in scope, normally localhost,
and use an isolated output directory. Do not capture authenticated/private
pages, cookies, tokens, personal data, or unrelated browser state. Review
artifacts before publishing them; screenshots can contain the same sensitive
data as the rendered page. The scripts do not need credential files or secrets.

## Core Direction

Create interfaces that feel calm, functional, refined, and intentionally simple. Use a neutral black-and-white foundation, functional restraint, and natural visual hierarchy. Build intermediate tones with alpha black over white, not warm or cool gray color casts. Let product imagery carry expression while the surrounding interface stays quiet.

Simplicity is not minimalism. Remove what is unnecessary so the primary task becomes obvious, but add context, labels, boundaries, or density when they make the interface easier to understand. Quiet must never mean empty, vague, or inert.

## Operating Posture

Act as a senior product designer with a bias toward restraint. Optimize in this order:

1. Comprehension and wayfinding
2. Task completion and accessibility
3. Information hierarchy and useful density
4. Brand and semantic meaning
5. Visual restraint and cohesion
6. Delight

Every element must earn its place. Every spacing, type, color, radius, and motion choice should be defensible in terms of the product rather than the style alone. Before making a visual change, confirm that it improves comprehension, hierarchy, efficiency, accessibility, or brand coherence; that it fits the surface's purpose, frequency of use, and required information density; that simplifying or reusing the existing system cannot achieve the same result; and that it preserves meaning, affordances, and semantic state. Reject changes whose only rationale is “it looks more Scandinavian.” A short list of high-confidence improvements is better than comprehensive restyling without purpose.

## Invocation Modes

Infer the mode from the request:

- **Apply** (default): inspect and redesign the requested surface, including its layout and composition when structure limits clarity, then verify it.
- **Review**: make no source edits; return prioritized findings, proposed changes, and important elements that should remain unchanged.
- **Prototype**: create three genuinely different Scandinavian directions in an isolated route or harness. Name each direction by its axis, such as Quiet, Editorial, or Utilitarian. Render one at a time at full size with realistic content and an instant switcher. Do not alter production UI until the user chooses.
- **Deep**: inspect the full relevant flow, including responsive states, interaction states, accessibility, and visual consistency.

Some surfaces are correctly loud, and the skill's instructions all point toward restraint whether or not restraint is the improvement. A publication or product whose visual volume is its identity can be made better structurally — fixing an inverted ranking, spending size on the thing that matters — while being made worse in voice. Where that tension exists, say which of the two you chose and why, rather than applying the rules and reporting the aggregate as an improvement by default.

Keep the requested product scope, but do not confuse scope control with layout preservation. A page redesign may change its grid, section order, grouping, hierarchy, and responsive composition without becoming a product-wide rebrand.

## Recon

Before designing or editing:

- Inspect the current interface in context, not only the target component.
- Identify the primary user task, common path, wayfinding, and escape routes.
- Map existing colors, typography, spacing, radii, borders, shadows, motion, components, and responsive conventions.
- Check installed UI primitives and dependencies. Reuse accessible existing components instead of hand-rolling dialogs, menus, selects, toasts, or focus behavior.
- Identify established brand elements and semantic colors that must survive.
- Decide whether the product is dense and operational, editorial, commercial, or expressive; restraint must fit its personality.
- Identify structural problems: weak page flow, repetitive card grids, fragmented hierarchy, poor text-to-media balance, or important content buried by the current layout.

## Visual System

Simplify the work into a clean, useful system:

- Preserve usability, accessibility, product meaning, and established brand identity.
- Prefer clear alignment and simple structure over decoration.
- Left-align text by default, including headings, labels, metadata, and footers. Centered text is a rare, deliberate exception, never a leftover from prior chrome, and never mixed with left-aligned siblings in the same group. A symmetric full-width band whose every member is centered — a closing lockup, a copyright row — is a coherent group rather than a leftover, and flushing one element of it to the left edge of a wide viewport strands it.
- Remove unnecessary color, heavy shadows, gradients, textures, containers, and ornamental chrome.
- Use one icon family with a single stroke weight and consistent optical size. Icons are monochrome ink on the same opacity ladder as text, not decoration. Emoji are not an icon family: they carry their own color, weight, and optical size, and no filter brings them onto the ink ladder. Remove them and let the labels carry the meaning. This applies to the interface's own iconography only. Emoji inside a product screenshot, someone's post, or a display name are content, and reaching in to edit them is the same mistake as repainting a photograph.
- Judge clutter by the number of visual weights, not the number of elements. In any region, decide which elements are peers and render peers identically: one size, one rung of the ink ladder, one baseline. A control's weight should track how often it is used, so the least-used control in a region must never be its heaviest element.
- Keep layouts balanced, calm, and easy to scan.
- Build long pages as a sequence of distinct, spacious chapters rather than a stack of similar cards.
- Keep copy short, direct, and specific.
- Reuse existing design tokens and components before introducing new ones.
- Reduce visual complexity instead of adding layers.

## Color and Opacity

Use these neutral defaults when the product does not already have an appropriate palette:

- Canvas: `#FFFFFF`
- Surface: `#FFFFFF`
- Primary ink: `#000000`
- Secondary ink: `rgb(0 0 0 / 64%)`
- Tertiary ink: `rgb(0 0 0 / 44%)`
- Border: `rgb(0 0 0 / 10%)`
- Strong border: `rgb(0 0 0 / 18%)`
- Hover fill: `rgb(0 0 0 / 5%)`
- Pressed fill: `rgb(0 0 0 / 9%)`
- Scrim: `rgb(0 0 0 / 44%)`

Use opacity to create hierarchy, not decoration:

- 90–100%: primary text and critical icons
- 60–70%: supporting text
- 40–50%: metadata and nonessential icons — this rung is for glyphs and genuinely optional text, and it does not reach 4.5:1 on white. Dense operational surfaces put real reading there: a tip-off time, a broadcast network, a struck-through price, a timestamp. When that is the case lift the rung to around 56% rather than accepting the band, and expect to do so often, because the range is written for editorial surfaces where metadata really is optional.
- 8–12%: borders and separators
- 4–6%: hover surfaces
- 8–10%: pressed or selected surfaces

These are three bands, and a product may ship four or more ink rungs. Keep the product's rung count rather than forcing it into three: distribute the extra rungs across and between the bands, and never collapse two rungs onto one value. A single sentence set across two rungs, or a flag distinguished from its own link by one rung, is a real distinction that flattening destroys.

Set ink with alpha colors rather than the `opacity` property. On a container it fades every descendant, and on a leaf it multiplies against whatever rung the element already sits on, quietly pushing supporting text below readable contrast. Do not introduce beige, cream, blue-gray, green-gray, or other tinted neutrals into interface chrome. Validate contrast rather than assuming these ranges are accessible in every context.

The rungs above assume ink on the canvas. Anything sitting on a tint — an alternating row fill, a raised card, a callout — has less contrast available than the table implies, and the lowest rungs are the ones that fail. Re-measure the quiet rungs against the surface they actually land on rather than against the page.

Where the product's neutrals already have zero channel spread and enough rungs, leave them as they are. Re-expressing a working hex ramp in alpha is risk at no visual gain, and it can actively break inverted contexts, since the same token often paints text over dark media where alpha black would disappear.

For dark-canvas products, invert the system with the same discipline: a near-black canvas such as `#0A0A0A` and white primary ink. The alpha values do not carry across unchanged. The same alpha buys more contrast on a dark canvas than on a light one — 64% white on `#0A0A0A` reaches 8.2:1 where 64% black on white reaches 6.7:1 — so reusing the light percentages makes supporting text and chrome louder rather than quieter, which is the opposite of the intent. Use roughly `rgb(255 255 255 / 56%)` for secondary ink and `rgb(255 255 255 / 36%)` for tertiary to match the hierarchy the light ladder produces. Borders are the exception and invert almost exactly, so `rgb(255 255 255 / 10–12%)` holds.

The tertiary rung is a faithful translation of a rung that was never accessible on white either, so it belongs to glyphs, dividers, and genuinely optional text. The moment real content sits there — a date, a struck-through price, a caption — lift it. On a true near-black canvas around `#0A0A0A`, 46% reaches 4.66:1 and is enough. That figure is sensitive to how dark the canvas actually is: at `#1F1F1F` it falls to 4.53:1 with no margin, and by `#262626` it fails. Dark products routinely ship surfaces in that range, so above about `#1A1A1A` use 50% instead.

Interaction fills do not invert one for one, because a light wash on a dark surround is a smaller perceptual step than a dark wash on a light one. Expect roughly one and a half times the light values: 9% for hover and 14% for pressed. Distinguish a resting *wash* from a resting *fill*. About 5% is right for a row or surface tint, but a button that must read as a control at rest needs roughly 9%, since 5% white on near-black moves the surface about twelve values out of 255 and does not read as filled at all.

Alpha-black fills stop being available. A recessed well built from `rgb(0 0 0 / 25%)` is invisible on a near-black canvas, so a surface that needs to sit *below* the page has to go lighter than it — which is the opposite of the instinct.

Correct ink before surfaces. Neutralizing the canvas first makes every remaining cast in the ink more obvious, not less, and the page looks worse in the middle of the job.

Do not introduce tinted dark grays, and judge that by channel spread rather than by eye. Correct a cast at roughly eight points of spread or more, leave it below five, and treat the band between as a judgment call — correct it where doing so costs nothing. Spread is far more visible in light ink than in a dark surface, so the same absolute cast matters at the top of the ladder and not at the bottom: a canvas two or three points off neutral is invisible, while ink whose channels sit ten or more points apart reads distinctly cool next to white.

Give the focus ring at least two pixels on a dark canvas, and never fewer than it already had. A hairline ring has no surrounding light field to register against, and the state color must stay whatever it was. Do not mix alpha-black and alpha-white neutrals within a single surface. A deliberately inverted surface — a light card on a dark page — is permitted and often useful, provided it carries its own consistent ladder throughout.

Keep interface chrome, typography, dividers, and data visualization neutral by default. A chart you are designing is chrome and goes neutral; a chart inside a product screenshot is content, and where two series are distinguished by color, that color is the legend and neutralizing it destroys the encoding. Product photography, screenshots, video, and narrative imagery may use expressive color; contain that color inside the media rather than leaking it into surrounding chrome.

Media that is mostly decoration is not protected by being media. A panel that is nine parts saturated gradient to one part product screenshot is the decorative gradient the escalation triggers name, and the fact that it ships inside a video or image frame does not change what it is. Judge by the proportion of the frame doing informational work.

A product mockup rebuilt in markup is still a screenshot. Marketing pages routinely reconstruct their own interface in DOM rather than shipping an image, and because that mockup reads the same tokens as the page around it, a token-level change reaches inside and repaints the depicted product — dimming an app's own body text, or graying a dashboard that is supposed to look like the real thing. Both the hues and the neutrals inside such a mockup belong to the product being depicted, so give it its own scope rather than exempting selectors one at a time.

A single established brand accent may be used sparingly for the primary action when it materially improves focus. Omit the accent when the user requests strict monochrome. Do not invent multiple decorative accents.

A brand mark is not chrome. Keep the product's own logo as it shipped, in full color, even as everything around it goes neutral. Where a brand publishes several colorways, "as shipped" has more than one answer: choose the published variant that survives the surface it now sits on, rather than leaving a white mark on a band you have just made light. On an otherwise monochrome page one small mark of signature color does more identity work than it did in the original, and desaturating it reads as decolorizing rather than designing. This covers the mark of the product you are designing; third-party marks appearing as customer logos, partner badges, or payment methods are social proof rather than identity, and go monochrome under Page Composition. Where a page carries both, the distinction is whose product the page belongs to.

A mark can also be a data label, which is a fourth case and the one most often got wrong. Where a third-party mark identifies the subject of a record — a team crest beside a score, a country flag beside a competitor, an exchange mark beside a quote — it is neither identity nor evidence. It is the row header, and it keeps its color regardless of who owns it. The test is the mark's job in that position, not its ownership.

The claim that a mark's shape carries its recognition has a size floor. It is true of a logo band at 120px and false at 16px, where hue is doing most of the discrimination: desaturating small marks does not quiet them, it collapses distinct ones into each other. Check the rendered size before deciding that monochrome is free.

Merchandising color is a third category, distinct from both. Loyalty badges, campaign fills, and promotional flashes are brand-adjacent but encode no state and identify nothing. Neutralize them.

A signature color may also attach to the product's own primary datum — the gold on a rating, the green on a score. Treat that as a brand mark rather than as an accent. It stays wherever the datum appears, including down a list of two hundred rows, because being recognized repeatedly is exactly what a signature mark is for and a product is not improved by making its most identifying element harder to spot. Ration it only where the same hue has spread onto things that are not the datum — a decorative bar, a promotional flash, a chart series borrowing the brand's color — which is merchandising wearing the brand rather than the brand doing its job.

Volume decides the ambiguous cases, and the measure is coverage rather than a raw count. A color that genuinely encodes state — an unread dot, a live indicator, an error badge — stops functioning as an accent when it saturates the region a reader scans: ten marks concentrated inside one card still say "this is the deals card," while the same ten scattered across a grid of a hundred say nothing at all.

Alignment beats both count and coverage. One small mark repeated at the same horizontal position down a list stacks into a dotted rule the length of the page, and it reads as a line long before its area reads as saturation. Where a repeated *accent* shares an axis, judge it as a rule rather than as a dot.

None of this reaches a brand mark or a signature datum color. The volume test governs merchandising fills and state colors, which lose their meaning when everything carries them. A signature mark does not: it is supposed to recur, and an argument that ends with "so we removed the thing the product is recognized by" has gone wrong somewhere earlier. When a rule and an identity collide, the identity wins and the rule needs the exception written down. Where a state color has stopped distinguishing anything, let the shape and the label carry it and take the hue out. Say that as a trade rather than a free removal, because something was being communicated before you took it.

Note that a promotional flash is settled by the paragraph above and never reaches this test: it encodes no state at any volume.

Do not quiet a disclosure below the prominence it shipped with. Sponsored labels, legal notices, and accessibility affordances are placed at a contrast their publisher chose and may be obliged to hold, so demoting them to the metadata rung is a different kind of failure from a design one.

Sweep `border-color` alongside backgrounds and text. A design system's default outline is often a tinted gray that reads as colored beside neutral ink, and it survives a neutralizing pass because the border itself looks intentional.

## Typography

Use one sans-serif family:

1. Preserve an existing well-made sans-serif product typeface.
2. Use the platform system font for native interfaces.
3. For the web, default to `Inter Variable`.
4. If already licensed, `Scto Grotesk A` may provide a more distinctive Nordic character.

Rule 1 is about quality and identity, not about serifs. A well-made serif that is a publication's typographic voice earns the same protection as a well-made grotesque, and replacing it needs the same argument of its own — stated out loud as a cost to brand voice. As written it is easy to read the rule as protecting sans faces only, which would mean a site with a beautiful grotesque keeps its typeface by rule while a site with a beautiful Cheltenham loses its typeface by rule, for no reason connected to either one working.

Rule 1 can also be satisfied by a family the page already owns but uses secondarily. Where a serif-led site also ships a well-made sans across its labels and controls, promoting that sans obeys the instruction while losing one less identity than importing a new family would. The difference between substituting the default web sans and promoting the product's own is the difference between a grayscale copy and a redesign.

Rule 3 applies only when rules 1 and 2 do not. Replacing a well-made product typeface is a change that needs an argument of its own, not a default. There is one argument that usually carries: a family shipping only two weights cannot express the label and heading ladder the rest of this system depends on, and substituting the default web sans is then legitimate — at the cost of brand voice, which is worth naming out loud. Check the weights of both families before a substitution, since the source's weights matter as much as the destination's: a page set entirely at 300 will silently resolve to 400 against a family that does not ship it, collapsing any distinction that weight was carrying. Check width class too. Grotesques run wider and taller in the x-height than most serifs, so a substitution at unchanged pixel sizes adds lines — replacing a condensed face one for one is the worst case, and headlines set in a narrow column can gain half their height again. Recover the width through tracking and leading before reaching for a smaller size.

A second family can be an encoding rather than a mixed system. Where one section of a publication is distinguished from another by typeface, flattening the two erases a distinction the reader was using, exactly as neutralizing a two-series chart destroys its legend. Look for a redundant label before deciding it is safe to collapse.

Do not introduce serif display type. Replace serif typography with the chosen sans-serif family unless the user explicitly asks to preserve it. Do not introduce a paid font without confirming it is licensed.

- Body: 16–18px, weight 400, line-height 1.5–1.6
- Labels and controls: weight 500
- Headings: weight 500–600 and avoid 700–900, but only after checking which weights the family actually ships. CSS matching resolves an unavailable 500 down to 400 and an unavailable 600 back to 700, so restating a weight on a two-weight family can silently erase the only thing separating a title from its description. Where the available weights cannot express the target, keep the weight the page already uses.
- Large headings: line-height 1.05–1.15 with slight negative tracking
- Body copy: neutral tracking
- Never use all-caps or forced uppercase text, including logos, labels, buttons, navigation, badges, and metadata. Use sentence case or natural title case. All-lowercase chrome is the same failure in the other direction, so correct lowercase navigation and control labels to sentence case as well. Both rules target styled casing: scope them to chrome, and leave titles, usernames, and running prose in the casing they shipped with. Where the capitals live in the markup rather than in CSS, leave them rather than applying a blanket transform that would corrupt adjacent strings. Check what the transform is doing before removing it: a `text-transform` sitting over a lowercase slug in the markup is *fixing* that markup, and clearing it produces the all-lowercase chrome this same rule forbids. Removing a transform also publishes whatever the markup happens to hold, which across a set of headings can be sentence case, all-lowercase, and shouted at once — so `text-transform: none` applied uniformly produces a page that reads as broken rather than restrained. Inspect the underlying strings before choosing one instruction for all of them.

Where the markup itself shouts, `text-transform: lowercase` with `::first-letter { text-transform: uppercase }` recovers sentence case. It is safe only for a single-sentence string with no proper noun and no acronym: it corrupts "RVs" and "FPS", it reaches only the first sentence across a `<br>`, and it is unsafe over templated copy whose future values you cannot see. Where none of the options is clean, say so and choose the lesser damage rather than reporting the rule as satisfied.
- Limit each screen to three or four clearly distinct text styles. This is written for editorial and marketing surfaces. A dense operational screen may legitimately need six, because a single row of data can consume four rungs — label, value, qualifier, and status — before any heading or story title exists. Count the rungs the data itself requires before treating the excess as a violation.
- Create hierarchy primarily through size and whitespace, not many weights
- Keep prose widths near 55–68 characters. Narrowing the measure on a figure-heavy page spends vertical height, so name that cost and move media into the freed horizontal space rather than letting it become dead gap.

## Surfaces and Structure

The numbers in this section are defaults for surfaces that have no coherent system of their own. Where the product already works to a consistent spacing scale, radius convention, or measure, conform to that system instead. Hitting these figures on a page that is already internally consistent replaces a working system with a different one, which is not an improvement.

- Use an 8px spacing rhythm, with 4px adjustments when necessary.
- Prefer 24px mobile margins and 40–64px desktop margins when the surrounding system permits.
- Give major editorial section transitions 96–144px on desktop and 64–96px on mobile when density permits; keep spacing inside related groups much tighter. Where a chapter already ends in a tall figure that pushes the next heading down on its own, the full transition stacks on top of that and opens a void beside the text; measure the rendered gap rather than applying the range blindly.
- Let whitespace separate sections before adding borders or backgrounds. Before adding a rule, name what would be ambiguous without it. If nothing would be, do not add it.
- Make space unambiguous with a ratio rather than a measurement. A heading belongs to the content beneath it when the gap above it is roughly three times the gap below it. Reaching for a rule usually means those two gaps are not yet different enough, and the rule compensates for that rather than for any real ambiguity.
- Keep rules countable per screen rather than per document. Roughly one chapter rule per viewport reads as structure on a long page, and the same fourteen rules counted as a document total read like a violation. One rule dividing chrome from content reads as structure; eighteen through an index read as a grid, and the eye starts tracking lines instead of words. Rails, section rules, group rules, and grid outlines compound quickly, and each looks locally defensible as it is added.
- Axis decides the trade between countable rules and density. Space can replace a horizontal rule, because it separates records that are read in sequence and the only cost is scroll. Space cannot replace a vertical one, because that rule separates columns read simultaneously and there is no gutter budget to widen. Cut horizontal rules first and keep the vertical ones that carry a multi-column grid.
- Never place a rule across a relationship. An image and its caption, a label and its field, a record and its metadata must read as one thing. A divider belongs between peers, not through a pair.
- Count boundaries per control, not per element. A bordered input inside a bordered form with a bordered submit button draws one control three times. A quiet fill can serve as the boundary instead of a rule.
- Leave quiet things quiet. A control that carried no boundary in the original does not earn one from the restyle, and boxing it promotes it above its neighbors for no reason.
- Lines are judged against each other, so deleting most of them promotes the survivors. After any pass that removes rules, re-examine the ones you kept.
- For repeated records, bind metadata to its record with a small gap and separate records with a much larger one; the eye groups on relative distance and needs no line. Reach for a hairline only when the space it would replace costs more density than the surface can afford, and name that trade when you make it.
- An alternating row fill is a third option alongside space and a hairline, and on a long list it beats both. It costs no vertical space and draws no line, where space can add thousands of pixels to a list of a few hundred records and hairlines put one rule every hundred pixels. Keep it very quiet, around 3%, and remember it moves the contrast arithmetic for everything sitting on it.
- The gap between records has to beat the largest gap *inside* one. Measure it rather than estimating: a card whose action row is pinned to the bottom leaves as much space inside a short item as a generous gutter provides between items, and the controls then read as belonging to the record below. Where the internal gap cannot be reduced, the gutter has to grow past it, and that costs density — which is the honest price of correct grouping.
- Prefer thin dividers over boxed cards when grouping remains clear.
- In segmented data regions, make shared borders meet cleanly. Dividers should span their intended container and adjacent cells should share edges without near-miss gaps caused by inconsistent padding.
- Keep corner radii restrained, usually 6–12px.
- Fully rounded pill buttons are allowed, but they are not the default. Choose the button shape as part of a component system, not per instance: equivalent primary CTAs must share the same radius, height, padding, and weight across the page. If the primary button is a pill, all primary buttons use that pill treatment; if it uses a restrained 6–10px radius, repeat that treatment consistently. Tags and filters may use a separate pill family because their role is distinct. Do not use pills for quantity controls, large fields, panels, or dense operational controls.
- Treat adjacent controls as one group: match their height, radius, and horizontal extent, and keep the gap between them smaller than the gap to anything around them. An icon that only restates the label beside it is decoration; keep icons where they replace a label, not where they duplicate one.
- Set spacing in one place per axis. Before adding padding to a wrapper, check whether the child already carries it, because inherited component CSS usually does and the two will stack.
- When you change padding, line-height, or height, re-check anything positioned against that element. Absolutely positioned toggles and inset indicators do not move with it, and an offset added to chase a symptom will drift the moment anything else changes.
- Avoid shadows unless elevation communicates behavior.
- When a shadow is necessary, use a barely visible neutral shadow rather than a large blur. On a near-black canvas a shadow does nothing at all, so the equivalent tool is a barely visible white radial glow, permitted under exactly the same test. The escalation trigger against glows targets decoration, not elevation.

## Structural Redesign

Layout and composition are in scope whenever the existing structure prevents the skill's hierarchy, clarity, or chapter rhythm. Preserve product meaning, content, capabilities, and interaction outcomes—not the existing DOM or arrangement.

Structural permission is not an obligation to rearrange everything. Preserve an effective composition when it already makes the primary task and content relationship obvious. Do not replace a strong, familiar product layout merely to make the redesign look more dramatic.

The skill may:

- Change page grids, column ratios, max widths, alignment, and section order.
- Move, merge, or split sections to create a clearer narrative and task flow.
- Replace repetitive card grids with dividers, feature rows, editorial chapters, or one dominant media composition.
- Recompose a hero, navigation, social-proof band, product demo, testimonial, comparison, or footer.
- Move supporting content closer to the control or outcome it explains.
- Turn a fragmented collection of small visuals into one large product screenshot, photograph, video, or illustration.
- Create or extract components when the new composition needs a cleaner implementation.
- Use different desktop and mobile compositions instead of preserving the same grid at smaller sizes.

Before making a large layout change, state the structural problem and the intended hierarchy. Prefer one coherent composition over many local rearrangements. Do not remove content or functionality merely to make the page look sparse.

A fill behind media may be an affordance rather than ornament. A flat panel under an image is often the placeholder that reserves the slot while the image loads, so removing it turns every unloaded image into a white hole with an orphaned caption beneath it. Check the unloaded state before clearing a background behind media.

Space reserved for decoration does not disappear when the decoration does. A band sized around an illustration, or a grid offset to clear an ornament, leaves a void that reads as emptiness rather than calm, and the same applies at small scale to a control still holding a box for an icon you removed. Close the freed space deliberately.

Where a piece of decoration is also a control's only visible output — a gradient that a selector changes, an animation a button replays — quieting it is not the same as deleting it. Desaturate it so the control still has something to say, and verify the states remain distinguishable from one another.

Where decoration varies per item, flatten it rather than desaturating it. A different hue behind each tile becomes a different grey behind each tile, which reads as an encoding that does not exist; a single flat surface says what the original said, which was nothing.

Then check whether the container still earns its place. Flattening per-item colour is how a grid of varied tiles becomes a wall of identical boxes — the uniformity is manufactured by the pass rather than inherited from the page, and a fill that was carrying variety is left carrying nothing. Usually the answer is to remove it and let the type hierarchy and the gutter do the grouping.

A tinted gradient laid over media is usually doing two jobs. Removing its hue also removes the scrim holding the text above it legible, so keep the scrim in neutral and drop only the color.

For commerce and product-detail pages:

- Make the product media the dominant visual anchor.
- On desktop, default to a large gallery on the left and a compact product and purchasing column on the right when the reading direction supports it.
- Keep the product name, price, options, availability, and primary purchase action together. Look specifically for interruptions: a promo tile, a planner link, or a services module wedged between the price and the delivery check splits the buying path just as effectively as putting them in separate chapters, and is far more common. Nothing that is not name, price, options, availability, or the purchase action belongs between them.
- Not every product has a variant control. Where there are no swatches or sizes, the options slot is filled by measurements, series, and catalog links, and those belong to the buying block rather than to the page around it.
- Media dominance is vertical as well as horizontal. A purchasing column that runs twice the height of the gallery has usually accumulated a tail of services, loyalty, financing, and protection modules below the purchase action; demote the tail rather than widening the column.
- When the purchase action is unavailable, the disabled control keeps its slot and states why at readable contrast — the reason you cannot buy something must never be the least legible text on the page. The live alternative, whether that is find similar, notify me, or change store, may carry the primary weight, because it is the only action the visitor can actually take.
- Baseline-align prices. Commerce systems habitually superscript the currency and the cents at half size; setting the whole price at one size and weight is usually the highest-impact restraint available on the page.
- Do not push the primary product image below a long purchasing preamble or reduce it to supporting decoration.
- On mobile, stack the gallery first, followed by product details, options, and the purchase action.
- Depart from this pattern only when another composition demonstrably improves product evaluation or task completion.

## Websites Without Source Access

This skill is written for codebases you can change — markup, styles, components, and tokens — and everything above assumes that control. Prefer editing the system over layering on top of it: change the token rather than overriding its consumers, delete the rule rather than resetting it, and split a component when one is doing two jobs. An override that fights the existing code is a finding about the code, not a solution.

When the target is a shipped or third-party site you cannot edit, read [websites.md](websites.md) for the constrained CSS-override fallback and its harness. Say plainly that this mode has a lower ceiling: composition bends only as far as the existing DOM allows, and a source-level redesign would go further.

## Page Composition and Storytelling

For marketing, editorial, and product pages:

- Give each major chapter one clear idea. A useful recurring structure is: concise heading, one short explanation, three or four feature summaries, then one dominant product visual.
- Alternate white and very light neutral section fills such as `rgb(0 0 0 / 4%)` to create rhythm before adding borders or containers. A dark canvas has no "very light fill" available, so its equivalent is one genuinely light band used as an interruption, or nothing at all.
- Use one oversized screenshot, photograph, video, or physical product composition as the visual anchor of a chapter. Let it approach full width when the content deserves immersion.
- Prefer a few large chapter containers over many small cards. A large media chapter may use a restrained radius; its internal content should not become another card grid.
- Keep customer and partner logos monochrome and evenly spaced so social proof remains quiet. This is the counterpart to keeping the product's own mark in full color: third-party marks are evidence, not identity, and a row of them in their native colors is the loudest band on most pages. The same applies to payment marks, whose shapes carry the recognition.
- Use a large testimonial, case-study image, or editorial collage as an occasional break in the system. One expressive interruption creates more character than decoration in every section.
- Present feature summaries as icon, short verb, and one-line outcome when cards are unnecessary.
- A two-tone inline heading — the first sentence at full ink and its continuation at around 60% on the same size and baseline — gives a marketing page real hierarchy without a second weight or a second size, and survives a neutralizing pass intact.
- One filled primary action per chapter is the pattern on a long marketing page, not a violation. Scope "sparingly" to the viewport rather than the document.
- Where a filled accent action sits near the product's own mark in the same region, the button will outrank the mark and the identity moment is lost. Make the button neutral and let the mark be the only color there. This assumes the mark has color to be outranked by; where the mark ships in black there is no identity moment to protect, and the accent may stay.
- The same reasoning applies to scale, not only color. Where a nameplate and a hero headline both shout at display size, the nameplate is competing with the page rather than heading it. Keeping an oversized mark is defensible only if the thing beside it is demoted, and then the mark does more identity work than it did originally, because it is no longer one of two.
- Let the footer become denser, but preserve the same typography, alignment, and neutral treatment.
- On mobile, preserve the order and hierarchy of each chapter. Stack and simplify; do not merely shrink the desktop composition.

## Interaction and Motion

Motion should feel quiet, immediate, and purposeful. Add it only for feedback, spatial continuity, state indication, or preventing a jarring change.

- Do not animate keyboard-initiated or extremely frequent actions.
- Reduce motion on interactions users perform tens of times per day.
- Keep ordinary UI motion under 300ms; use longer motion only for rare explanatory moments.
- Use `ease-out` for entrances and exits, `ease-in-out` for movement already on screen, and `ease` for color or hover transitions. Avoid `ease-in` for responsive UI.
- Prefer `transform` and `opacity`; avoid animating layout properties when a composited alternative exists.
- Never animate entrances from `scale(0)`. Use a subtle `scale(0.95–0.98)` with opacity when scale is appropriate.
- Anchor popovers and menus to their trigger; centered modals may remain centered.
- If press feedback suits the product, use a subtle `scale(0.97)` for roughly 100–160ms.
- Make rapidly triggered and gesture-driven motion interruptible.
- Honor `prefers-reduced-motion`, keeping useful color or opacity feedback while removing unnecessary movement.
- Gate hover-only motion behind `(hover: hover) and (pointer: fine)`.

Do not add animation merely to make a static interface feel polished. When uncertain, remove or reduce it.

Stopping perpetual decorative motion means returning it to rest, not freezing it. Disabling the animation alone leaves the element wherever its last frame put it, which for a marquee or a carousel is an arbitrary offset with content sliced off the container edge, and for a fade-in can be full transparency. Clear the transform or opacity the animation was driving as well, and confirm in a capture that the resting state is the one you intended.

## Escalation Triggers

Correct these when they occur within scope, unless brand or function clearly requires them:

- Tinted warm or cool grays standing in for neutral alpha-black tones, including default border colors inherited from a design system. A neutral derived systematically from the product's own brand color and used consistently is brand, not a tint to correct.
- Serif display typography or mixed serif/sans systems
- All-caps text or CSS `text-transform: uppercase`
- All-lowercase navigation or control labels
- Emoji used as interface iconography
- Dividers separating an element from its own caption, label, or metadata
- More rules on a screen than a reader can count, where space could do the same work. Rules that separate peers on a dense lookup surface are buying density, so ask what would replace them before counting them as clutter.
- Decorative gradients, textures, glows, or saturated color without meaning
- Large or layered shadows used only to make surfaces look premium
- Uniform cards of equal weight with no dominant element. A mixed composition of large and small containers each holding real product media is a bento, not a card grid, and flattening it removes the only place the product is shown rather than described.
- Pills used for ordinary rectangular controls or containers
- Mixed radii, heights, or padding among equivalent buttons and CTAs
- Inconsistent spacing, alignment, radii, border opacity, or icon treatment
- More type styles or font weights than the hierarchy needs
- Oversized headings or whitespace that reduce useful density
- Low-contrast body text or controls
- Color removed from status, focus, warning, error, success, selected, active, or destructive states
- A shape or glyph that accompanies a semantic color flattened away with it, leaving the state carried by hue alone. Check that what survives is still strong enough to read as a state: a selected tab distinguished from its neighbors only by a hairline once its fill goes neutral has technically kept a distinction and lost the affordance. Re-encode it rather than confirming a difference exists.
- Semantic color removed as a side effect of a typography or label rule. This is the usual way it is lost, not a deliberate palette change: a breaking-news flag and an ordinary kicker are often the same element with the same markup, distinguished only by which token they read, so a rule about size and tracking that also sets `color` will take the state with it while the token you carefully preserved stays untouched.
- Motion without a functional purpose

## Remediation Order

Prefer earlier moves over later ones:

1. Repair page flow, hierarchy, wayfinding, grouping, and control-to-content mapping.
2. Restructure the layout when the current composition blocks those goals.
3. Remove ornament, redundant surfaces, and duplicated labels.
4. Normalize spacing, alignment, and information density.
5. Normalize typography, measure, tracking, and line height.
6. Consolidate color, borders, radii, and elevation into shared tokens. Before changing any token, find every consumer and check what each uses it *for*, because the same value that quiets a fill will shout as a border: an accent taken to black calms every button reading it and turns a soft gold hairline into a hard black box, louder after the change than before. A design system also spends one token in several roles, so a brand token often turns out to define an active state as an alias, and a decorative badge may be borrowing the value of a genuine error state. Where one token serves two jobs, that is usually the finding — split it rather than picking a compromise value.
7. Refine controls, affordances, focus, hover, pressed, disabled, loading, empty, and error states.
8. Add or tune motion only after the static hierarchy works.

## Workflow

1. Determine the invocation mode and exact scope.
2. Complete recon and identify the primary task and hierarchy.
3. Evaluate candidate changes against the Operating Posture.
4. Apply changes in the Remediation Order, reusing and extending the existing system rather than creating a parallel one.
5. Verify mechanically and visually.
6. Report what changed, why, and what was deliberately preserved.

## Verification

### Browser verification

If any browser, preview, screenshot, or computer-use tool exists, visual verification is required:

1. Start or locate the real application and open the exact changed route.
2. Capture fixed desktop and mobile screenshots before and after the change.
3. Inspect the rendered screenshots rather than relying on code or DOM structure.
4. Measure interaction states rather than photographing them. A hover, focus, or pressed rule can lose a specificity contest and simply never fire, which no screenshot reveals, so read the computed style with the state forced rather than trusting that the rule you wrote is the rule that won.
5. Verify removals in the rendered output rather than in the declaration. Not every line is a border: interfaces draw them with `box-shadow`, a `::before` or `::after` bar, or an element collapsed to one pixel, so deleting a `border` is not evidence a line is gone. Enumerate what the interface actually paints rather than what the source mentions.
6. Inspect small controls zoomed. A few pixels of misalignment are invisible at page scale and will survive both a fix and a full-page verification pass.
7. Exercise the primary interaction, keyboard focus, hover or pressed states, and any changed responsive behavior.
8. Give the narrow viewport its own pass rather than a check. Padding, insets, and borders written for a wide column are a large fraction of a phone's width, and a rule that is a refinement at 1440px is a regression at 390px.
9. Check the browser console for errors and the viewport for clipping or horizontal overflow.
10. For long pages, scroll through every chapter and capture the full page or multiple viewport segments; the first fold is insufficient.
11. Correct visible problems and recapture until the result passes.

If no browser tooling is available, state that visual verification was not possible. Never claim a design was visually verified from code inspection alone.

Four checks in this list are hard to do by eye and are scripted in `scripts/`, alongside this file. Each takes a URL, normally a route on your dev server, and needs only `playwright-core` plus a local Chrome:

- `node scripts/lines.js <url>` — every rule the page paints, horizontal and vertical, with the mechanism drawing it. Run it after any pass that removes dividers.
- `node scripts/tints.js <url>` — colors whose channel spread marks them as tinted neutrals, plus an inventory of the saturated color a monochrome pass has to account for.
- `node scripts/density.js <url>` — items visible per screen, so a density claim is measured rather than estimated.
- `node scripts/bands.js <url>` — a long page sliced into reviewable viewport-height captures.

Read what they print rather than assuming a clean run means a clean page: each answers one narrow question, and the sections above say where each is known to mislead.

Name any state you could not reach rather than implying the whole surface was checked. Visited links, error and loading states, and authenticated views are commonly unreachable in a screenshot harness.

When a verification step fails repeatedly for the same reason, write the check as a script rather than resolving to be more careful. A tool that makes the failure visible is worth more than another instruction to watch for it.

Inspect the result at realistic desktop and mobile sizes with realistic content. Verify:

- The primary task and next action are obvious.
- Navigation answers where the user is, where they can go, and how they can leave.
- Grouping follows proximity and controls sit near what they affect.
- Long copy, empty states, loading, errors, and dense data do not break the layout.
- Contrast, keyboard navigation, visible focus, touch targets, and semantic states remain accessible.
- Larger text and narrow screens do not collapse the hierarchy.
- Nothing is painted twice. Matching the intended design is not evidence that your rule produced it, so check whether an existing declaration already draws the same pixels before adding your own.
- Nothing became accidentally meaningful. Removing color can reveal an encoding that was invisible when everything was saturated, and when the result is more legible than the original, stop there rather than pushing further toward monochrome.
- Left-aligning is finished only when the container, every intermediate wrapper, and the text node itself have been checked. Centering stacks, and correcting two of three mechanisms leaves a block that is centered while its text is flush left, which is worse than where you started.
- Long pages have deliberate chapter rhythm and do not become repetitive stacks of cards.
- The result passes the recognition test: shown only the after state, a designer who never saw the original would read it as an intentionally designed Scandinavian surface, not the original with color removed.
- Every interactive capability of the original surface — actions, controls, navigation, inputs, toggles — is still present and reachable. Inventory features, not only content and links; quieting a control is fine, dropping it is not.
- Expressive color stays inside purposeful media or the single permitted primary accent.
- Hover, pressed, selected, disabled, and destructive states remain distinguishable.
- Reduced-motion behavior is present where movement exists.
- The console is clean and existing checks still pass.

If visual inspection reveals ambiguity, excessive emptiness, or reduced efficiency, restore the necessary context or density and inspect again.

## Guardrails

Do not:

- Make destructive and neutral actions visually indistinguishable.
- Remove labels or boundaries needed for comprehension.
- Invent a primary call to action on a surface that never had one. One primary action means at most one, not exactly one.
- Desaturate a brand mark to match the palette.
- Replace an established product identity without being asked.
- Preserve a weak layout solely to minimize the code diff.
- Add dependencies when existing components can solve the problem well.
- Hide advanced functionality merely to create a cleaner screenshot.
- Confuse novelty with refinement.

## Review Output

For review mode:

1. Present findings in priority order.
2. For each finding, state the current condition, the proposed target, and why it improves the product.
3. Separate necessary corrections from optional polish.
4. Include a short **Preserve** section naming branding, semantic color, useful boundaries, density, or interaction patterns that should not change.
5. End with a verdict: already coherent, needs focused refinement, or needs structural redesign.

For apply mode, summarize the highest-impact changes, verification performed, and any limitation that could not be visually checked.

## Output Standard

The result should feel calm, functional, refined, and intentionally simple. When uncertain, make the interface quieter—not less usable.
