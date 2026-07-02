#!/usr/bin/env python3
"""Geodi — minimal, cute, *behaving* vector sprite (rose, with depth).

Soft chibi axolotl. One hue family (rose = identity), elevated from flat fill to
a highlight -> base -> shade gradient for volume, plus gloss + faint glow.
Feathery gill crown + full body (head, belly, arms, feet). Behaviour is pure-CSS:
bounce (squash/stretch) + blink + gill flutter. No JS, no libs. No outline.

Run:  uv run python scripts/visualizations/geodi_sprite.py
Out:  site/public/images/geodi.svg · geodi-dark.svg
Preview motion: open the .svg in a browser (qlmanage shows one static frame).
"""

from pathlib import Path

ROSE = "#F49BC4"  # identity base
ROSE_HI = "#FBD3E6"  # highlight
ROSE_DEEP = "#E06CA4"  # shaded depth
ROSE_L = "#FCDDEC"  # cheeks / eye sparkle
EYE = "#241019"  # warm near-black (eyes / mouth)
SUB = "#0B0A10"  # substrate
FILL = "url(#body)"  # the elevated rose gradient

DEFS = f"""
  <defs>
   <radialGradient id="body" gradientUnits="userSpaceOnUse" cx="94" cy="86" r="162">
    <stop offset="0" stop-color="{ROSE_HI}"/><stop offset=".45" stop-color="{ROSE}"/>
    <stop offset="1" stop-color="{ROSE_DEEP}"/>
   </radialGradient>
   <radialGradient id="glow" cx="50%" cy="45%" r="62%">
    <stop offset="0" stop-color="{ROSE}" stop-opacity=".16"/>
    <stop offset="1" stop-color="{ROSE}" stop-opacity="0"/>
   </radialGradient>
  </defs>"""

STYLE = """
  <style>
   @keyframes bob  {0%,100%{transform:translateY(0) scaleX(1) scaleY(1)}
                    50%{transform:translateY(-9px) scaleX(.98) scaleY(1.02)}}
   @keyframes blink{0%,90%,100%{transform:scaleY(1)} 95%{transform:scaleY(.08)}}
   @keyframes flut {0%,100%{transform:rotate(-5deg)} 50%{transform:rotate(6deg)}}
   #geodi{transform-box:fill-box;transform-origin:50% 92%;animation:bob 2.9s ease-in-out infinite}
   .eye {transform-box:fill-box;transform-origin:center;animation:blink 4.2s ease-in-out infinite}
   .gill{transform-box:fill-box;transform-origin:50% 86%;animation:flut 2.6s ease-in-out infinite}
   @media (prefers-reduced-motion:reduce){*{animation:none!important}}
  </style>"""


def frond(cx, cy, rx, ry, rot, delay):
    """One slender feathery gill frond: tapered stalk + two small side lobes."""
    return (
        f'<g class="gill" style="animation-delay:{delay}s">'
        f'<g transform="rotate({rot} {cx} {cy})">'
        f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{FILL}"/>'
        f'<circle cx="{cx - rx}" cy="{cy - ry * 0.3:.0f}" r="{rx * 0.7:.0f}" fill="{FILL}"/>'
        f'<circle cx="{cx + rx}" cy="{cy + ry * 0.15:.0f}" r="{rx * 0.7:.0f}" fill="{FILL}"/>'
        f"</g></g>"
    )


# three slender fronds per side, fanning UP-and-out (iconic axolotl gill crown)
_FRONDS = [
    (62, 74, 8, 30, -18, 0.0),
    (48, 88, 8, 32, -46, 0.3),
    (40, 106, 8, 30, -70, 0.6),
    (178, 74, 8, 30, 18, 0.15),
    (192, 88, 8, 32, 46, 0.45),
    (200, 106, 8, 30, 70, 0.75),
]


def gills(sway=0):
    """The gill crown; ``sway`` rotates every frond a few degrees (flutter frames)."""
    return "".join(frond(cx, cy, rx, ry, rot + sway, d) for cx, cy, rx, ry, rot, d in _FRONDS)


GILLS = gills(0)

# Body parts shared across the open / blink / sway variants (full body — head,
# belly, arms, feet, gloss, cheeks). Only the gills sway and the eyes blink.
BODY_PARTS = f"""
   <ellipse cx="120" cy="120" rx="84" ry="64" fill="{FILL}"/>
   <ellipse cx="120" cy="170" rx="56" ry="44" fill="{FILL}"/>
   <path d="M82,158 Q62,168 55,179" stroke="{FILL}" stroke-width="20" stroke-linecap="round" fill="none"/>
   <path d="M158,158 Q178,168 185,179" stroke="{FILL}" stroke-width="20" stroke-linecap="round" fill="none"/>
   <ellipse cx="98" cy="208" rx="15" ry="11" fill="{FILL}"/>
   <ellipse cx="142" cy="208" rx="15" ry="11" fill="{FILL}"/>
   <ellipse cx="92" cy="86" rx="34" ry="20" fill="{ROSE_HI}" opacity=".45" transform="rotate(-16 92 86)"/>
   <circle cx="74" cy="140" r="11" fill="{ROSE_L}" opacity=".6"/>
   <circle cx="166" cy="140" r="11" fill="{ROSE_L}" opacity=".6"/>"""

