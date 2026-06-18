"""GUI-element grounding for computer-use (Phase D — Zhipu GLM-5V).

Anthropic/OpenAI computer-use is *native*: the model emits actions
(click/type/...) in a loop. Zhipu GLM-5V is a *grounding* model — given a
screenshot + a target description it returns a bounding box for the element, in
a NORMALISED 0-1000 space (``bbox_2d: [x1, y1, x2, y2]``). To act on it, take the
box centre and de-normalise it into the harness target space; the harness then
maps target → screen as usual.

This module is the testable core: the pure bbox→coordinate conversion + the
grounding-response parser, plus a thin :func:`glm_locate` that wires them to the
GLM client. The full GLM-5V GUI-agent control loop (intent → ground → act →
re-screenshot) is a larger integration deferred to a live session.

# ref: ctx7 /websites/z_ai — docs.z.ai/guides/vlm/glm-5v-turbo + glm-4.6v
#   (grounding output is ``bbox_2d``; the docs SHOW examples — [95,152,192,825],
#    [599,99,799,599] — whose values are all sub-1000, CONSISTENT with a 0-1000
#    normalised grid. The docs do NOT state the normalisation explicitly, so
#    the 0-1000 assumption is INFERRED and part of the live-test gate below.)
# backend acceptance + coordinate space unverified — live test required: no GLM
#   balance to exercise the live grounding call (429 insufficient balance), so
#   the actual normalisation is confirmed only by a live round-trip. CANNOT §4d.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from core.tools.computer_use import TARGET_HEIGHT, TARGET_WIDTH

log = logging.getLogger(__name__)

# Inferred 0-1000 normalised grid (ctx7 examples are consistent; not stated
# explicitly — see the module header's live-test gate).
GROUNDING_NORM = 1000

# Default grounding model (z.ai). Routing/pricing already carry it.
GLM_GROUNDING_MODEL = "glm-5v-turbo"

_BBOX_RE = re.compile(
    r'"bbox_2d"\s*:\s*\[\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*\]'
)


def bbox_center_to_target(
    bbox_2d: list[int] | tuple[int, int, int, int],
    *,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
) -> tuple[int, int]:
    """Convert a normalised-1000 ``[x1, y1, x2, y2]`` box to a click point in the
    harness target space.

    The click point is the box centre, de-normalised from the 0-1000 grid onto
    ``target_width x target_height`` (the dims the harness then scales to the
    real screen via ``_scale_to_screen``). Coordinates are clamped into range so
    a slightly out-of-bounds box never produces a negative/overflow click.
    """
    x1, y1, x2, y2 = bbox_2d
    cx = (x1 + x2) / 2 / GROUNDING_NORM * target_width
    cy = (y1 + y2) / 2 / GROUNDING_NORM * target_height
    tx = max(0, min(target_width - 1, round(cx)))
    ty = max(0, min(target_height - 1, round(cy)))
    return tx, ty


def parse_grounding_bboxes(text: str) -> list[dict[str, Any]]:
    """Extract ``[{"label"?, "bbox_2d"}]`` from a GLM grounding response.

    Tolerant of markdown ```json fences and surrounding prose: first try strict
    JSON, then fall back to a regex sweep for every ``bbox_2d`` array (GLM often
    narrates before emitting the JSON). Boxes with non-4-length / non-int values
    are skipped rather than raising (boundary completeness).
    """
    out: list[dict[str, Any]] = []
    fenced = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    for candidate in (text, fenced):
        try:
            data = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and _is_bbox(item.get("bbox_2d")):
                out.append({"label": item.get("label", ""), "bbox_2d": list(item["bbox_2d"])})
        if out:
            return out
    # Regex fallback — pull every bbox_2d array out of free-form text.
    for m in _BBOX_RE.finditer(text):
        out.append({"label": "", "bbox_2d": [int(m.group(i)) for i in range(1, 5)]})
    return out


def _is_bbox(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(isinstance(v, (int, float)) for v in value)
    )


async def glm_locate(
    screenshot_b64: str,
    instruction: str,
    *,
    target_width: int = TARGET_WIDTH,
    target_height: int = TARGET_HEIGHT,
    model: str = GLM_GROUNDING_MODEL,
) -> tuple[int, int] | None:
    """Ground ``instruction`` against the screenshot → a click point, or ``None``.

    Sends the (image, instruction) to GLM-5V via the GLM OpenAI-compatible
    client, parses the first ``bbox_2d`` from the reply, and converts its centre
    to a harness target coordinate. Returns ``None`` when the model returns no
    usable box.

    The LIVE GLM call is ``unverified — live test required`` (no GLM balance);
    the parsing + conversion are unit-tested with a mocked client.
    """
    from core.llm.providers.glm import _get_async_glm_client

    client = _get_async_glm_client()
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Locate this UI element: {instruction}. "
                            'Respond ONLY with JSON [{"bbox_2d": [x1,y1,x2,y2]}] '
                            "in 0-1000 normalised coordinates."
                        ),
                    },
                ],
            }
        ],
        max_tokens=512,
    )
    text = (resp.choices[0].message.content or "") if resp.choices else ""
    boxes = parse_grounding_bboxes(text)
    if not boxes:
        log.info("glm_locate: no bbox for instruction=%r", instruction[:80])
        return None
    return bbox_center_to_target(
        boxes[0]["bbox_2d"], target_width=target_width, target_height=target_height
    )
