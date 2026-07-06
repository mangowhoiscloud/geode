# Full-screen TUI parity map

This is the implementation map for moving GEODE's pre-full-screen terminal UI
contract into the prompt_toolkit full-screen surface. The goal is parity first,
not a new visual system.

The full-screen surface is experimental and opt-in. The default CLI remains the
legacy prompt/EventRenderer UI until this map reaches parity.

## Preserved GEODE contracts

- Header keeps the GEODE mascot/spec block.
- Final assistant text renders through a Markdown-capable path before display.
- Progress plan stays as one managed surface: `Tasks · n/m done`, completed
  checks, GEODE-rose active step, pending circles, and active-centered windowing.
- `update_plan` changes mutate the plan surface. They do not print raw
  `tool: update_plan` or duplicate an `Updated Plan` transcript block.
- Tool/thought progress belongs to the Activity surface, not the answer
  transcript.
- Turn metrics use the existing `Worked for ... · model · tokens · cost`
  language.

## Codex TUI feature map

In progress:

- Transcript scrollback / pager navigation:
  wheel, PageUp/PageDown, Home/End, Ctrl-Up/Down.
- Ctrl+O reasoning collapse:
  adapted as GEODE progress surface collapse/expand.
- Markdown-rendered assistant history:
  Rich Markdown to terminal rows.
- Running/completed tool activity cells:
  Activity pane summary.
- Plan update cell:
  adapted as fixed GEODE plan pane mutation.

Pending:

- Raw scrollback toggle.
- Ctrl+T transcript overlay.
- Copy last response.
- Clear terminal UI.
- External editor for draft.
- Composer shortcut overlay.
- Reverse history search.
- Vim composer mode.
- Reasoning effort up/down.
- Statusline/title configuration.

## First parity slice

The first slice covers the missing basics reported during full-screen testing:

- readable Markdown output
- scrollable transcript
- fixed plan surface updates
- activity summary surface
- Ctrl+O collapse/expand for progress detail
- GEODE-accent input border

Later slices should take the remaining rows from the map in order of direct user
workflow impact.