EYES_OPEN = f"""
   <ellipse class="eye" cx="90" cy="116" rx="10" ry="12" fill="{EYE}"/>
   <ellipse class="eye" cx="150" cy="116" rx="10" ry="12" fill="{EYE}"/>
   <circle cx="86" cy="111" r="3.4" fill="{ROSE_L}"/>
   <circle cx="146" cy="111" r="3.4" fill="{ROSE_L}"/>
   <path d="M96,134 Q120,152 144,134" stroke="{EYE}" stroke-width="4.5" fill="none" stroke-linecap="round"/>"""

EYES_SHUT = f"""
   <path d="M81,115 Q90,121 99,115" stroke="{EYE}" stroke-width="3.6" fill="none" stroke-linecap="round"/>
   <path d="M141,115 Q150,121 159,115" stroke="{EYE}" stroke-width="3.6" fill="none" stroke-linecap="round"/>
   <path d="M96,134 Q120,152 144,134" stroke="{EYE}" stroke-width="4.5" fill="none" stroke-linecap="round"/>"""


def sprite(sway=0, eyes=EYES_OPEN):
    return f"\n   {gills(sway)}{BODY_PARTS}{eyes}"


BODY = sprite(0, EYES_OPEN)  # geodi.svg (CSS-animated) + geodi-dark.svg


# Terminal animation frames (static): eyes-closed blink + gill crown swayed L/R.
BLINK = sprite(0, EYES_SHUT)
SWAY_L = sprite(-9, EYES_OPEN)
SWAY_R = sprite(9, EYES_OPEN)


# Bold full-body icon for tiny renders (terminal art). Bigger eyes + thick wide
# smile + chunky belly/feet so they survive downscaling. Static.
ICON = f"""
   {GILLS}
   <ellipse cx="120" cy="120" rx="84" ry="64" fill="{FILL}"/>
   <ellipse cx="120" cy="170" rx="56" ry="44" fill="{FILL}"/>
   <ellipse cx="96" cy="206" rx="18" ry="14" fill="{FILL}"/>
   <ellipse cx="144" cy="206" rx="18" ry="14" fill="{FILL}"/>
   <ellipse cx="86" cy="114" rx="14" ry="17" fill="{EYE}"/>
   <ellipse cx="154" cy="114" rx="14" ry="17" fill="{EYE}"/>
   <path d="M90,140 Q120,167 150,140" stroke="{EYE}" stroke-width="10" fill="none" stroke-linecap="round"/>"""


def svg(bg=None):
    back = ""
    if bg:
        back = (
            f'<rect width="240" height="240" fill="{bg}"/>'
            f'<rect width="240" height="240" fill="url(#glow)"/>\n'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240" '
        f'viewBox="0 0 240 240">{DEFS}{STYLE}\n{back}<g id="geodi">{BODY}\n</g>\n</svg>\n'
    )


def static_svg(body):
    """A single static frame (no CSS animation) — used for the baked terminal frames."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240" '
        f'viewBox="0 0 240 240">{DEFS}\n<g>{body}\n</g>\n</svg>\n'
    )


def main():
    out = Path(__file__).resolve().parents[2] / "site/public/images"
    (out / "geodi.svg").write_text(svg())
    (out / "geodi-dark.svg").write_text(svg(SUB))
    (out / "geodi-icon.svg").write_text(static_svg(ICON))
    (out / "geodi-blink.svg").write_text(static_svg(BLINK))
    (out / "geodi-sway-l.svg").write_text(static_svg(SWAY_L))
    (out / "geodi-sway-r.svg").write_text(static_svg(SWAY_R))
    print(f"geodi sprite -> {out}/geodi.svg (+dark, +icon, +blink, +sway-l/r)")


def _check():
    """ponytail: rose gradient wired, idle behaviour (bob/blink/flut) present."""
    s = svg()
    assert "url(#body)" in s and ROSE in s, "body gradient not wired"
    for name in ("bob", "blink", "flut"):
        assert f"@keyframes {name}" in s, f"missing {name}"
    assert 'class="eye"' in s and 'class="gill"' in s


if __name__ == "__main__":
    _check()
    main()
