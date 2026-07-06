"""Phase D — Zhipu GLM-5V grounding (bbox → click) guards.

The pure conversion + response parsing are deterministic and unit-tested here;
the live GLM grounding call is `unverified — live test required` (no GLM
balance), exercised only with a mocked client.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core.tools import computer_grounding as cg
from core.tools.base import ToolContext


class TestBboxCenterToTarget:
    def test_full_box_maps_to_center(self) -> None:
        # [0,0,1000,1000] centre = (500,500) normalised → (640,400) on 1280x800
        assert cg.bbox_center_to_target([0, 0, 1000, 1000]) == (640, 400)

    def test_specific_box(self) -> None:
        # ctx7 example [599,99,799,599] centre (699,349) → (895,279)
        assert cg.bbox_center_to_target([599, 99, 799, 599]) == (895, 279)

    def test_custom_target_dims(self) -> None:
        # [0,0,1000,1000] centre on a 1000x1000 target = (500,500)
        assert cg.bbox_center_to_target(
            [0, 0, 1000, 1000], target_width=1000, target_height=1000
        ) == (
            500,
            500,
        )

    def test_out_of_range_box_is_clamped(self) -> None:
        x, y = cg.bbox_center_to_target([1800, 1800, 2000, 2000])  # well past 1000
        assert 0 <= x <= 1279 and 0 <= y <= 799


class TestParseGroundingBboxes:
    def test_strict_json_list(self) -> None:
        out = cg.parse_grounding_bboxes('[{"label": "Submit", "bbox_2d": [10, 20, 30, 40]}]')
        assert out == [{"label": "Submit", "bbox_2d": [10, 20, 30, 40]}]

    def test_markdown_fenced_json(self) -> None:
        text = '```json\n[{"bbox_2d": [1, 2, 3, 4]}]\n```'
        out = cg.parse_grounding_bboxes(text)
        assert out and out[0]["bbox_2d"] == [1, 2, 3, 4]

    def test_prose_with_bbox_regex_fallback(self) -> None:
        text = (
            'Sure — the button is here. The bounding box is "bbox_2d": [100, 200, 300, 400] for it.'
        )
        out = cg.parse_grounding_bboxes(text)
        assert out and out[0]["bbox_2d"] == [100, 200, 300, 400]

    def test_no_bbox_returns_empty(self) -> None:
        assert cg.parse_grounding_bboxes("I could not find that element.") == []

    def test_malformed_bbox_skipped(self) -> None:
        # 3-element bbox is not a valid box → skipped, not raised
        out = cg.parse_grounding_bboxes('[{"bbox_2d": [1, 2, 3]}]')
        assert out == []


def _fake_client(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    return client


class TestGlmLocate:
    def test_returns_click_coord_from_grounding(self) -> None:
        client = _fake_client('[{"bbox_2d": [599, 99, 799, 599]}]')
        with patch("core.llm.providers.glm._get_async_glm_client", return_value=client):
            coord = asyncio.run(cg.glm_locate("B64", "the cheapest item"))
        assert coord == (895, 279)

    def test_no_bbox_returns_none(self) -> None:
        client = _fake_client("I cannot find that element.")
        with patch("core.llm.providers.glm._get_async_glm_client", return_value=client):
            coord = asyncio.run(cg.glm_locate("B64", "nonexistent"))
        assert coord is None


class TestLocateWithActiveProvider:
    def test_glm_context_uses_glm_grounding(self) -> None:
        with patch.object(cg, "glm_locate", new=AsyncMock(return_value=(11, 22))) as glm_locate:
            coord = asyncio.run(
                cg.locate_with_active_provider(
                    "B64",
                    "submit",
                    tool_context=ToolContext(provider="glm", source="payg"),
                )
            )

        assert coord == (11, 22)
        glm_locate.assert_awaited_once()

    def test_openai_subscription_refuses_implicit_glm_fallback(self) -> None:
        with (
            patch.object(cg, "glm_locate", new=AsyncMock()) as glm_locate,
            pytest.raises(cg.VisualGroundingUnavailableError) as raised,
        ):
            asyncio.run(
                cg.locate_with_active_provider(
                    "B64",
                    "submit",
                    tool_context=ToolContext(provider="openai", source="subscription"),
                )
            )

        exc = raised.value
        assert exc.provider == "openai"
        assert exc.source == "subscription"
        assert "implicit GLM fallback is disabled" in str(exc)
        glm_locate.assert_not_awaited()
